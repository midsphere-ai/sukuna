"""Idle-pause timer maintenance — throttled writes to DjangoE2bSandbox.

Called from the event emit path on activity events (tool calls, steps, progress).
Throttled so the hot path stays cheap; the exact delay doesn't matter — the
terminate_delayed_sandboxes Celery task reads the timestamp every ~60s anyway.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.utils import timezone

from agent_server.config import SUKUNA_SANDBOX_ID
from agent_server.models import DjangoE2bSandbox

log = logging.getLogger("agent_server")


# Minimum seconds between successive DjangoE2bSandbox writes per sandbox.
_THROTTLE_SECONDS = 30.0

# Fresh idle window granted on each bump. Matches the backend's default
# (~1 min) with a small safety margin so terminate_delayed_sandboxes doesn't
# race a bump that's about to happen.
_IDLE_WINDOW_MINUTES = 2

_last_bump_at: float = 0.0
_bump_lock = asyncio.Lock()


async def bump_idle_timer() -> None:
    """Extend ``DjangoE2bSandbox.delayed_termination_at`` by the idle window.

    No-op when SUKUNA_SANDBOX_ID is unset (local-mode dev, integration tests).
    Fire-and-forget: failures are logged at debug level and swallowed so the
    agent event emit path cannot be stalled by DB hiccups.
    """
    global _last_bump_at

    if not SUKUNA_SANDBOX_ID:
        return

    now = time.monotonic()
    if now - _last_bump_at < _THROTTLE_SECONDS:
        return

    async with _bump_lock:
        # Re-check inside the lock — another coroutine may have bumped.
        if time.monotonic() - _last_bump_at < _THROTTLE_SECONDS:
            return
        _last_bump_at = time.monotonic()

    try:
        await sync_to_async(_write_bump)()
    except Exception:
        log.debug("Idle bump failed for sandbox %s", SUKUNA_SANDBOX_ID, exc_info=True)


def _write_bump() -> None:
    record = DjangoE2bSandbox.objects.filter(sandbox_id=SUKUNA_SANDBOX_ID).first()
    if record is None:
        return
    record.delayed_termination_at = timezone.now() + timedelta(minutes=_IDLE_WINDOW_MINUTES)
    record.save(update_fields=["delayed_termination_at", "date_updated"])
