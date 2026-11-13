"""File operations, health, conversations, and skills endpoints.

GET    /files/tree   -> Recursive directory tree
GET    /files/read   -> Read file content as text
PUT    /files/write  -> Write (create or overwrite) a file
POST   /files/create -> Create a new file or directory
DELETE /files/delete -> Delete a file or directory
GET    /files/watch  -> SSE stream of filesystem changes (polling-based)
GET    /health       -> Liveness check with active run count
POST   /expose-port  -> Expose a sandbox port and extend idle-pause timer
GET    /conversations -> List conversations grouped by conversation_id
GET    /skills       -> List all loaded skills
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path as FilePath
from typing import Any

from asgiref.sync import sync_to_async
from django.http import StreamingHttpResponse
from django.utils import timezone
from ninja import Body, Schema
from ninja.errors import HttpError

from agent_server.auth import require_scope
from agent_server.config import (
    SANDBOX_WORKSPACE_ROOT,
    SUKUNA_SANDBOX_ID,
)
from agent_server.infra import (
    _run_tasks,
    files_router,
    health_router,
    skill_registry,
    skills_router,
)
from agent_server.models import (
    DjangoE2bSandbox,
    SandboxRun,
)

log = logging.getLogger("agent_server")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 10 — FILE OPERATIONS ENDPOINTS                                    ║
# ║                                                                            ║
# ║  GET    /files/tree   → Recursive directory tree                           ║
# ║  GET    /files/read   → Read file content as text                          ║
# ║  PUT    /files/write  → Write (create or overwrite) a file                 ║
# ║  POST   /files/create → Create a new file or directory                     ║
# ║  DELETE /files/delete → Delete a file or directory                         ║
# ║  GET    /files/watch  → SSE stream of filesystem changes (polling-based)   ║
# ║                                                                            ║
# ║  All paths are resolved relative to SANDBOX_WORKSPACE_ROOT with security   ║
# ║  checks: null-byte rejection, traversal blocking, symlink escape           ║
# ║  detection, and a sensitive-path blocklist.                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

_FILES_ROOT = FilePath(SANDBOX_WORKSPACE_ROOT)

# Sensitive paths that must never be accessed through the file API, even if
# they happen to sit under the sandbox root (e.g. when root is ``/``).
_SENSITIVE_PREFIXES: tuple[str, ...] = (
    "/etc/shadow",
    "/etc/passwd",
    "/etc/gshadow",
    "/proc",
    "/sys",
)
_SENSITIVE_NAMES: frozenset[str] = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".ssh",
        ".vault-token",
        ".npmrc",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
    }
)


def _resolve_sandbox_path(path: str, *, must_exist: bool = True) -> FilePath:
    """Resolve *path* to an absolute ``FilePath`` inside ``_FILES_ROOT``.

    Security checks applied (in order):
    1. Null-byte rejection
    2. ``..`` component rejection (including ``....//`` variants)
    3. Resolved-path prefix check (catches symlink escapes)
    4. Symlink-target verification (target must be inside sandbox)
    5. Sensitive-path blocklist

    Raises ``HttpError(403)`` for all blocked paths and
    ``HttpError(404)`` when ``must_exist`` is ``True`` and the path is absent.
    """
    if not path:
        return _FILES_ROOT

    # 1. Null-byte injection
    if "\x00" in path:
        raise HttpError(403, "Path blocked: null bytes not allowed")

    # Normalise URL-encoded sequences so traversal tricks like
    # ``%2e%2e%2f`` or ``..%2f`` are caught.
    from urllib.parse import unquote

    decoded = unquote(path)
    if "\x00" in decoded:
        raise HttpError(403, "Path blocked: null bytes not allowed")

    cleaned = FilePath(decoded)

    # 2. Reject traversal components (covers ``..``, ``....//``, etc.)
    if ".." in cleaned.parts or any(".." in part for part in cleaned.parts):
        raise HttpError(403, "Path blocked: directory traversal not allowed")

    # Build candidate (do NOT resolve yet — we check the raw join first)
    candidate = _FILES_ROOT / cleaned

    # 3. Resolve and verify the path stays inside the sandbox root
    resolved_root = _FILES_ROOT.resolve()
    resolved_candidate = candidate.resolve()
    root_prefix = str(resolved_root)
    if not root_prefix.endswith(os.sep):
        root_prefix += os.sep
    if not (resolved_candidate == resolved_root or str(resolved_candidate).startswith(root_prefix)):
        raise HttpError(403, "Path blocked: outside sandbox root")

    # 4. Symlink escape: if any component is a symlink, ensure its target
    #    also resolves inside the sandbox root.
    if candidate.is_symlink():
        link_target = candidate.resolve(strict=False)
        if not str(link_target).startswith(root_prefix):
            raise HttpError(403, "Path blocked: symlink points outside sandbox")

    # 5. Sensitive-path blocklist
    abs_str = str(resolved_candidate)
    for prefix in _SENSITIVE_PREFIXES:
        if abs_str == prefix or abs_str.startswith(prefix + "/"):
            raise HttpError(403, "Path blocked: access to sensitive path denied")
    if resolved_candidate.name in _SENSITIVE_NAMES:
        raise HttpError(403, "Path blocked: access to sensitive path denied")

    # Existence check (opt-out for write/create operations)
    if must_exist and not resolved_candidate.exists():
        raise HttpError(404, f"Path not found: {path}")

    return resolved_candidate


_FILES_TREE_MAX_DEPTH = 10
_FILES_TREE_MAX_ENTRIES = 5000


def _build_tree(
    root: FilePath, base: FilePath, *, _depth: int = 0, _count: list[int] | None = None
) -> list[dict[str, Any]]:
    """Return a lightweight directory tree rooted at *root*.

    Enforces *_FILES_TREE_MAX_DEPTH* and *_FILES_TREE_MAX_ENTRIES* to avoid
    hanging on large or deeply-nested workspace roots.
    """
    if _count is None:
        _count = [0]
    entries: list[dict[str, Any]] = []
    if _depth >= _FILES_TREE_MAX_DEPTH:
        return entries
    try:
        items = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return entries
    for item in items:
        if _count[0] >= _FILES_TREE_MAX_ENTRIES:
            break
        if item.name.startswith(".git"):
            continue
        _count[0] += 1
        rel = str(item.relative_to(base))
        if item.is_dir():
            entries.append(
                {
                    "name": item.name,
                    "path": rel,
                    "type": "directory",
                    "children": _build_tree(item, base, _depth=_depth + 1, _count=_count),
                }
            )
        else:
            try:
                size = item.stat().st_size
            except OSError:
                size = 0
            entries.append({"name": item.name, "path": rel, "type": "file", "size": size})
    return entries


class _FileWriteBody(Schema):
    path: str
    content: str


class _FileCreateBody(Schema):
    path: str
    type: str = "file"  # "file" or "directory"
    content: str = ""


@files_router.get("/files/tree")
@require_scope(["stream:read", "files:rw"])
async def files_tree(request, path: str = "") -> dict[str, Any]:
    """Return a recursive directory tree from the sandbox root (or sub-path)."""
    target = _resolve_sandbox_path(path)
    if not target.is_dir():
        raise HttpError(400, f"Path is not a directory: {path}")
    tree = await asyncio.to_thread(_build_tree, target, _FILES_ROOT)
    return {"path": path or ".", "tree": tree}


@files_router.get("/files/read")
@require_scope(["stream:read", "files:rw"])
async def files_read(request, path: str) -> dict[str, Any]:
    """Return the text content of a file."""
    target = _resolve_sandbox_path(path)
    if not target.is_file():
        raise HttpError(400, f"Path is not a file: {path}")

    def _read() -> str:
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HttpError(400, f"Binary file cannot be read as text: {path}")

    content = await asyncio.to_thread(_read)
    stat = target.stat()
    return {
        "path": path,
        "content": content,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
    }


@files_router.put("/files/write")
@require_scope(["files:rw"])
async def files_write(request, body: _FileWriteBody = Body(...)) -> dict[str, Any]:
    """Write (create or overwrite) a file."""
    target = _resolve_sandbox_path(body.path, must_exist=False)

    def _write() -> int:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.content, encoding="utf-8")
        return target.stat().st_size

    size = await asyncio.to_thread(_write)
    return {"path": body.path, "size": size, "status": "written"}


@files_router.post("/files/create")
@require_scope(["files:rw"])
async def files_create(request, body: _FileCreateBody = Body(...)) -> dict[str, Any]:
    """Create a new file or directory."""
    target = _resolve_sandbox_path(body.path, must_exist=False)
    if target.exists():
        raise HttpError(409, f"Path already exists: {body.path}")

    def _create() -> None:
        if body.type == "directory":
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body.content, encoding="utf-8")

    await asyncio.to_thread(_create)
    return {"path": body.path, "type": body.type, "status": "created"}


@files_router.delete("/files/delete")
@require_scope(["files:rw"])
async def files_delete(request, path: str) -> dict[str, Any]:
    """Delete a file or directory."""
    target = _resolve_sandbox_path(path)
    if not target.exists():
        raise HttpError(404, f"Path not found: {path}")

    import shutil as _shutil

    def _delete() -> str:
        if target.is_dir():
            _shutil.rmtree(target)
            return "directory"
        else:
            target.unlink()
            return "file"

    kind = await asyncio.to_thread(_delete)
    return {"path": path, "type": kind, "status": "deleted"}


@files_router.get("/files/watch")
@require_scope(["stream:read", "files:rw"])
async def files_watch(request, path: str = "") -> StreamingHttpResponse:
    """SSE stream of filesystem change events (polling-based).

    Emits ``file_created``, ``file_modified``, ``file_deleted`` events.
    Send a client ``close`` or disconnect to stop.
    """
    target = _resolve_sandbox_path(path)
    if not target.exists() or not target.is_dir():
        raise HttpError(400, "Watch path must be an existing directory")

    async def _event_stream() -> AsyncIterator[str]:
        # Build initial snapshot: {relative_path: mtime}
        def _snapshot() -> dict[str, float]:
            snap: dict[str, float] = {}
            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if not d.startswith(".git")]
                root_p = FilePath(root)
                for f in files:
                    fp = root_p / f
                    try:
                        rel = str(fp.relative_to(_FILES_ROOT))
                        snap[rel] = fp.stat().st_mtime
                    except OSError:
                        pass
            return snap

        prev = await asyncio.to_thread(_snapshot)
        # Send initial connected event
        yield f"event: connected\ndata: {json.dumps({'watching': path or '.'})}\n\n"

        while True:
            await asyncio.sleep(2)  # poll interval
            try:
                curr = await asyncio.to_thread(_snapshot)
            except Exception:
                continue

            # Detect changes
            for p, mtime in curr.items():
                if p not in prev:
                    yield f"event: file_created\ndata: {json.dumps({'path': p})}\n\n"
                elif mtime != prev[p]:
                    yield f"event: file_modified\ndata: {json.dumps({'path': p})}\n\n"
            for p in prev:
                if p not in curr:
                    yield f"event: file_deleted\ndata: {json.dumps({'path': p})}\n\n"

            prev = curr

    response = StreamingHttpResponse(_event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    return response


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 11 — CONVERSATION & HEALTH ENDPOINTS                             ║
# ║                                                                            ║
# ║  GET /conversations → List conversations grouped by conversation_id        ║
# ║  GET /health        → Liveness check with active run count                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SKILLS API                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


@skills_router.get("/skills")
async def list_loaded_skills(request) -> list[dict[str, str]]:
    """List all skills currently loaded in the skill registry."""
    return [
        {"name": s.name, "description": s.description, "type": s.skill_type}
        for s in skill_registry.skills.values()
        if s.active
    ]


@health_router.get("/conversations", auth=None)
async def list_conversations(request) -> list[dict[str, Any]]:
    """List conversations grouped by conversation_id, sorted by most recent.

    Uses Django ORM aggregation to group runs by conversation_id and compute
    last_active, first_task, and run_count per conversation.
    """
    from django.db.models import Count, Max, Min

    qs = (
        SandboxRun.objects.filter(conversation_id__isnull=False)
        .values("conversation_id")
        .annotate(
            last_active=Max("updated_at"),
            first_task=Min("task"),
            run_count=Count("id"),
        )
        .order_by("-last_active")
    )
    rows = await sync_to_async(list)(qs)
    return [
        {
            "conversation_id": r["conversation_id"],
            "last_active": r["last_active"].isoformat(),
            "first_task": r["first_task"],
            "run_count": r["run_count"],
        }
        for r in rows
    ]


@health_router.get("/health", auth=None)
async def health(request) -> dict[str, Any]:
    """Liveness check.

    Verifies DB connectivity by running a trivial query, and reports
    the number of currently active agent runs.
    """

    def _check_db():
        from django.db import connection

        connection.ensure_connection()

    await sync_to_async(_check_db)()
    return {"status": "ok", "active_runs": len(_run_tasks)}


@health_router.post("/expose-port", auth=None)
async def expose_port(request) -> dict[str, Any]:
    """Expose a sandbox port and extend the idle-pause timer by 30 minutes.

    Called by the ``expose_port`` tool when the agent starts a service that
    the user should be able to view in their browser.
    """
    import json as _json
    from datetime import timedelta

    body: dict[str, Any] = {}
    if request.body:
        try:
            body = _json.loads(request.body)
        except Exception:
            pass

    port: int = body.get("port", 0)
    label: str = body.get("label", "")

    if not SUKUNA_SANDBOX_ID:
        # Local mode — return localhost URL instead of E2B URL.
        return {
            "status": "ok",
            "message": f"Port {port} exposed locally",
            "url": f"http://localhost:{port}" if port else "",
            "port": port,
            "label": label,
        }

    @sync_to_async
    def _expose():
        record = DjangoE2bSandbox.objects.filter(sandbox_id=SUKUNA_SANDBOX_ID).first()
        if record is None:
            return None
        record.delayed_termination_at = timezone.now() + timedelta(minutes=30)
        record.save(update_fields=["delayed_termination_at", "date_updated"])
        return record.sandbox_id

    sandbox_id = await _expose()
    if sandbox_id is None:
        return {"status": "error", "message": "Sandbox record not found"}

    # Construct the public E2B URL for the exposed port.
    public_url = f"https://{sandbox_id}-{port}.e2b.dev" if port else ""
    return {
        "status": "ok",
        "message": f"Port {port} exposed for 30 minutes",
        "url": public_url,
        "port": port,
        "label": label,
    }
