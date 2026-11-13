"""Unit tests for the sandbox agent server (Django edition).

Covers:
- RunNotifyChannel — lightweight per-run wake signal for SSE streaming
- LeaseEnforcer / UsageTotals / LeaseLimits — pure-Python lease logic
- parse_lease_limits / _parse_positive_float / _parse_positive_int — helpers
- backend_sync service — Django ORM writes to storage_agentrun
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from agent_server.models import DjangoAgentRun, DjangoConversation
from agent_server.server import (
    _TERMINAL_STATUSES,
    LeaseEnforcer,
    LeaseLimits,
    LeaseViolation,
    RunNotifyChannel,
    UsageTotals,
    _apply_usage,
    _get_run,
    _parse_positive_float,
    _parse_positive_int,
    parse_lease_limits,
    sync_run_cancelled,
    sync_run_completed,
    sync_run_failed,
    sync_run_started,
    sync_run_usage,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _create_django_agent_run(
    *,
    run_id: str,
    status: str = "provisioning",
    error: str = "",
    sandbox_id: str = "",
    metadata: dict | None = None,
    conversation_id: str | None = None,
    started_at=None,
    finished_at=None,
) -> DjangoAgentRun:
    """Insert a DjangoAgentRun row for testing.

    Since Step 1b of the backend-purge made ``storage_agentrun.conversation_id``
    NOT NULL, we auto-create a DjangoConversation when the caller doesn't supply
    one. This keeps individual tests concise without each having to mint a
    conversation first.
    """
    now = timezone.now()
    if conversation_id is None:
        conv = DjangoConversation.objects.create(
            id=str(uuid.uuid4()),
            user_id=1,
            date_created=now,
            date_updated=now,
        )
        conv_uuid = uuid.UUID(conv.id)
    else:
        conv_uuid = uuid.UUID(conversation_id)
    return DjangoAgentRun.objects.create(
        id=uuid.uuid4(),
        run_id=run_id,
        conversation_id=conv_uuid,
        status=status,
        error=error,
        sandbox_id=sandbox_id,
        metadata=metadata or {},
        created_at=now,
        started_at=started_at,
        finished_at=finished_at,
        updated_at=now,
    )


@dataclass
class _FakeUsage:
    """Duck-typed usage object matching what backend_sync._apply_usage expects."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# RunNotifyChannel Tests — pure asyncio, no DB
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunNotifyChannel(TestCase):
    """RunNotifyChannel is a lightweight per-run wake signal for SSE streaming."""

    def test_notify_wakes_waiter(self):
        async def _run():
            ch = RunNotifyChannel()
            waiter = ch.create_waiter()
            ch.notify(0)
            assert waiter.is_set()

        asyncio.get_event_loop().run_until_complete(_run())

    def test_multiple_waiters(self):
        async def _run():
            ch = RunNotifyChannel()
            w1 = ch.create_waiter()
            w2 = ch.create_waiter()
            ch.notify(0)
            assert w1.is_set()
            assert w2.is_set()

        asyncio.get_event_loop().run_until_complete(_run())

    def test_remove_waiter(self):
        async def _run():
            ch = RunNotifyChannel()
            w = ch.create_waiter()
            ch.remove_waiter(w)
            ch.notify(0)
            assert not w.is_set()

        asyncio.get_event_loop().run_until_complete(_run())

    def test_close_wakes_all(self):
        async def _run():
            ch = RunNotifyChannel()
            w1 = ch.create_waiter()
            w2 = ch.create_waiter()
            ch.close()
            assert w1.is_set()
            assert w2.is_set()
            assert ch.is_closed

        asyncio.get_event_loop().run_until_complete(_run())

    def test_latest_seq_tracked(self):
        async def _run():
            ch = RunNotifyChannel()
            assert ch.latest_seq == -1
            ch.notify(5)
            assert ch.latest_seq == 5
            ch.notify(10)
            assert ch.latest_seq == 10

        asyncio.get_event_loop().run_until_complete(_run())

    def test_remove_nonexistent_waiter_is_safe(self):
        async def _run():
            ch = RunNotifyChannel()
            fake = asyncio.Event()
            ch.remove_waiter(fake)  # should not raise

        asyncio.get_event_loop().run_until_complete(_run())


