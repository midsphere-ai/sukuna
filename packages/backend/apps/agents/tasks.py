"""
Celery Tasks — Sandbox Lifecycle Management

Post-purge: these tasks care about sandbox infrastructure only. Run-side reaping
and billing reconciliation live inside the sandbox agent server.

Tasks:
- terminate_delayed_sandboxes: pause sandboxes past their idle timeout
- replenish_sandbox_pool: pre-warm pool to target size
- expire_stale_pool_sandboxes: rotate pool sandboxes before E2B hard timeout
- kill_orphaned_sandboxes: clean up leaked/orphaned sandboxes
- monitor_assigned_sandboxes: health-check assigned sandboxes
"""

import logging
import os

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

AGENT_SERVER_PORT = getattr(settings, "SANDBOX_AGENT_SERVER_PORT", 8000)


def _get_agent_server_api_key() -> str:
    """Resolve the agent server API key from settings or environment variables."""
    key = getattr(settings, "AGENT_SERVER_API_KEY", "")
    if key:
        return key
    for env_key in ("SUKUNA_AGENT_SERVER_API_KEY", "API_KEY"):
        value = os.getenv(env_key)
        if value:
            return value
    return ""


def _dispatch_pool_replenish() -> None:
    """Best-effort async pool replenish trigger after a warm sandbox is claimed."""
    if getattr(settings, "SANDBOX_POOL_SIZE", 0) <= 0:
        return
    try:
        replenish_sandbox_pool.delay()
    except Exception as exc:
        logger.warning(f"[POOL] Could not dispatch replenish: {exc}")


def _mark_sandbox_unhealthy(record, reason: str, terminate: bool = False) -> None:
    """Mark a sandbox record unusable so future routing won't pick it again."""
    if record is None:
        return

    from apps.agents.models import E2bSandbox

    logger.warning(
        "[SANDBOX] Marking sandbox %s unhealthy (%s): %s",
        record.sandbox_id or record.pk,
        reason,
        record.sandbox_state,
    )

    if terminate and record.sandbox_id:
        try:
            record.pause_sandbox()
            return
        except Exception as exc:
            logger.warning(
                "[SANDBOX] pause_sandbox failed for %s: %s",
                record.sandbox_id,
                exc,
            )

    update_fields = []
    if record.sandbox_state != E2bSandbox.SandboxState.ERROR:
        record.sandbox_state = E2bSandbox.SandboxState.ERROR
        update_fields.append("sandbox_state")
    if record.delayed_termination_at is not None:
        record.delayed_termination_at = None
        update_fields.append("delayed_termination_at")
    if update_fields:
        record.save(update_fields=[*update_fields, "date_updated"])


def _sweep_stale_pool_creating_records(max_age_minutes: int = 10) -> int:
    """Expire pool records stuck in CREATING long enough to be considered dead."""
    from apps.agents.models import E2bSandbox

    stale = list(
        E2bSandbox.objects.pool_stale_creating(max_age_minutes=max_age_minutes)
    )
    for record in stale:
        _mark_sandbox_unhealthy(record, "stale_pool_creating_record", terminate=True)
    return len(stale)


# =============================================================================
# SANDBOX MAINTENANCE
# =============================================================================


@shared_task
def terminate_delayed_sandboxes():
    """Pause sandboxes that have passed their delayed_termination_at time.

    Instead of killing, this pauses so they can be quickly resumed when the user
    returns — the agent_server process survives pause/resume. The sandbox itself
    writes ``delayed_termination_at`` each time it processes an event (idle
    timer); this task enforces what the sandbox wrote.
    """
    from apps.agents.models import E2bSandbox
    from apps.storage.models import AgentRun

    sandboxes_list = list(E2bSandbox.objects.idle_past_deadline())

    count = len(sandboxes_list)
    if count > 0:
        logger.info(f"[SANDBOX] Found {count} sandboxes to pause")

    for sandbox in sandboxes_list:
        try:
            if sandbox.conversation_id:
                run = sandbox.conversation.current_task
                if run and run.status in (
                    AgentRun.Status.QUEUED,
                    AgentRun.Status.PROVISIONING,
                    AgentRun.Status.RUNNING,
                ):
                    logger.info(
                        "[SANDBOX] Skipping idle pause for %s; run %s is active (%s)",
                        sandbox.sandbox_id,
                        run.id,
                        run.status,
                    )
                    sandbox.schedule_idle_pause()
                    continue

            try:
                project = sandbox.project
            except Exception:
                project = None
            if project is not None:
                from apps.agents.sandbox import has_active_project_runs

                if has_active_project_runs(project):
                    logger.info(
                        "[SANDBOX] Skipping idle pause for %s; project %s has active runs",
                        sandbox.sandbox_id,
                        project.id,
                    )
                    sandbox.schedule_idle_pause()
                    continue

            logger.info(f"[SANDBOX] Pausing idle sandbox {sandbox.sandbox_id}")
            sandbox.pause_sandbox()
        except Exception as e:
            logger.error(f"[SANDBOX] Error pausing sandbox {sandbox.sandbox_id}: {e}")

    if count > 0:
        logger.info(f"[SANDBOX] Finished pausing {count} idle sandboxes")

    return count


