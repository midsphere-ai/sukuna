"""Unit tests for credit system models."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing.models import (
    CreditGrant,
    CreditHold,
    CreditRate,
    CreditTransaction,
    CreditWallet,
    SubscriptionPlan,
)
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
def wallet(user):
    return CreditWallet.objects.create(
        user=user,
        monthly_credits=12000,
        monthly_credits_remaining=12000,
        addon_credits=500,
        free_credits=150,
    )


@pytest.mark.django_db
class TestCreditWallet:
    def test_creation_defaults(self, user):
        wallet = CreditWallet.objects.create(user=user)
        assert wallet.monthly_credits == 0
        assert wallet.monthly_credits_remaining == 0
        assert wallet.addon_credits == 0
        assert wallet.free_credits == 0
        assert wallet.version == 0

    def test_str(self, wallet):
        assert "credits" in str(wallet)
        assert wallet.user.email in str(wallet)

    def test_total_available_base(self, wallet):
        assert wallet.total_available == 12000 + 500 + 150

    def test_total_available_with_grants(self, wallet):
        CreditGrant.objects.create(
            wallet=wallet,
            grant_type="promo",
            amount=100,
            remaining=75,
            expires_at=timezone.now() + timedelta(days=7),
        )
        assert wallet.total_available == 12000 + 500 + 150 + 75

    def test_total_available_excludes_expired_grants(self, wallet):
        CreditGrant.objects.create(
            wallet=wallet,
            grant_type="event",
            amount=200,
            remaining=200,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        assert wallet.total_available == 12000 + 500 + 150

    def test_total_available_includes_non_expiring_grants(self, wallet):
        CreditGrant.objects.create(
            wallet=wallet,
            grant_type="referral",
            amount=300,
            remaining=300,
            expires_at=None,
        )
        assert wallet.total_available == 12000 + 500 + 150 + 300


@pytest.mark.django_db
class TestCreditGrant:
    def test_is_expired_future(self, wallet):
        grant = CreditGrant.objects.create(
            wallet=wallet,
            grant_type="event",
            amount=100,
            remaining=100,
            expires_at=timezone.now() + timedelta(days=1),
        )
        assert not grant.is_expired

    def test_is_expired_past(self, wallet):
        grant = CreditGrant.objects.create(
            wallet=wallet,
            grant_type="event",
            amount=100,
            remaining=100,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        assert grant.is_expired

    def test_is_expired_null(self, wallet):
        grant = CreditGrant.objects.create(
            wallet=wallet,
            grant_type="referral",
            amount=100,
            remaining=100,
            expires_at=None,
        )
        assert not grant.is_expired

    def test_ordering(self, wallet):
        g1 = CreditGrant.objects.create(
            wallet=wallet,
            grant_type="event",
            amount=10,
            remaining=10,
            expires_at=timezone.now() + timedelta(days=5),
        )
        g2 = CreditGrant.objects.create(
            wallet=wallet,
            grant_type="event",
            amount=20,
            remaining=20,
            expires_at=timezone.now() + timedelta(days=1),
        )
        grants = list(CreditGrant.objects.filter(wallet=wallet))
        assert grants[0] == g2  # sooner expiry first


@pytest.mark.django_db
class TestCreditHold:
    def test_str(self, wallet):
        from apps.storage.models import AgentRun, Conversation

        conv = Conversation.objects.create(user=wallet.user, title="test")
        run = AgentRun.objects.create(
            conversation=conv, user=wallet.user, task="test task"
        )
        hold = CreditHold.objects.create(
            wallet=wallet,
            run=run,
            amount_reserved=500,
            amount_consumed=123,
        )
        s = str(hold)
        assert "123" in s
        assert "500" in s
        assert "active" in s


@pytest.mark.django_db
class TestCreditTransaction:
    def test_str_positive(self, wallet):
        tx = CreditTransaction.objects.create(
            wallet=wallet,
            amount=500,
            balance_after=13150,
            category="purchase",
            description="Purchased 500 credits",
        )
        assert "+500" in str(tx)
        assert "purchase" in str(tx)

    def test_str_negative(self, wallet):
        tx = CreditTransaction.objects.create(
            wallet=wallet,
            amount=-20,
            balance_after=12630,
            category="llm",
            description="GPT-4o tokens",
        )
        assert "-20" in str(tx)

    def test_ordering(self, wallet):
        tx1 = CreditTransaction.objects.create(
            wallet=wallet,
            amount=-10,
            balance_after=100,
            category="llm",
        )
        tx2 = CreditTransaction.objects.create(
            wallet=wallet,
            amount=-20,
            balance_after=80,
            category="compute",
        )
        txs = list(CreditTransaction.objects.filter(wallet=wallet))
        assert txs[0] == tx2  # most recent first


@pytest.mark.django_db
class TestCreditRate:
    def test_calculate(self):
        rate = CreditRate.objects.create(
            category="llm",
            key="default",
            credits_per_unit=Decimal("2000"),
            unit="usd",
            markup=Decimal("2.00"),
        )
        # $0.01 * 2000 * 2.0 = 40 credits
        assert rate.calculate(0.01) == 40

    def test_calculate_compute(self):
        rate = CreditRate.objects.create(
            category="compute",
            key="e2b:default",
            credits_per_unit=Decimal("8"),
            unit="minute",
            markup=Decimal("1.00"),
        )
        # 10 minutes * 8 * 1.0 = 80 credits
        assert rate.calculate(10) == 80

    def test_unique_active_constraint(self):
        CreditRate.objects.create(
            category="llm",
            key="default",
            credits_per_unit=Decimal("2000"),
            unit="usd",
        )
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            CreditRate.objects.create(
                category="llm",
                key="default",
                credits_per_unit=Decimal("3000"),
                unit="usd",
            )

    def test_str(self):
        rate = CreditRate.objects.create(
            category="integration",
            key="composio:standard",
            credits_per_unit=Decimal("5"),
            unit="invocation",
        )
        assert "composio:standard" in str(rate)


@pytest.mark.django_db
class TestSubscriptionPlanMonthlyCredits:
    def test_monthly_credits_field(self, plan):
        assert plan.monthly_credits == 12000

    def test_default_zero(self, db):
        p = SubscriptionPlan.objects.create(
            name="Free", tier="free", price=Decimal("0")
        )
        assert p.monthly_credits == 0