# ═══════════════════════════════════════════════════════════════════════════════
# Lease Enforcement Tests — pure Python, no DB
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseLeaseLimits(TestCase):
    def test_none_metadata(self):
        limits = parse_lease_limits(None)
        assert limits.max_runtime_seconds is None

    def test_flat_metadata(self):
        limits = parse_lease_limits({"max_runtime_seconds": 60, "max_total_tokens": 1000})
        assert limits.max_runtime_seconds == 60.0
        assert limits.max_total_tokens == 1000

    def test_nested_lease(self):
        limits = parse_lease_limits({"lease": {"max_runtime_seconds": 120, "max_cost_usd": 5.0}})
        assert limits.max_runtime_seconds == 120.0
        assert limits.max_cost_usd == 5.0

    def test_non_dict(self):
        limits = parse_lease_limits("not-a-dict")
        assert limits == LeaseLimits()


class TestLeaseEnforcer(TestCase):
    def test_no_limits(self):
        enforcer = LeaseEnforcer(LeaseLimits())
        enforcer.check_runtime()
        enforcer.check_usage(UsageTotals(total_tokens=9999))

    def test_runtime_exceeded(self):
        enforcer = LeaseEnforcer(LeaseLimits(max_runtime_seconds=1.0), started_monotonic=0.0)
        with self.assertRaises(LeaseViolation) as ctx:
            enforcer.check_runtime(now_monotonic=2.0)
        assert ctx.exception.code == "lease_runtime_exceeded"

    def test_runtime_within_limit(self):
        enforcer = LeaseEnforcer(LeaseLimits(max_runtime_seconds=10.0), started_monotonic=0.0)
        enforcer.check_runtime(now_monotonic=5.0)

    def test_tokens_exceeded(self):
        enforcer = LeaseEnforcer(LeaseLimits(max_total_tokens=100))
        with self.assertRaises(LeaseViolation) as ctx:
            enforcer.check_usage(UsageTotals(total_tokens=101))
        assert ctx.exception.code == "lease_tokens_exceeded"

    def test_cost_exceeded(self):
        enforcer = LeaseEnforcer(LeaseLimits(max_cost_usd=1.0))
        with self.assertRaises(LeaseViolation) as ctx:
            enforcer.check_usage(UsageTotals(cost_usd=1.01))
        assert ctx.exception.code == "lease_cost_exceeded"


class TestParseHelpers(TestCase):
    def test_parse_positive_float(self):
        assert _parse_positive_float(1.5) == 1.5
        assert _parse_positive_float("3.14") == pytest.approx(3.14)
        assert _parse_positive_float(-1) is None
        assert _parse_positive_float(None) is None
        assert _parse_positive_float(True) is None
        assert _parse_positive_float("") is None

    def test_parse_positive_int(self):
        assert _parse_positive_int(42) == 42
        assert _parse_positive_int("100") == 100
        assert _parse_positive_int(-5) is None
        assert _parse_positive_int(None) is None


class TestUsageTotals(TestCase):
    def test_default_values(self):
        usage = UsageTotals()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0
        assert usage.cost_usd == 0.0

    def test_custom_values(self):
        usage = UsageTotals(input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=0.05)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.total_tokens == 150
        assert usage.cost_usd == 0.05


# ═══════════════════════════════════════════════════════════════════════════════
# backend_sync._apply_usage Tests — unit-level, needs a model instance
# ═══════════════════════════════════════════════════════════════════════════════


class TestApplyUsage(TransactionTestCase):
    """Tests for the _apply_usage helper that merges usage into run metadata."""

    def test_apply_usage_populates_sandbox_usage(self):
        run = _create_django_agent_run(run_id="apply-usage-1")
        usage = _FakeUsage(input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=0.01)
        changed = _apply_usage(run, usage)
        assert changed is True
        assert run.metadata["sandbox_usage"]["input_tokens"] == 100
        assert run.metadata["sandbox_usage"]["output_tokens"] == 50
        assert run.metadata["sandbox_usage"]["total_tokens"] == 150
        assert run.metadata["sandbox_usage"]["cost_usd"] == 0.01
        assert "updated_at" in run.metadata["sandbox_usage"]

    def test_apply_usage_none_returns_false(self):
        run = _create_django_agent_run(run_id="apply-usage-2")
        changed = _apply_usage(run, None)
        assert changed is False

    def test_apply_usage_merges_over_existing(self):
        run = _create_django_agent_run(
            run_id="apply-usage-3",
            metadata={"sandbox_usage": {"input_tokens": 50, "total_tokens": 50}},
        )
        usage = _FakeUsage(input_tokens=200, total_tokens=300)
        changed = _apply_usage(run, usage)
        assert changed is True
        assert run.metadata["sandbox_usage"]["input_tokens"] == 200
        assert run.metadata["sandbox_usage"]["total_tokens"] == 300

    def test_apply_usage_preserves_existing_metadata(self):
        run = _create_django_agent_run(
            run_id="apply-usage-4",
            metadata={"custom_key": "custom_value"},
        )
        usage = _FakeUsage(input_tokens=10)
        _apply_usage(run, usage)
        assert run.metadata["custom_key"] == "custom_value"
        assert run.metadata["sandbox_usage"]["input_tokens"] == 10