# =============================================================================
# PREWARMED SANDBOX POOL
# =============================================================================


@shared_task
def replenish_sandbox_pool():
    """Check pool deficit and dispatch ``_create_pool_sandbox`` tasks in parallel."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.agents.models import E2bSandbox

    lock_key = "agents:pool:replenish_lock"
    if not cache.add(lock_key, "1", timeout=55):
        logger.info("[POOL] Replenish already in progress, skipping")
        return 0

    pool_size = getattr(settings, "SANDBOX_POOL_SIZE", 2)
    try:
        if pool_size <= 0:
            return 0

        stale_creating = _sweep_stale_pool_creating_records(max_age_minutes=10)
        if stale_creating:
            logger.warning(
                "[POOL] Expired %s stale CREATING sandbox record(s)",
                stale_creating,
            )

        creating_fresh_cutoff = timezone.now() - timedelta(minutes=10)
        pool_ready = E2bSandbox.objects.pool_ready().count()
        pool_creating = (
            E2bSandbox.objects.get_queryset()
            .pool()
            .by_state(E2bSandbox.SandboxState.CREATING)
            .filter(start_time__gt=creating_fresh_cutoff)
            .count()
        )
        current = pool_ready + pool_creating

        deficit = pool_size - current
        if deficit <= 0:
            logger.info(f"[POOL] Pool full ({current}/{pool_size}), nothing to do")
            return 0

        logger.info(
            f"[POOL] Dispatching {deficit} sandbox creation(s) (current={current}, target={pool_size})"
        )
        for _ in range(deficit):
            _create_pool_sandbox.delay()

        return deficit
    finally:
        cache.delete(lock_key)


@shared_task(soft_time_limit=120, time_limit=150)
def _create_pool_sandbox():
    """Create a single prewarmed pool sandbox. Dispatched by ``replenish_sandbox_pool``."""
    from apps.agents.models import E2bSandbox

    record = E2bSandbox.objects.create(
        sandbox_state=E2bSandbox.SandboxState.CREATING,
        conversation=None,
    )
    sandbox = record.create_sandbox()
    if sandbox is not None:
        logger.info(f"[POOL] Created pool sandbox {record.sandbox_id}")
    else:
        _mark_sandbox_unhealthy(record, "pool_sandbox_create_failed")
        logger.warning(f"[POOL] Failed to create pool sandbox (record id={record.pk})")


@shared_task
def expire_stale_pool_sandboxes():
    """Terminate pool sandboxes older than 50 min — 10 min before E2B's hard timeout."""
    from apps.agents.models import E2bSandbox

    stale = list(E2bSandbox.objects.pool_stale(max_age_minutes=50))

    if stale:
        logger.info(f"[POOL] Expiring {len(stale)} stale pool sandbox(es)")
        for record in stale:
            try:
                record.pause_sandbox()
                logger.info(f"[POOL] Paused stale pool sandbox {record.sandbox_id}")
            except Exception as e:
                logger.error(
                    f"[POOL] Error pausing stale sandbox {record.sandbox_id}: {e}"
                )

    stale_creating = _sweep_stale_pool_creating_records(max_age_minutes=10)
    if stale_creating:
        logger.info(
            f"[POOL] Marked {stale_creating} stale CREATING pool sandbox record(s) as unhealthy"
        )

    return len(stale) + stale_creating


