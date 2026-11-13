"""Continuous background Knowledge Manager loop.

The KM needs to run in parallel with the planner / executor, not just
on discrete triggers.  This module provides a long-lived asyncio task
that ticks the KM on a timer and exits cleanly when the run ends.

Each tick:
1. Reads the freshest trajectory snapshot via the caller-supplied
   ``messages_provider`` closure (which in production resolves to
   ``state.get_messages_snapshot``).
2. Fires a **single** ``run_km`` call with ``trigger="periodic"`` and
   ``scope="overall"`` — the continuous loop is the safety-net
   background process that complements the event-driven triggers
   (post_executor / pre_compression / content_burst / prefetch).

The run is gated by the same ``should_run_km`` / ``is_trivial_window``
/ ``km_run_rate_limited`` checks used by the event-driven triggers —
the loop is not a bypass, just another trigger source.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from agent_server.engine.context import ContextEngineConfig

from .runner import run_km

log = logging.getLogger("knowledge_manager.loop")


def _default_loop_interval() -> float:
    """Resolve the default KM loop tick interval.

    Precedence:
    1. ``KM_LOOP_INTERVAL_SEC`` env var — explicit override, always
       wins. Floats accepted.
    2. ``LOCAL_MODE=1`` → 60s. Local models (e.g. Ollama gemma) can
       take tens of seconds to hundreds of seconds per KM run; ticking
       every 15s just means every tick after the first is skipped by
       the in-flight lock anyway, so we relax the cadence.
    3. Default (hosted provider) → 15s.
    """
    override = os.environ.get("KM_LOOP_INTERVAL_SEC")
    if override:
        try:
            return float(override)
        except ValueError:
            log.warning(
                "KM_LOOP_INTERVAL_SEC=%r is not a float; using default",
                override,
            )
    if os.environ.get("LOCAL_MODE") in ("1", "true", "True", "yes"):
        return 60.0
    return 15.0


# Resolved once at import time; callers can still pass their own value
# per ``KMContinuousLoop`` instance.  The env var is the usual knob.
KM_LOOP_INTERVAL_SEC: float = _default_loop_interval()


class KMContinuousLoop:
    """Lifecycle wrapper around the background KM ticker task.

    Typical usage inside the runner:

        loop = KMContinuousLoop(
            conversation_id=..., run_id=..., provider=..., model=...,
            ctx_engine_config=...,
            messages_provider=lambda: get_messages_snapshot(conv_id),
        )
        loop.start()
        try:
            ...  # planner / executor loop
        finally:
            await loop.stop()
    """

    def __init__(
        self,
        *,
        conversation_id: str,
        run_id: str,
        provider: Any,
        model: str,
        messages_provider,
        ctx_engine_config: ContextEngineConfig | None = None,
        interval_sec: float = KM_LOOP_INTERVAL_SEC,
    ) -> None:
        self._conversation_id = conversation_id
        self._run_id = run_id
        self._provider = provider
        self._model = model
        self._messages_provider = messages_provider
        self._ctx_engine_config = ctx_engine_config
        self._interval_sec = interval_sec
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        """Start the background ticker task.  No-op if already running."""
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(
            self._run(),
            name=f"km-loop-{self._conversation_id[:8]}",
        )

    async def stop(self) -> None:
        """Signal the ticker to exit and wait for the task to finish."""
        self._stopped.set()
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    async def _run(self) -> None:
        log.info(
            "km_loop: started conv=%s interval=%.1fs",
            self._conversation_id[:8],
            self._interval_sec,
        )
        try:
            while not self._stopped.is_set():
                # Use wait_for so we exit promptly when ``stop`` is called.
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=self._interval_sec)
                    break  # Stop was signalled while we were waiting.
                except asyncio.TimeoutError:
                    pass  # Regular tick.

                await self._tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "km_loop: unexpected failure (conv=%s) — loop exiting",
                self._conversation_id[:8],
            )
        finally:
            log.info("km_loop: stopped conv=%s", self._conversation_id[:8])

    async def _tick(self) -> None:
        """One tick of the loop: a single unified KM run.

        The call is gated internally by ``run_km`` (in-flight lock,
        threshold, trivial window, rate limit) and returns fast no-ops
        when the conversation has nothing new to do.  We do not pass
        ``force`` — the loop never bypasses the gates.
        """
        messages = self._safe_messages()
        log.info(
            "km_loop: tick conv=%s n_messages=%d",
            self._conversation_id[:8],
            len(messages),
        )
        if not messages:
            return

        try:
            await run_km(
                conversation_id=self._conversation_id,
                run_id=self._run_id,
                messages=messages,
                provider=self._provider,
                model=self._model,
                trigger="periodic",
                scope="overall",
                ctx_engine_config=self._ctx_engine_config,
            )
        except Exception:
            log.warning(
                "km_loop: tick failed (conv=%s)",
                self._conversation_id[:8],
                exc_info=True,
            )

    def _safe_messages(self) -> list:
        """Pull a message snapshot through the caller-provided callable.

        In production the closure resolves to ``state.get_messages_snapshot``,
        which returns the freshest trajectory captured by ``vital_info_hook``
        on the most recent PRE_LLM_CALL.  Swallows errors so a bad
        ``messages_provider`` does not kill the loop.
        """
        try:
            messages = self._messages_provider()
            return list(messages) if messages is not None else []
        except Exception:
            log.debug(
                "km_loop: messages_provider raised (conv=%s)",
                self._conversation_id[:8],
                exc_info=True,
            )
            return []


def start_km_loop(
    *,
    conversation_id: str,
    run_id: str,
    provider: Any,
    model: str,
    messages_provider,
    ctx_engine_config: ContextEngineConfig | None = None,
) -> KMContinuousLoop:
    """Construct and start a ``KMContinuousLoop``.  Convenience wrapper."""
    loop = KMContinuousLoop(
        conversation_id=conversation_id,
        run_id=run_id,
        provider=provider,
        model=model,
        messages_provider=messages_provider,
        ctx_engine_config=ctx_engine_config,
    )
    loop.start()
    return loop


async def stop_km_loop(loop: KMContinuousLoop | None) -> None:
    """Stop a running loop.  Safe to call with ``None`` or a finished loop."""
    if loop is None:
        return
    await loop.stop()