# ═══════════════════════════════════════════════════════════════════════════════
# backend_sync Service Tests — Django ORM
# ═══════════════════════════════════════════════════════════════════════════════


class TestSyncRunStarted(TransactionTestCase):
    """Tests for sync_run_started: sets status=running and started_at."""

    def test_sets_running_and_started_at(self):
        run = _create_django_agent_run(run_id="started-1", status="provisioning")

        async def _do():
            await sync_run_started("started-1")

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.status == "running"
        assert run.started_at is not None

    def test_sets_sandbox_id(self):
        run = _create_django_agent_run(run_id="started-2", status="provisioning")

        async def _do():
            await sync_run_started("started-2", sandbox_id="sb-123")

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.sandbox_id == "sb-123"

    def test_missing_run_id_does_not_raise(self):
        """sync_run_started should silently handle a missing run."""

        async def _do():
            await sync_run_started("nonexistent-run")

        # Should not raise
        asyncio.get_event_loop().run_until_complete(_do())

    def test_terminal_status_not_overwritten(self):
        """If run is already completed, sync_run_started should not change it."""
        run = _create_django_agent_run(run_id="started-3", status="completed")

        async def _do():
            await sync_run_started("started-3")

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.status == "completed"


class TestSyncRunCompleted(TransactionTestCase):
    """Tests for sync_run_completed: sets status=completed, finished_at, and usage."""

    def test_sets_completed_and_finished_at(self):
        run = _create_django_agent_run(run_id="completed-1", status="running")
        usage = _FakeUsage(input_tokens=500, output_tokens=200, total_tokens=700, cost_usd=0.05)

        async def _do():
            await sync_run_completed("completed-1", usage)

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.status == "completed"
        assert run.finished_at is not None
        assert run.metadata["sandbox_usage"]["total_tokens"] == 700

    def test_terminal_status_not_overwritten(self):
        run = _create_django_agent_run(run_id="completed-2", status="failed")

        async def _do():
            await sync_run_completed("completed-2", None)

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.status == "failed"

    def test_missing_run_id_does_not_raise(self):
        async def _do():
            await sync_run_completed("nonexistent-completed", None)

        asyncio.get_event_loop().run_until_complete(_do())


class TestSyncRunFailed(TransactionTestCase):
    """Tests for sync_run_failed: sets status=failed, error, finished_at."""

    def test_sets_failed_and_error(self):
        run = _create_django_agent_run(run_id="failed-1", status="running")
        usage = _FakeUsage(input_tokens=100, total_tokens=100)

        async def _do():
            await sync_run_failed("failed-1", "Out of tokens", usage)

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.error == "Out of tokens"
        assert run.finished_at is not None
        assert run.metadata["sandbox_usage"]["input_tokens"] == 100

    def test_terminal_status_not_overwritten(self):
        run = _create_django_agent_run(run_id="failed-2", status="completed")

        async def _do():
            await sync_run_failed("failed-2", "should not overwrite", None)

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.status == "completed"
        assert run.error == ""  # original empty error

    def test_missing_run_id_does_not_raise(self):
        async def _do():
            await sync_run_failed("nonexistent-failed", "error msg", None)

        asyncio.get_event_loop().run_until_complete(_do())


class TestSyncRunCancelled(TransactionTestCase):
    """Tests for sync_run_cancelled: sets status=cancelled and finished_at."""

    def test_sets_cancelled(self):
        run = _create_django_agent_run(run_id="cancelled-1", status="running")

        async def _do():
            await sync_run_cancelled("cancelled-1", None)

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.status == "cancelled"
        assert run.finished_at is not None

    def test_terminal_status_not_overwritten(self):
        run = _create_django_agent_run(run_id="cancelled-2", status="completed")

        async def _do():
            await sync_run_cancelled("cancelled-2", None)

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.status == "completed"


