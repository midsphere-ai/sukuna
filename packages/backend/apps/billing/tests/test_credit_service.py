"""Unit tests for CreditService."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing.credit_service import SIGNUP_BONUS, CreditService
from apps.billing.errors import InsufficientCreditsError
from apps.billing.models import (
    CreditGrant,
    CreditHold,
    CreditRate,
    CreditTransaction,
    CreditWallet,
    SubscriptionPlan,
    UserSubscription,
)
from apps.storage.models import AgentRun, Conversation
from apps.users.tests.factories import UserFactory


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
def free_plan(db):
    return SubscriptionPlan.objects.create(
        name="Free",
        tier="free",
        price=Decimal("0"),
        monthly_credits=300,
    )


@pytest.fixture
def subscription(user, plan):
    return UserSubscription.objects.create(user=user, plan=plan, status="active")


@pytest.fixture
def wallet(user):
    return CreditWallet.objects.create(
        user=user,
        monthly_credits=12000,
        monthly_credits_remaining=10000,
        addon_credits=500,
        free_credits=150,
    )


@pytest.fixture
def agent_run(user):
    conv = Conversation.objects.create(user=user, title="test")
    return AgentRun.objects.create(conversation=conv, user=user, task="test task")


@pytest.fixture
def hold(wallet, agent_run):
    return CreditHold.objects.create(
        wallet=wallet,
        run=agent_run,
        amount_reserved=500,
        amount_consumed=0,
        status="active",
    )


def _make_run(user):
    conv = Conversation.objects.create(user=user, title="test")
    return AgentRun.objects.create(conversation=conv, user=user, task="test task")


@pytest.mark.django_db
class TestGetOrCreateWallet:
    def test_creates_wallet_with_signup_bonus(self, user):
        wallet = CreditService.get_or_create_wallet(user)
        assert wallet.free_credits == SIGNUP_BONUS
        assert CreditTransaction.objects.filter(
            wallet=wallet, category="signup_bonus"
        ).exists()

    def test_returns_existing_wallet(self, wallet):
        existing = CreditService.get_or_create_wallet(wallet.user)
        assert existing.pk == wallet.pk
        # Should not create duplicate bonus
        assert (
            CreditTransaction.objects.filter(
                wallet=wallet, category="signup_bonus"
            ).count()
            == 0
        )

    def test_wallet_gets_plan_credits(self, subscription):
        wallet = CreditService.get_or_create_wallet(subscription.user)
        assert wallet.monthly_credits == 12000
        assert wallet.monthly_credits_remaining == 12000


@pytest.mark.django_db
class TestSyncWalletToPlan:
    def test_updates_monthly_credits(self, wallet, plan):
        wallet.monthly_credits = 300
        wallet.monthly_credits_remaining = 50
        wallet.save()
        CreditService.sync_wallet_to_plan(wallet, plan)
        wallet.refresh_from_db()
        assert wallet.monthly_credits == 12000
        assert wallet.monthly_credits_remaining == 12000


@pytest.mark.django_db
class TestCreateHold:
    def test_creates_hold(self, wallet, agent_run):
        hold = CreditService.create_hold(wallet, agent_run, 100)
        assert hold.amount_reserved == 100
        assert hold.amount_consumed == 0
        assert hold.status == "active"

    def test_insufficient_credits(self, user):
        wallet = CreditWallet.objects.create(
            user=user,
            monthly_credits=10,
            monthly_credits_remaining=5,
        )
        run = _make_run(user)
        with pytest.raises(InsufficientCreditsError):
            CreditService.create_hold(wallet, run, 100)


@pytest.mark.django_db
class TestConsume:
    def test_basic_deduction(self, hold):
        tx = CreditService.consume(
            hold,
            "llm",
            20,
            source_type="openai:gpt-4o",
            description="LLM tokens",
        )
        assert tx is not None
        assert tx.amount == -20
        assert tx.category == "llm"
        hold.refresh_from_db()
        assert hold.amount_consumed == 20
        hold.wallet.refresh_from_db()
        assert hold.wallet.monthly_credits_remaining == 10000 - 20

    def test_zero_amount_returns_none(self, hold):
        assert CreditService.consume(hold, "llm", 0) is None

    def test_non_active_hold_returns_none(self, hold):
        hold.status = "settled"
        hold.save()
        assert CreditService.consume(hold, "llm", 10) is None

    def test_insufficient_credits_raises(self, user):
        wallet = CreditWallet.objects.create(
            user=user,
            monthly_credits=10,
            monthly_credits_remaining=5,
        )
        run = _make_run(user)
        hold = CreditHold.objects.create(
            wallet=wallet,
            run=run,
            amount_reserved=100,
            status="active",
        )
        with pytest.raises(InsufficientCreditsError):
            CreditService.consume(hold, "llm", 50)

    def test_priority_order_grants_first(self, wallet, agent_run):
        # Add an event grant
        CreditGrant.objects.create(
            wallet=wallet,
            grant_type="event",
            amount=30,
            remaining=30,
            expires_at=timezone.now() + timedelta(days=1),
        )
        hold = CreditHold.objects.create(
            wallet=wallet,
            run=agent_run,
            amount_reserved=500,
            status="active",
        )
        CreditService.consume(hold, "llm", 50)
        # Grant should be drained first
        grant = CreditGrant.objects.get(wallet=wallet)
        assert grant.remaining == 0
        # Then 20 from monthly
        wallet.refresh_from_db()
        assert wallet.monthly_credits_remaining == 10000 - 20

    def test_priority_monthly_then_addon_then_free(self, user):
        wallet = CreditWallet.objects.create(
            user=user,
            monthly_credits=10,
            monthly_credits_remaining=5,
            addon_credits=10,
            free_credits=10,
        )
        run = _make_run(user)
        hold = CreditHold.objects.create(
            wallet=wallet,
            run=run,
            amount_reserved=100,
            status="active",
        )
        CreditService.consume(hold, "compute", 20)
        wallet.refresh_from_db()
        assert wallet.monthly_credits_remaining == 0  # 5 taken
        assert wallet.addon_credits == 0  # 10 taken
        assert wallet.free_credits == 5  # 5 taken

    def test_version_incremented(self, hold):
        old_version = hold.wallet.version
        CreditService.consume(hold, "llm", 10)
        hold.wallet.refresh_from_db()
        assert hold.wallet.version == old_version + 1


@pytest.mark.django_db
class TestSettle:
    def test_settle_active_hold(self, hold):
        hold.amount_consumed = 200
        hold.save()
        CreditService.settle(hold)
        hold.refresh_from_db()
        assert hold.status == "settled"
        assert hold.settled_at is not None

    def test_settle_non_active_noop(self, hold):
        hold.status = "refunded"
        hold.save()
        CreditService.settle(hold)
        hold.refresh_from_db()
        assert hold.status == "refunded"


@pytest.mark.django_db
class TestRefund:
    def test_refund_returns_credits(self, hold):
        # Consume some credits first
        CreditService.consume(hold, "llm", 100)
        wallet_before = hold.wallet.monthly_credits_remaining
        hold.wallet.refresh_from_db()
        wallet_before = hold.wallet.monthly_credits_remaining

        tx = CreditService.refund(hold, reason="platform crash")
        assert tx is not None
        assert tx.amount == 100
        assert tx.category == "refund"
        hold.refresh_from_db()
        assert hold.status == "refunded"
        hold.wallet.refresh_from_db()
        assert hold.wallet.monthly_credits_remaining == wallet_before + 100

    def test_refund_zero_consumed(self, hold):
        tx = CreditService.refund(hold)
        assert tx is None
        hold.refresh_from_db()
        assert hold.status == "refunded"

    def test_refund_non_active_noop(self, hold):
        hold.status = "settled"
        hold.save()
        tx = CreditService.refund(hold)
        assert tx is None


@pytest.mark.django_db
class TestRefreshMonthly:
    def test_resets_remaining(self, wallet):
        wallet.monthly_credits_remaining = 0
        wallet.save()
        tx = CreditService.refresh_monthly(wallet)
        wallet.refresh_from_db()
        assert wallet.monthly_credits_remaining == 12000
        assert tx.category == "refresh"
        assert tx.amount == 12000


@pytest.mark.django_db
class TestPurchaseAddonPack:
    def test_adds_to_addon_credits(self, wallet):
        tx = CreditService.purchase_addon_pack(wallet, 1000)
        wallet.refresh_from_db()
        assert wallet.addon_credits == 500 + 1000
        assert tx.amount == 1000
        assert tx.category == "purchase"


@pytest.mark.django_db
class TestCalculations:
    def test_llm_credits_default(self):
        # $0.01 * 2.0 * 1000 = 20
        assert CreditService.calculate_llm_credits(0.01) == 20

    def test_llm_credits_byom(self):
        assert CreditService.calculate_llm_credits(0.50, is_byom=True) == 0

    def test_llm_credits_zero(self):
        assert CreditService.calculate_llm_credits(0) == 0

    def test_llm_credits_with_rate(self, db):
        CreditRate.objects.create(
            category="llm",
            key="default",
            credits_per_unit=Decimal("2000"),
            unit="usd",
            markup=Decimal("2.00"),
        )
        # $0.015 * 2000 * 2.0 = 60
        assert CreditService.calculate_llm_credits(0.015) == 60

    def test_compute_credits_default(self):
        # 300 seconds = 5 minutes * 8 = 40
        assert CreditService.calculate_compute_credits(300) == 40

    def test_compute_credits_partial_minute(self):
        # 90 seconds = 1.5 minutes * 8 = 12
        assert CreditService.calculate_compute_credits(90) == 12

    def test_compute_credits_zero(self):
        assert CreditService.calculate_compute_credits(0) == 0

    def test_integration_credits_tiers(self):
        assert CreditService.calculate_integration_credits("basic") == 2
        assert CreditService.calculate_integration_credits("standard") == 5
        assert CreditService.calculate_integration_credits("premium") == 10


@pytest.mark.django_db
class TestGetHoldForRun:
    def test_returns_active_hold(self, hold, agent_run):
        found = CreditService.get_hold_for_run(agent_run)
        assert found is not None
        assert found.pk == hold.pk

    def test_returns_none_for_settled(self, hold, agent_run):
        hold.status = "settled"
        hold.save()
        assert CreditService.get_hold_for_run(agent_run) is None


@pytest.mark.django_db
class TestGetUsageSummary:
    def test_aggregates_by_category(self, wallet, agent_run):
        hold = CreditHold.objects.create(
            wallet=wallet,
            run=agent_run,
            amount_reserved=500,
            status="active",
        )
        CreditService.consume(hold, "llm", 100)
        CreditService.consume(hold, "compute", 40)
        CreditService.consume(hold, "llm", 50)

        summary = CreditService.get_usage_summary(wallet)
        assert summary["llm"] == 150
        assert summary["compute"] == 40


@pytest.mark.django_db
class TestEstimateHoldAmount:
    def test_returns_default_without_history(self, wallet):
        assert CreditService.estimate_hold_amount(wallet) == 100

    def test_returns_average_of_settled_holds(self, wallet):
        conv = Conversation.objects.create(user=wallet.user, title="test")
        for consumed in [40, 60, 80]:
            run = AgentRun.objects.create(
                conversation=conv,
                user=wallet.user,
                task="test",
            )
            CreditHold.objects.create(
                wallet=wallet,
                run=run,
                amount_reserved=200,
                amount_consumed=consumed,
                status="settled",
                settled_at=timezone.now(),
            )
        # avg(40, 60, 80) = 60
        assert CreditService.estimate_hold_amount(wallet) == 60

    def test_respects_floor(self, wallet):
        conv = Conversation.objects.create(user=wallet.user, title="test")
        run = AgentRun.objects.create(
            conversation=conv,
            user=wallet.user,
            task="test",
        )
        CreditHold.objects.create(
            wallet=wallet,
            run=run,
            amount_reserved=50,
            amount_consumed=5,
            status="settled",
            settled_at=timezone.now(),
        )
        # avg=5 but floor is 20
        assert CreditService.estimate_hold_amount(wallet) == 20

    def test_respects_cap(self, wallet):
        conv = Conversation.objects.create(user=wallet.user, title="test")
        run = AgentRun.objects.create(
            conversation=conv,
            user=wallet.user,
            task="test",
        )
        CreditHold.objects.create(
            wallet=wallet,
            run=run,
            amount_reserved=1000,
            amount_consumed=900,
            status="settled",
            settled_at=timezone.now(),
        )
        # avg=900 but cap is 500
        assert CreditService.estimate_hold_amount(wallet) == 500

    def test_ignores_active_and_refunded_holds(self, wallet):
        conv = Conversation.objects.create(user=wallet.user, title="test")
        for status in ["active", "refunded"]:
            run = AgentRun.objects.create(
                conversation=conv,
                user=wallet.user,
                task="test",
            )
            CreditHold.objects.create(
                wallet=wallet,
                run=run,
                amount_reserved=200,
                amount_consumed=100,
                status=status,
            )
        # No settled holds → default
        assert CreditService.estimate_hold_amount(wallet) == 100
