"""Integration tests for credit system hooks in the execution pipeline (Phase 2 & 3)."""

from decimal import Decimal

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.billing.models import (
    CreditHold,
    CreditTransaction,
    CreditWallet,
    SubscriptionPlan,
    UserSubscription,
)
from apps.storage.models import AgentRun, Conversation
from apps.users.tests.factories import UserFactory

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def plan(db):
    return SubscriptionPlan.objects.create(
        name="Pro",
        tier="premium",
        price=Decimal("19.00"),
        monthly_credits=12000,
        features={"weekly_tasks": 15},
    )


@pytest.fixture
def subscription(user, plan):
    return UserSubscription.objects.create(user=user, plan=plan, status="active")


@pytest.fixture
def wallet(user, subscription):
    """Get signal-created wallet and set known balances."""
    wallet, _ = CreditWallet.objects.update_or_create(
        user=user,
        defaults={
            "monthly_credits": 12000,
            "monthly_credits_remaining": 10000,
            "addon_credits": 500,
            "free_credits": 150,
        },
    )
    return wallet


@pytest.fixture
def conversation(user):
    return Conversation.objects.create(user=user, title="test")


@pytest.fixture
def agent_run(user, conversation):
    run = AgentRun.objects.create(
        conversation=conversation,
        user=user,
        task="test task",
        run_id="test-run-id",
        model="openai:gpt-4o",
    )
    conversation.current_task = run
    conversation.save(update_fields=["current_task"])
    return run


@pytest.fixture
def hold(wallet, agent_run):
    return CreditHold.objects.create(
        wallet=wallet,
        run=agent_run,
        amount_reserved=500,
        amount_consumed=0,
        status="active",
    )


class _FakeData:
    """Minimal data object matching AgentStartInput shape."""

    def __init__(self):
        self.prompt = "test prompt"
        self.files = []
        self.addons = []
        self.mcp_configs = []
        self.model = ""
        self.customise = {}


# ── 2.1: Credit Hold at Task Start (MOVED TO SANDBOX) ────────────────────────
# Hold creation + insufficient-credits + no-wallet coverage has moved to the
# sandbox (Step 1b of the backend purge — ``start_run`` creates DjangoAgentRun
# + DjangoCreditHold inline). See ``packages/sandbox/agent_server/engine/billing.py``
# ``create_hold`` / ``InsufficientCreditsError``. Sandbox-side tests belong in
# ``packages/sandbox/tests/test_billing.py`` (to be written).


# ── 2.5a: Terminal-state settlement/refund moved to sandbox ──────────────────
# Coverage is now in ``packages/sandbox/tests/test_billing.py`` — the backend
# no longer owns run-terminal transitions.


# ── 2.3: Compute Credit Deduction ────────────────────────────────────────────


@pytest.mark.django_db
class TestComputeCredits:
    def test_compute_credits_consumed_on_sandbox_billing(
        self, user, wallet, conversation, agent_run, hold
    ):
        from apps.agents.models import E2bSandbox

        sandbox = E2bSandbox.objects.create(
            sandbox_id="test-sandbox-123",
            conversation=conversation,
            start_time=timezone.now(),
        )

        sandbox._record_billing_usage(300)  # 5 minutes

        tx = CreditTransaction.objects.filter(hold=hold, category="compute").first()
        assert tx is not None
        assert tx.amount < 0
        # 300s = 5min → ceil(5 * 8) = 40 credits
        assert abs(tx.amount) == 40
        assert tx.source_type == "e2b:sandbox"

    def test_compute_credits_skipped_without_hold(
        self, user, subscription, conversation
    ):
        """No hold on run — compute credits silently skipped."""
        from apps.agents.models import E2bSandbox

        run = AgentRun.objects.create(conversation=conversation, user=user, task="test")
        conversation.current_task = run
        conversation.save(update_fields=["current_task"])

        sandbox = E2bSandbox.objects.create(
            sandbox_id="test-sandbox-456",
            conversation=conversation,
            start_time=timezone.now(),
        )

        sandbox._record_billing_usage(120)  # No exception

        assert not CreditTransaction.objects.filter(category="compute").exists()


# ── 2.2: LLM Credit Deduction ────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
class TestLLMCredits:
    @pytest.mark.skip(
        reason="Per-event _consume_llm_credits removed — credits now settled post-run via set_run_terminal_state"
    )
    @pytest.mark.asyncio
    async def test_llm_credits_consumed(
        self, user, wallet, conversation, agent_run, hold
    ):
        pass

        tx = await sync_to_async(
            lambda: CreditTransaction.objects.filter(hold=hold, category="llm").first()
        )()
        assert tx is not None
        assert tx.amount < 0
        # $0.01 * 2.0 * 1000 = 20 credits
        assert abs(tx.amount) == 20
        assert tx.source_type == "openai:gpt-4o"

    @pytest.mark.skip(
        reason="Per-event _consume_llm_credits removed — credits now settled post-run"
    )
    @pytest.mark.asyncio
    async def test_llm_credits_zero_for_byom(
        self, user, wallet, conversation, agent_run, hold
    ):
        pass

    def test_cumulative_cost_delta_tracking(self):
        """Verify delta logic: cumulative cost subtraction works correctly."""
        prev = 0.0

        cost_1 = 0.01
        delta_1 = cost_1 - prev if cost_1 > prev else cost_1
        prev = max(prev, cost_1)
        assert abs(delta_1 - 0.01) < 1e-9

        cost_2 = 0.025
        delta_2 = cost_2 - prev if cost_2 > prev else cost_2
        prev = max(prev, cost_2)
        assert abs(delta_2 - 0.015) < 1e-9

        cost_3 = 0.005
        delta_3 = cost_3 - prev if cost_3 > prev else cost_3
        prev = max(prev, cost_3)
        assert abs(delta_3 - 0.005) < 1e-9


# ── 3.1: Credit Enforcement Gate (MOVED TO SANDBOX) ─────────────────────────
# Insufficient-credits-at-start is enforced inside the sandbox's ``start_run``
# (Step 1b). It returns HTTP 402 directly, with the backend no longer involved
# in the per-run credit check. Coverage belongs in
# ``packages/sandbox/tests/test_billing.py``.


# ── 3.3: Smarter Hold Estimation (MOVED TO SANDBOX) ─────────────────────────
# ``estimate_hold_amount`` now lives in
# ``packages/sandbox/agent_server/engine/billing.py`` and runs during
# ``start_run``. Pipeline-level coverage belongs in
# ``packages/sandbox/tests/test_billing.py``.