class TestSyncRunUsage(TransactionTestCase):
    """Tests for sync_run_usage: updates usage metadata (non-terminal)."""

    def test_updates_usage_metadata(self):
        run = _create_django_agent_run(run_id="usage-1", status="running")
        usage = _FakeUsage(input_tokens=200, output_tokens=100, total_tokens=300, cost_usd=0.02)

        async def _do():
            await sync_run_usage("usage-1", usage)

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.metadata["sandbox_usage"]["total_tokens"] == 300

    def test_updates_sandbox_id(self):
        run = _create_django_agent_run(run_id="usage-2", status="running")

        async def _do():
            await sync_run_usage("usage-2", _FakeUsage(total_tokens=10), sandbox_id="sb-new")

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.sandbox_id == "sb-new"

    def test_missing_run_id_does_not_raise(self):
        async def _do():
            await sync_run_usage("nonexistent-usage", _FakeUsage())

        asyncio.get_event_loop().run_until_complete(_do())


# ═══════════════════════════════════════════════════════════════════════════════
# Terminal Status Idempotency
# ═══════════════════════════════════════════════════════════════════════════════


class TestTerminalStatusIdempotency(TransactionTestCase):
    """Verifies that terminal statuses are never overwritten, regardless
    of which sync function is called."""

    def _assert_status_preserved(self, original_status: str, run_id_suffix: str):
        run = _create_django_agent_run(run_id=f"idem-{run_id_suffix}", status=original_status)

        async def _do():
            await sync_run_started(f"idem-{run_id_suffix}")
            await sync_run_completed(f"idem-{run_id_suffix}", None)
            await sync_run_failed(f"idem-{run_id_suffix}", "err", None)
            await sync_run_cancelled(f"idem-{run_id_suffix}", None)

        asyncio.get_event_loop().run_until_complete(_do())

        run.refresh_from_db()
        assert run.status == original_status

    def test_completed_is_preserved(self):
        self._assert_status_preserved("completed", "completed")

    def test_failed_is_preserved(self):
        self._assert_status_preserved("failed", "failed")

    def test_cancelled_is_preserved(self):
        self._assert_status_preserved("cancelled", "cancelled")


class TestTerminalStatusConstants(TestCase):
    """Verify the terminal status set matches expected values."""

    def test_expected_terminal_statuses(self):
        assert "completed" in _TERMINAL_STATUSES
        assert "failed" in _TERMINAL_STATUSES
        assert "cancelled" in _TERMINAL_STATUSES

    def test_running_is_not_terminal(self):
        assert "running" not in _TERMINAL_STATUSES

    def test_provisioning_is_not_terminal(self):
        assert "provisioning" not in _TERMINAL_STATUSES


# ═══════════════════════════════════════════════════════════════════════════════
# _get_run helper
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetRun(TransactionTestCase):
    def test_returns_run_by_run_id(self):
        _create_django_agent_run(run_id="get-run-1", status="running")
        run = _get_run("get-run-1")
        assert run is not None
        assert run.run_id == "get-run-1"

    def test_returns_none_for_missing_run(self):
        run = _get_run("nonexistent")
        assert run is None

    def test_returns_most_recently_updated(self):
        """When multiple rows share a run_id, _get_run returns the most recent."""
        now = timezone.now()
        first = _create_django_agent_run(run_id="dup-run", status="provisioning")
        # Create a second one (simulating retry) with a later updated_at. Reuse
        # the same conversation so we don't need to spin up another.
        DjangoAgentRun.objects.create(
            id=uuid.uuid4(),
            run_id="dup-run",
            conversation_id=first.conversation_id,
            status="running",
            error="",
            sandbox_id="",
            metadata={},
            created_at=now,
            updated_at=now + timedelta(seconds=10),
        )
        run = _get_run("dup-run")
        assert run is not None
        assert run.status == "running"


# ═══════════════════════════════════════════════════════════════════════════════
# Ralph Loop Helpers — pure Python, no DB
# ═══════════════════════════════════════════════════════════════════════════════

