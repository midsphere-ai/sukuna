"""Backend sync service — propagate run lifecycle and usage to Django models."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from contextlib import suppress
from typing import Any

from asgiref.sync import sync_to_async
from django.utils import timezone
from exo.models.provider import get_provider
from exo.types import SystemMessage, UserMessage

from agent_server.models import (
    DjangoAgentRun,
    DjangoConversation,
    DjangoConversationFile,
    DjangoConversationPlan,
    DjangoStoredFile,
)

log = logging.getLogger("agent_server")

# ── Config constants (read from env, mirroring server.py definitions) ────────
_g = os.getenv  # shorthand

_super_provider = _g("MANAGED_SUPER_LLM_PROVIDER", "openai")
_super_model = _g("MANAGED_SUPER_LLM_MODEL", "zai-org/glm-5-maas")
AGENT_MODEL: str = _g("AGENT_MODEL", f"{_super_provider}:{_super_model}")
TITLE_GEN_MODEL: str = _g("TITLE_GEN_MODEL", AGENT_MODEL)
TITLE_GEN_MAX_TITLE_CHARS: int = max(int(_g("TITLE_GEN_MAX_TITLE_CHARS", "60")), 20)
TITLE_GEN_ENABLED: bool = _g("TITLE_GEN_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
_TITLE_GEN_TIMEOUT_MAX_SECONDS = 15.0
TITLE_GEN_TIMEOUT_SECONDS: float = min(
    max(float(_g("TITLE_GEN_TIMEOUT_SECONDS", "15.0")), 0.1),
    _TITLE_GEN_TIMEOUT_MAX_SECONDS,
)
TITLE_GEN_MAX_PROMPT_CHARS: int = max(int(_g("TITLE_GEN_MAX_PROMPT_CHARS", "500")), 50)
TITLE_GEN_MAX_RESPONSE_CHARS: int = max(int(_g("TITLE_GEN_MAX_RESPONSE_CHARS", "256")), 64)
TITLE_GEN_MAX_PARALLEL: int = max(int(_g("TITLE_GEN_MAX_PARALLEL", "1")), 1)
_TITLE_GEN_XML_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TITLE_GEN_UNUSED_TOKEN_RE = re.compile(r"^(?:<unused\d+>\s*)+$", re.IGNORECASE)
_TITLE_GEN_SEMAPHORE = asyncio.Semaphore(TITLE_GEN_MAX_PARALLEL)

# Terminal statuses that must never be overwritten.
_TERMINAL_STATUSES: set[str] = {"completed", "failed", "cancelled"}


def _get_run(run_id: str) -> DjangoAgentRun | None:
    return DjangoAgentRun.objects.filter(run_id=run_id).order_by("-updated_at").first()


def _apply_usage(run_obj: DjangoAgentRun, usage: Any) -> bool:
    if usage is None:
        return False
    usage_update: dict[str, int | float] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        val = getattr(usage, key, None)
        if val is not None:
            with suppress(ValueError, TypeError):
                usage_update[key] = int(val)
    cost = getattr(usage, "cost_usd", None)
    if cost is not None:
        with suppress(ValueError, TypeError):
            usage_update["cost_usd"] = float(cost)
    # Tool call counters
    for key in ("native_tool_calls", "mcp_tool_calls"):
        val = getattr(usage, key, None)
        if val is not None and val > 0:
            with suppress(ValueError, TypeError):
                usage_update[key] = int(val)
    if not usage_update:
        return False
    metadata = dict(run_obj.metadata or {})
    existing_usage = dict(metadata.get("sandbox_usage") or {})
    existing_usage.update(usage_update)
    existing_usage["updated_at"] = timezone.now().isoformat()
    metadata["sandbox_usage"] = existing_usage
    run_obj.metadata = metadata
    return True


def _update_conversation_task(run_obj: DjangoAgentRun) -> None:
    if run_obj.conversation_id is None:
        return
    try:
        conv = DjangoConversation.objects.filter(pk=run_obj.conversation_id).first()
        if conv is None:
            return
        if conv.current_task_id != run_obj.id:
            conv.current_task_id = run_obj.id
            conv.save(update_fields=["current_task_id"])
    except Exception:
        log.warning(
            "Failed to update conversation current_task_id for run %s",
            run_obj.id,
            exc_info=True,
        )


_TITLE_GEN_PROMPT = (
    "Generate a concise conversation title (max 60 chars).\n"
    "Return ONLY XML in this exact format: <title>your title</title>\n"
    "No JSON. No markdown. No quotes. No extra text."
)


def _truncate_title(value: str, max_len: int = TITLE_GEN_MAX_TITLE_CHARS) -> str:
    """Trim title to a short readable line, keeping whole words when possible."""
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    cutoff = text[:max_len].rstrip()
    if " " in cutoff:
        cutoff = cutoff.rsplit(" ", 1)[0].strip()
    return cutoff or text[:max_len].strip()


def _fallback_title(user_prompt: str) -> str:
    """Fast deterministic title fallback with no model dependency."""
    text = (user_prompt or "").strip()
    if not text:
        return "New conversation"

    first_line = re.sub(r"\s+", " ", text.splitlines()[0]).strip()
    first_clause = re.split(r"[.!?]", first_line, maxsplit=1)[0].strip()
    return _truncate_title(first_clause or first_line) or "New conversation"


def _title_gen_log_preview(raw: str, limit: int = 180) -> str:
    """Compact raw model output for logs (single line, bounded length)."""
    compact = re.sub(r"\s+", " ", raw).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}…"


def _sanitize_generated_title(value: str) -> str | None:
    """Normalize model title candidates and drop placeholder/null-ish values."""
    title = str(value or "").strip()
    title = title.strip("`'\" ").strip()
    if not title:
        return None
    if _TITLE_GEN_UNUSED_TOKEN_RE.fullmatch(title):
        return None
    if title.lower() in {"null", "none", "n/a"}:
        return None
    return _truncate_title(title) or None


def _parse_llm_title_response(raw: str) -> str | None:
    """Extract a usable title from LLM output (<title>...</title> only)."""
    text = (raw or "").strip()
    if not text:
        return None

    match = _TITLE_GEN_XML_TITLE_RE.search(text)
    if not match:
        return None

    extracted = (match.group(1) or "").strip()
    if len(extracted) > TITLE_GEN_MAX_RESPONSE_CHARS:
        extracted = extracted[:TITLE_GEN_MAX_RESPONSE_CHARS]
    return _sanitize_generated_title(extracted)


async def _generate_conversation_title_and_icon(
    conversation_id: str,
    user_prompt: str,
) -> None:
    """Background task: generate conversation title for a new conversation.

    Function name is retained for compatibility with existing imports/call sites.
    Icon generation is intentionally disabled. This path is best-effort and
    bounded with timeout/concurrency limits so it cannot block the main run.

    The ``storage_conversation`` row is backend-owned (``managed=False``) and is
    normally created by the Django backend in ``do_atomic_reservation`` before
    the run is forwarded to the sandbox.  In local mode — where the frontend
    hits the sandbox directly with no backend in front — the row does not
    exist, so we skip title generation entirely instead of creating backend
    resources from the sandbox (which would bypass auth and break FK invariants).
    """
    try:
        fallback_title = _fallback_title(user_prompt)

        @sync_to_async
        def _update_title(*, title: str, only_if_empty: bool = False) -> None:
            conv = DjangoConversation.objects.filter(pk=conversation_id).first()
            if conv is None:
                return
            safe_title = _sanitize_generated_title(title)
            if not safe_title:
                return
            if only_if_empty and conv.title:
                return
            if conv.title != safe_title:
                conv.title = safe_title
                conv.save(update_fields=["title"])

        conv_exists = await sync_to_async(DjangoConversation.objects.filter(pk=conversation_id).exists)()
        if not conv_exists:
            log.info(
                "Title generation: skipping for conversation %s — no storage_conversation "
                "row exists. This is expected in local mode where the sandbox is hit "
                "directly without the Django backend creating the conversation first.",
                conversation_id,
            )
            return

        if fallback_title:
            # Ensure a title is available immediately without waiting for LLM.
            await _update_title(title=fallback_title, only_if_empty=True)

        if not TITLE_GEN_ENABLED:
            log.debug("Title generation disabled via TITLE_GEN_ENABLED for conversation %s", conversation_id)
            return

        # Drop optional refinement when worker is busy instead of queueing.
        if _TITLE_GEN_SEMAPHORE.locked():
            log.debug("Title generation busy; skipping LLM refinement for conversation %s", conversation_id)
            return

        async with _TITLE_GEN_SEMAPHORE:
            provider = get_provider(TITLE_GEN_MODEL)
            try:
                response = await asyncio.wait_for(
                    provider.complete(
                        [
                            SystemMessage(content=_TITLE_GEN_PROMPT),
                            UserMessage(content=user_prompt[:TITLE_GEN_MAX_PROMPT_CHARS]),
                        ],
                        temperature=0.2,
                        max_tokens=40,
                    ),
                    timeout=TITLE_GEN_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                log.warning(
                    "Title generation timed out after %.1fs for conversation %s",
                    TITLE_GEN_TIMEOUT_SECONDS,
                    conversation_id,
                )
                return

        llm_title = _parse_llm_title_response(response.content or "")
        if not llm_title:
            log.warning(
                "Title generation: could not parse model output for conversation %s: %s",
                conversation_id,
                _title_gen_log_preview(response.content or ""),
            )
            return

        await _update_title(title=llm_title)
        log.info(
            "Generated conversation title for %s: %r",
            conversation_id,
            llm_title,
        )
    except Exception:
        log.warning(
            "Title generation failed for conversation %s",
            conversation_id,
            exc_info=True,
        )


async def sync_run_started(run_id: str, *, sandbox_id: str | None = None) -> None:
    @sync_to_async
    def _do() -> None:
        run_obj = _get_run(run_id)
        if run_obj is None:
            log.warning("sync_run_started: no AgentRun found for run_id=%s", run_id)
            return
        if run_obj.status in _TERMINAL_STATUSES:
            log.debug("sync_run_started: run %s already terminal (%s), skipping", run_id, run_obj.status)
            return
        update_fields: list[str] = ["updated_at"]
        run_obj.status = "running"
        update_fields.append("status")
        if run_obj.started_at is None:
            run_obj.started_at = timezone.now()
            update_fields.append("started_at")
        if sandbox_id and run_obj.sandbox_id != sandbox_id:
            run_obj.sandbox_id = sandbox_id
            update_fields.append("sandbox_id")
        run_obj.updated_at = timezone.now()
        run_obj.save(update_fields=update_fields)
        _update_conversation_task(run_obj)

    try:
        await _do()
    except Exception:
        log.error("sync_run_started failed for run_id=%s", run_id, exc_info=True)


async def sync_run_usage(run_id: str, usage: Any, *, sandbox_id: str | None = None) -> None:
    @sync_to_async
    def _do() -> None:
        run_obj = _get_run(run_id)
        if run_obj is None:
            log.warning("sync_run_usage: no AgentRun found for run_id=%s", run_id)
            return
        update_fields: list[str] = []
        if _apply_usage(run_obj, usage):
            update_fields.append("metadata")
        if sandbox_id and run_obj.sandbox_id != sandbox_id:
            run_obj.sandbox_id = sandbox_id
            update_fields.append("sandbox_id")
        if update_fields:
            update_fields.append("updated_at")
            run_obj.updated_at = timezone.now()
            run_obj.save(update_fields=update_fields)

    try:
        await _do()
    except Exception:
        log.error("sync_run_usage failed for run_id=%s", run_id, exc_info=True)


async def sync_run_completed(run_id: str, usage: Any, *, sandbox_id: str | None = None) -> None:
    @sync_to_async
    def _do() -> None:
        run_obj = _get_run(run_id)
        if run_obj is None:
            log.warning("sync_run_completed: no AgentRun found for run_id=%s", run_id)
            return
        if run_obj.status in _TERMINAL_STATUSES:
            log.debug("sync_run_completed: run %s already terminal (%s), skipping", run_id, run_obj.status)
            return
        update_fields: list[str] = ["status", "updated_at"]
        run_obj.status = "completed"
        if run_obj.finished_at is None:
            run_obj.finished_at = timezone.now()
            update_fields.append("finished_at")
        _apply_usage(run_obj, usage)
        update_fields.append("metadata")
        if sandbox_id and run_obj.sandbox_id != sandbox_id:
            run_obj.sandbox_id = sandbox_id
            update_fields.append("sandbox_id")
        run_obj.updated_at = timezone.now()
        run_obj.save(update_fields=update_fields)
        _update_conversation_task(run_obj)

    try:
        await _do()
    except Exception:
        log.error("sync_run_completed failed for run_id=%s", run_id, exc_info=True)

    try:
        from agent_server.engine.billing import settle_hold_for_run

        await sync_to_async(settle_hold_for_run)(run_id)
    except Exception:
        log.error("credit-settle failed for run_id=%s", run_id, exc_info=True)

    await _process_injection_queue_for_run(run_id, "run_completed")


async def sync_run_failed(
    run_id: str,
    error: str,
    usage: Any,
    *,
    sandbox_id: str | None = None,
) -> None:
    @sync_to_async
    def _do() -> None:
        run_obj = _get_run(run_id)
        if run_obj is None:
            log.warning("sync_run_failed: no AgentRun found for run_id=%s", run_id)
            return
        if run_obj.status in _TERMINAL_STATUSES:
            log.debug("sync_run_failed: run %s already terminal (%s), skipping", run_id, run_obj.status)
            return
        update_fields: list[str] = ["status", "updated_at"]
        run_obj.status = "failed"
        if error:
            run_obj.error = error
            update_fields.append("error")
        if run_obj.finished_at is None:
            run_obj.finished_at = timezone.now()
            update_fields.append("finished_at")
        _apply_usage(run_obj, usage)
        update_fields.append("metadata")
        if sandbox_id and run_obj.sandbox_id != sandbox_id:
            run_obj.sandbox_id = sandbox_id
            update_fields.append("sandbox_id")
        run_obj.updated_at = timezone.now()
        run_obj.save(update_fields=update_fields)
        _update_conversation_task(run_obj)

    try:
        await _do()
    except Exception:
        log.error("sync_run_failed failed for run_id=%s", run_id, exc_info=True)

    try:
        from agent_server.engine.billing import refund_hold_for_run

        await sync_to_async(refund_hold_for_run)(run_id, error or "Run failed")
    except Exception:
        log.error("credit-refund failed for run_id=%s", run_id, exc_info=True)

    await _process_injection_queue_for_run(run_id, "run_failed")


async def sync_run_cancelled(run_id: str, usage: Any, *, sandbox_id: str | None = None) -> None:
    @sync_to_async
    def _do() -> None:
        run_obj = _get_run(run_id)
        if run_obj is None:
            log.warning("sync_run_cancelled: no AgentRun found for run_id=%s", run_id)
            return
        if run_obj.status in _TERMINAL_STATUSES:
            log.debug("sync_run_cancelled: run %s already terminal (%s), skipping", run_id, run_obj.status)
            return
        update_fields: list[str] = ["status", "updated_at"]
        run_obj.status = "cancelled"
        if run_obj.finished_at is None:
            run_obj.finished_at = timezone.now()
            update_fields.append("finished_at")
        _apply_usage(run_obj, usage)
        update_fields.append("metadata")
        if sandbox_id and run_obj.sandbox_id != sandbox_id:
            run_obj.sandbox_id = sandbox_id
            update_fields.append("sandbox_id")
        run_obj.updated_at = timezone.now()
        run_obj.save(update_fields=update_fields)
        _update_conversation_task(run_obj)

    try:
        await _do()
    except Exception:
        log.error("sync_run_cancelled failed for run_id=%s", run_id, exc_info=True)

    try:
        from agent_server.engine.billing import refund_hold_for_run

        await sync_to_async(refund_hold_for_run)(run_id, "Run cancelled")
    except Exception:
        log.error("credit-refund failed for run_id=%s", run_id, exc_info=True)

    await _process_injection_queue_for_run(run_id, "run_cancelled")


async def _process_injection_queue_for_run(run_id: str, terminal_event: str) -> None:
    """On terminal, dequeue next injection (on success) or clear queue (on failure)."""
    try:
        run_obj = await sync_to_async(_get_run)(run_id)
        if run_obj is None or not run_obj.conversation_id:
            return
        conv_id = str(run_obj.conversation_id)

        from agent_server.infra.injection_queue import (
            clear_queue,
            dequeue,
            discard_deleted_users,
        )

        if terminal_event != "run_completed":
            cleared = await sync_to_async(clear_queue)(conv_id)
            if cleared:
                log.info(
                    "[INJECT-QUEUE] Cleared %d entries after %s for conversation %s",
                    cleared,
                    terminal_event,
                    conv_id,
                )
            return

        await sync_to_async(discard_deleted_users)(conv_id)
        entry = await sync_to_async(dequeue)(conv_id)
        if entry is None:
            return
        log.info(
            "[INJECT-QUEUE] Dequeued injection for conversation %s (user=%s) — "
            "auto-send will be handled by the next run starting on this conversation",
            conv_id,
            entry.user_id,
        )
    except Exception:
        log.warning(
            "[INJECT-QUEUE] Processing failed for run %s (%s)",
            run_id,
            terminal_event,
            exc_info=True,
        )


async def sync_plan(
    conversation_id: str,
    sandbox_id: str,
    goal: str,
    phases: list[dict[str, Any]],
    current_phase_id: str,
) -> None:
    @sync_to_async
    def _do() -> None:
        now = timezone.now()
        try:
            plan = DjangoConversationPlan.objects.filter(conversation_id=conversation_id).first()
            if plan is not None:
                plan.goal = goal
                plan.phases = phases
                plan.current_phase_id = current_phase_id
                plan.sandbox_id = sandbox_id
                plan.updated_at = now
                plan.save(
                    update_fields=[
                        "goal",
                        "phases",
                        "current_phase_id",
                        "sandbox_id",
                        "updated_at",
                    ]
                )
            else:
                DjangoConversationPlan.objects.create(
                    id=uuid.uuid4(),
                    conversation_id=conversation_id,
                    goal=goal,
                    phases=phases,
                    current_phase_id=current_phase_id,
                    sandbox_id=sandbox_id,
                    created_at=now,
                    updated_at=now,
                )
        except Exception:
            log.error(
                "sync_plan: failed for conversation_id=%s",
                conversation_id,
                exc_info=True,
            )

    try:
        await _do()
    except Exception:
        log.error(
            "sync_plan failed for conversation_id=%s",
            conversation_id,
            exc_info=True,
        )


async def sync_attachment(
    *,
    file_path: str,
    conversation_id: str,
    owner_id: int | None = None,
    display_name: str | None = None,
    mime_type: str = "",
) -> dict | None:
    @sync_to_async
    def _do() -> dict | None:
        import mimetypes as _mimetypes
        import os as _os

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        if not _os.path.isfile(file_path):
            log.warning("sync_attachment: not a regular file or not found: %s", file_path)
            return None

        name = display_name or _os.path.basename(file_path)
        size = _os.path.getsize(file_path)
        resolved_mime = mime_type or _mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        with open(file_path, "rb") as f:
            content = f.read()

        ext = name.rsplit(".", 1)[-1] if "." in name else "bin"
        file_id = uuid.uuid4()
        owner_dir = str(owner_id) if owner_id else "sandbox"
        storage_path = f"uploads/{owner_dir}/{file_id}.{ext}"

        saved_path = default_storage.save(storage_path, ContentFile(content))

        now = timezone.now()

        DjangoStoredFile.objects.create(
            id=file_id,
            owner_id=owner_id,
            file=saved_path,
            name=name,
            size=size,
            mime_type=resolved_mime,
            uploaded_at=now,
            updated_at=now,
        )

        if conversation_id:
            DjangoConversationFile.objects.create(
                conversation_id=conversation_id,
                stored_file_id=file_id,
            )

        try:
            url = default_storage.url(saved_path)
        except Exception:
            url = saved_path

        log.info(
            "sync_attachment: stored file_id=%s name=%s size=%d path=%s",
            file_id,
            name,
            size,
            saved_path,
        )

        return {"file_id": str(file_id), "name": name, "size": size, "url": url}

    try:
        return await _do()
    except Exception:
        log.error(
            "sync_attachment failed for file=%s conversation=%s",
            file_path,
            conversation_id,
            exc_info=True,
        )
        return None