@shared_task
def kill_orphaned_sandboxes():
    """Pause sandboxes stuck in ERROR/CREATING state, plus leaked READY sandboxes."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.agents.models import E2bSandbox
    from apps.storage.models import AgentRun

    paused = 0
    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=5)
    # Pool rotation is owned by ``expire_stale_pool_sandboxes`` (50 min). Use a
    # longer cutoff here so this task only catches truly leaked READY records
    # that the pool rotator missed — without thrashing the pool on every tick.
    pool_leak_cutoff = now - timedelta(minutes=55)

    error_sandboxes = list(
        E2bSandbox.objects.get_queryset()
        .by_state(E2bSandbox.SandboxState.ERROR)
        .filter(sandbox_id__gt="", date_updated__lte=stale_cutoff)
    )
    for record in error_sandboxes:
        try:
            record.pause_sandbox()
            paused += 1
            logger.info("[ORPHAN] Paused ERROR-state sandbox %s", record.sandbox_id)
        except Exception as e:
            logger.debug(
                "[ORPHAN] Could not pause ERROR sandbox %s: %s",
                record.sandbox_id,
                e,
            )

    leaked_ready = list(
        E2bSandbox.objects.get_queryset()
        .by_state(E2bSandbox.SandboxState.READY)
        .filter(
            delayed_termination_at__isnull=True,
            conversation__isnull=True,
            start_time__lte=pool_leak_cutoff,
        )
    )
    for record in leaked_ready:
        try:
            record.pause_sandbox()
            paused += 1
            logger.info(
                "[ORPHAN] Paused leaked READY sandbox %s (no conversation, no idle timer)",
                record.sandbox_id,
            )
        except Exception as e:
            logger.warning(
                "[ORPHAN] Could not pause leaked sandbox %s: %s",
                record.sandbox_id,
                e,
            )

    orphaned_assigned = list(
        E2bSandbox.objects.get_queryset()
        .by_state(E2bSandbox.SandboxState.READY)
        .filter(
            delayed_termination_at__isnull=True,
            conversation__isnull=False,
            start_time__lte=stale_cutoff,
        )
        .select_related("conversation", "conversation__current_task")
    )
    for record in orphaned_assigned:
        run = record.conversation.current_task if record.conversation_id else None
        if run and run.status in (
            AgentRun.Status.QUEUED,
            AgentRun.Status.PROVISIONING,
            AgentRun.Status.RUNNING,
        ):
            continue
        try:
            record.schedule_idle_pause(minutes=1)
            logger.info(
                "[ORPHAN] Scheduled idle pause for orphaned sandbox %s",
                record.sandbox_id,
            )
        except Exception as e:
            logger.warning(
                "[ORPHAN] Could not schedule pause for sandbox %s: %s",
                record.sandbox_id,
                e,
            )

    if paused:
        logger.info("[ORPHAN] Paused %d orphaned sandboxes", paused)
    return paused


@shared_task
def monitor_assigned_sandboxes():
    """Periodic health check for assigned sandboxes.

    If a sandbox becomes unreachable, mark it unhealthy and trigger pool
    replenish so capacity recovers quickly. The sandbox itself owns run-status
    reconciliation — a stuck RUNNING row will be failed by the sandbox's own
    reaper next time it reports, or by the terminal-event writer.
    """
    import httpx

    from apps.agents.models import E2bSandbox

    checked = 0
    healthy = 0
    unhealthy = 0
    api_key = _get_agent_server_api_key()

    records = list(
        E2bSandbox.objects.get_queryset()
        .by_state(E2bSandbox.SandboxState.READY)
        .filter(conversation__isnull=False)
        .select_related("conversation", "conversation__current_task")
    )

    for record in records:
        checked += 1
        try:
            sandbox = record.get_sandbox()
            if sandbox is None:
                raise RuntimeError("sandbox_connect_failed")
            host = sandbox.get_host(AGENT_SERVER_PORT)
            resp = httpx.get(
                f"https://{host}/health",
                headers={"X-API-Key": api_key} if api_key else {},
                timeout=5,
            )
            if resp.status_code < 400:
                healthy += 1
                continue
            raise RuntimeError(f"health_status_{resp.status_code}")
        except Exception as exc:
            unhealthy += 1
            logger.warning(
                "[SANDBOX] Assigned sandbox %s failed health check: %s",
                record.sandbox_id,
                exc,
            )
            _mark_sandbox_unhealthy(record, "assigned_sandbox_healthcheck_failed", True)

    if unhealthy:
        _dispatch_pool_replenish()

    return {"checked": checked, "healthy": healthy, "unhealthy": unhealthy}