from agent_server.server import (  # noqa: E402
    RALPH_WORKER_INSTRUCTIONS,
    _check_prd_completion,
    _merge_prd_passes,
    _read_progress_patterns,
)


class TestCheckPrdCompletion(TestCase):
    """_check_prd_completion reads prd.json and returns (passed, total, score)."""

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_prd(self, data: dict):
        import json
        from pathlib import Path

        Path(self._tmpdir, "prd.json").write_text(json.dumps(data))

    def test_all_stories_incomplete(self):
        self._write_prd(
            {
                "project": "Test",
                "userStories": [
                    {"id": "US-001", "passes": False},
                    {"id": "US-002", "passes": False},
                    {"id": "US-003", "passes": False},
                ],
            }
        )
        passed, total, score = _check_prd_completion(self._tmpdir)
        assert passed == 0
        assert total == 3
        assert score == 0.0

    def test_some_stories_complete(self):
        self._write_prd(
            {
                "project": "Test",
                "userStories": [
                    {"id": "US-001", "passes": True},
                    {"id": "US-002", "passes": False},
                    {"id": "US-003", "passes": True},
                ],
            }
        )
        passed, total, score = _check_prd_completion(self._tmpdir)
        assert passed == 2
        assert total == 3
        assert abs(score - 2 / 3) < 0.001

    def test_all_stories_complete(self):
        self._write_prd(
            {
                "project": "Test",
                "userStories": [
                    {"id": "US-001", "passes": True},
                    {"id": "US-002", "passes": True},
                ],
            }
        )
        passed, total, score = _check_prd_completion(self._tmpdir)
        assert passed == 2
        assert total == 2
        assert score == 1.0

    def test_missing_prd(self):
        passed, total, score = _check_prd_completion(self._tmpdir)
        assert passed == 0
        assert total == 0
        assert score == 0.0

    def test_empty_stories(self):
        self._write_prd({"project": "Test", "userStories": []})
        passed, total, score = _check_prd_completion(self._tmpdir)
        assert passed == 0
        assert total == 0
        assert score == 0.0

    def test_malformed_json(self):
        from pathlib import Path

        Path(self._tmpdir, "prd.json").write_text("not json {{{")
        passed, total, score = _check_prd_completion(self._tmpdir)
        assert passed == 0
        assert total == 0
        assert score == 0.0


class TestMergePrdPasses(TestCase):
    """_merge_prd_passes preserves on-disk completion state."""

    def test_preserves_passed_stories(self):
        new = [
            {"id": "US-001", "passes": False},
            {"id": "US-002", "passes": False},
        ]
        existing = [
            {"id": "US-001", "passes": True},
            {"id": "US-002", "passes": False},
        ]
        result = _merge_prd_passes(new, existing)
        assert result[0]["passes"] is True  # preserved
        assert result[1]["passes"] is False  # still incomplete

    def test_handles_new_stories_not_in_existing(self):
        new = [
            {"id": "US-001", "passes": False},
            {"id": "US-003", "passes": False},  # new story
        ]
        existing = [
            {"id": "US-001", "passes": True},
        ]
        result = _merge_prd_passes(new, existing)
        assert result[0]["passes"] is True
        assert result[1]["passes"] is False

    def test_empty_existing(self):
        new = [{"id": "US-001", "passes": False}]
        result = _merge_prd_passes(new, [])
        assert result[0]["passes"] is False

    def test_all_previously_passed(self):
        new = [
            {"id": "US-001", "passes": False},
            {"id": "US-002", "passes": False},
        ]
        existing = [
            {"id": "US-001", "passes": True},
            {"id": "US-002", "passes": True},
        ]
        result = _merge_prd_passes(new, existing)
        assert all(s["passes"] for s in result)


class TestReadProgressPatterns(TestCase):
    """_read_progress_patterns extracts the Codebase Patterns section."""

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_progress(self, content: str):
        from pathlib import Path

        Path(self._tmpdir, "progress.txt").write_text(content)

    def test_extracts_patterns_section(self):
        self._write_progress(
            "## Codebase Patterns\n"
            "- Always use uv run pytest\n"
            "- Models are in models.py\n"
            "\n"
            "## 2026-04-01 - US-001\n"
            "- Implemented auth\n"
        )
        result = _read_progress_patterns(self._tmpdir)
        assert "Always use uv run pytest" in result
        assert "Models are in models.py" in result
        assert "Implemented auth" not in result

    def test_no_patterns_section(self):
        self._write_progress("## 2026-04-01 - US-001\n- Implemented auth\n")
        result = _read_progress_patterns(self._tmpdir)
        assert result == ""

    def test_missing_file(self):
        result = _read_progress_patterns(self._tmpdir)
        assert result == ""

    def test_patterns_at_end_of_file(self):
        self._write_progress("## Codebase Patterns\n- Use Django Ninja for APIs\n")
        result = _read_progress_patterns(self._tmpdir)
        assert "Use Django Ninja for APIs" in result


class TestRalphWorkerInstructions(TestCase):
    """RALPH_WORKER_INSTRUCTIONS constant is well-formed."""

    def test_instructions_exist(self):
        assert len(RALPH_WORKER_INSTRUCTIONS) > 100

    def test_instructions_mention_prd(self):
        assert "prd.json" in RALPH_WORKER_INSTRUCTIONS

    def test_instructions_mention_progress(self):
        assert "progress.txt" in RALPH_WORKER_INSTRUCTIONS

    def test_instructions_mention_one_story(self):
        assert "ONE" in RALPH_WORKER_INSTRUCTIONS


class TestRalphToolSchema(TestCase):
    """The ralph_loop FunctionTool generates a correct JSON schema."""

    def test_schema_generation(self):
        from exo import FunctionTool

        async def _ralph_loop_fn(
            prd_content: str,
            instructions: str | None = None,
            max_iterations: int = 10,
        ) -> str:
            """Spawn ralph loop.

            Args:
                prd_content: The PRD JSON string.
                instructions: Project context.
                max_iterations: Max iterations.
            """
            return ""

        tool = FunctionTool(_ralph_loop_fn, name="ralph_loop", description="test")
        assert tool.name == "ralph_loop"
        params = tool.parameters
        assert "prd_content" in params["properties"]
        assert params["properties"]["prd_content"]["type"] == "string"
        assert "instructions" in params["properties"]
        assert "max_iterations" in params["properties"]
        assert params["properties"]["max_iterations"]["type"] == "integer"
        assert params["required"] == ["prd_content"]


class TestRalphLoopIntegration(TestCase):
    """Integration test: ralph loop iteration with mocked agent."""

    def test_full_loop_completes_all_stories(self):
        """Simulate a ralph loop where each iteration marks one story as passed."""
        import json
        import tempfile
        from pathlib import Path

        tmpdir = tempfile.mkdtemp()
        try:
            prd = {
                "project": "TestProject",
                "branchName": "test/ralph",
                "description": "Test PRD",
                "userStories": [
                    {
                        "id": "US-001",
                        "title": "Add config file",
                        "description": "Create config",
                        "acceptanceCriteria": ["config.json exists"],
                        "priority": 1,
                        "passes": False,
                        "notes": "",
                    },
                    {
                        "id": "US-002",
                        "title": "Add main module",
                        "description": "Create main.py",
                        "acceptanceCriteria": ["main.py exists"],
                        "priority": 2,
                        "passes": False,
                        "notes": "",
                    },
                ],
            }

            prd_path = Path(tmpdir) / "prd.json"
            prd_path.write_text(json.dumps(prd))
            progress_path = Path(tmpdir) / "progress.txt"
            progress_path.write_text("## Codebase Patterns\n\n---\n")

            # Simulate iteration 1: mark US-001 as passed
            passed, total, score = _check_prd_completion(tmpdir)
            assert passed == 0
            assert total == 2

            # Agent would implement US-001, then update prd.json
            prd["userStories"][0]["passes"] = True
            prd_path.write_text(json.dumps(prd))

            passed, total, score = _check_prd_completion(tmpdir)
            assert passed == 1
            assert total == 2
            assert abs(score - 0.5) < 0.001

            # Simulate iteration 2: mark US-002 as passed
            prd["userStories"][1]["passes"] = True
            prd_path.write_text(json.dumps(prd))

            passed, total, score = _check_prd_completion(tmpdir)
            assert passed == 2
            assert total == 2
            assert score == 1.0

            # Verify progress patterns work
            progress_path.write_text(
                "## Codebase Patterns\n- Use json for config\n\n---\n## 2026-04-01 - US-001\n- Created config.json\n"
            )
            patterns = _read_progress_patterns(tmpdir)
            assert "Use json for config" in patterns
            assert "Created config.json" not in patterns

        finally:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)
