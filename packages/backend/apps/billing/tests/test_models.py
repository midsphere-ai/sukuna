"""Unit tests for billing app models and managers."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.billing.models import (
    CouponUsage,
    CustomerSupportTicket,
    FailedPayment,
    Payment,
    PromoCoupon,
    SubscriptionHistory,
    SubscriptionPause,
    SubscriptionPlan,
    TrialPeriod,
    UsageRecord,
    UserSubscription,
    WebhookEvent,
)
from apps.users.tests.factories import UserFactory


# ---------------------------------------------------------------------------
# SubscriptionPlan
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSubscriptionPlan:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.free = SubscriptionPlan.objects.create(
            name="Free",
            tier="free",
            price=Decimal("0.00"),
            features={"weekly_tasks": 5},
        )
        self.basic = SubscriptionPlan.objects.create(
            name="Basic",
            tier="basic",
            price=Decimal("9.00"),
            dodo_product_id="plan_123",
        )
        self.premium = SubscriptionPlan.objects.create(
            name="Premium",
            tier="premium",
            price=Decimal("19.00"),
            features={"weekly_tasks": 100, "max_sandbox_time": 3600},
            is_active=False,
        )

    def test_str(self):
        assert str(self.free) == "Free - $0.00"
        assert str(self.basic) == "Basic - $9.00"

    def test_active_manager(self):
        active = SubscriptionPlan.objects.active()
        assert self.free in active
        assert self.basic in active
        assert self.premium not in active

    def test_clean_valid_features(self):
        self.free.features = {
            "storage": "10GB",
            "tasks": 5,
            "premium": True,
            "rate": 1.5,
        }
        self.free.clean()  # should not raise

    def test_clean_invalid_feature_value(self):
        self.free.features = {"bad": [1, 2, 3]}
        with pytest.raises(ValidationError):
            self.free.clean()

    def test_clean_empty_features(self):
        self.free.features = {}
        self.free.clean()  # should not raise

    def test_unique_tier(self):
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            SubscriptionPlan.objects.create(
                name="Another Free", tier="free", price=Decimal("0.00")
            )


# ---------------------------------------------------------------------------
# SubscriptionPlanManager
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSubscriptionPlanManager:
    def test_active_returns_only_active(self):
        SubscriptionPlan.objects.create(
            name="A", tier="free", price=Decimal("0"), is_active=True
        )
        SubscriptionPlan.objects.create(
            name="B", tier="basic", price=Decimal("5"), is_active=False
        )
        assert SubscriptionPlan.objects.active().count() == 1


# ---------------------------------------------------------------------------
# UserSubscription
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUserSubscription:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.plan = SubscriptionPlan.objects.create(
            name="Basic",
            tier="basic",
            price=Decimal("9.00"),
            features={"weekly_tasks": 10, "max_sandbox_time": 3600},
        )
        self.sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=30),
        )

    def test_str_with_plan(self):
        assert self.user.email in str(self.sub)
        assert "Basic" in str(self.sub)

    def test_str_no_plan(self):
        self.sub.plan = None
        self.sub.save()
        assert "No Plan" in str(self.sub)

    def test_is_active_true(self):
        assert self.sub.is_active() is True

    def test_is_active_expired(self):
        self.sub.end_date = timezone.now() - timedelta(days=1)
        self.sub.save()
        assert self.sub.is_active() is False

    def test_is_active_no_end_date(self):
        self.sub.end_date = None
        self.sub.save()
        assert self.sub.is_active() is True

    def test_is_active_cancelled(self):
        self.sub.status = "cancelled"
        self.sub.save()
        assert self.sub.is_active() is False

    def test_in_grace_period_true(self):
        self.sub.grace_period_end = timezone.now() + timedelta(days=7)
        self.sub.save()
        assert self.sub.in_grace_period() is True

    def test_in_grace_period_false(self):
        self.sub.grace_period_end = timezone.now() - timedelta(days=1)
        self.sub.save()
        assert self.sub.in_grace_period() is False

    def test_in_grace_period_none(self):
        assert self.sub.in_grace_period() is False

    def test_get_weekly_task_limit(self):
        assert self.sub.get_weekly_task_limit() == 10

    def test_get_weekly_task_limit_tuple_feature(self):
        self.plan.features = {"weekly_tasks": [25, "25 tasks/week"]}
        self.plan.save()
        assert self.sub.get_weekly_task_limit() == 25

    def test_get_weekly_task_limit_no_plan(self):
        self.sub.plan = None
        self.sub.save()
        assert self.sub.get_weekly_task_limit() == 0

    def test_get_weekly_task_limit_no_features(self):
        self.plan.features = {}
        self.plan.save()
        assert self.sub.get_weekly_task_limit() == 0

    def test_get_feature_info(self):
        assert self.sub.get_feature_info("weekly_tasks") == 10
        assert self.sub.get_feature_info("max_sandbox_time") == 3600
        assert self.sub.get_feature_info("nonexistent") is None

    def test_get_feature_info_tuple(self):
        self.plan.features = {"weekly_tasks": [25, "label"]}
        self.plan.save()
        assert self.sub.get_feature_info("weekly_tasks") == 25

    def test_get_feature_info_no_plan(self):
        self.sub.plan = None
        self.sub.save()
        assert self.sub.get_feature_info("weekly_tasks") is None

    def test_get_feature_info_no_features(self):
        self.plan.features = {}
        self.plan.save()
        assert self.sub.get_feature_info("weekly_tasks") is None

    def test_get_tasks_used_this_week(self):
        assert self.sub.get_tasks_used_this_week() == 0
        # Add a reserved task this week
        UsageRecord.objects.create(
            subscription=self.sub,
            user=self.user,
            metric_name="agent_task",
            quantity=1,
            metadata={"status": "reserved", "run_id": "r1"},
        )
        assert self.sub.get_tasks_used_this_week() == 1

    def test_get_tasks_used_this_week_excludes_voided(self):
        UsageRecord.objects.create(
            subscription=self.sub,
            user=self.user,
            metric_name="agent_task",
            quantity=1,
            metadata={"status": "voided", "run_id": "r2"},
        )
        assert self.sub.get_tasks_used_this_week() == 0

    def test_can_run_task(self):
        assert self.sub.can_run_task() is True

    def test_can_run_task_at_limit(self):
        for i in range(10):
            UsageRecord.objects.create(
                subscription=self.sub,
                user=self.user,
                metric_name="agent_task",
                quantity=1,
                metadata={"status": "reserved", "run_id": f"r{i}"},
            )
        assert self.sub.can_run_task() is False

    def test_get_remaining_tasks(self):
        assert self.sub.get_remaining_tasks() == 10
        UsageRecord.objects.create(
            subscription=self.sub,
            user=self.user,
            metric_name="agent_task",
            quantity=1,
            metadata={"status": "completed", "run_id": "r1"},
        )
        assert self.sub.get_remaining_tasks() == 9

    def test_get_sandbox_time(self):
        assert self.sub.get_sandbox_time() == 0
        UsageRecord.objects.create(
            subscription=self.sub,
            user=self.user,
            metric_name="sandbox_time",
            quantity=Decimal("120"),
        )
        assert self.sub.get_sandbox_time() == Decimal("120")

    def test_check_sandbox_available(self):
        assert self.sub.check_sandbox_available() is True
        # Exhaust sandbox time
        UsageRecord.objects.create(
            subscription=self.sub,
            user=self.user,
            metric_name="sandbox_time",
            quantity=Decimal("3601"),
        )
        assert self.sub.check_sandbox_available() is False

    def test_check_sandbox_available_no_feature(self):
        self.plan.features = {}
        self.plan.save()
        assert self.sub.check_sandbox_available() is False

    def test_record_task_usage(self):
        self.sub.record_task_usage(metadata={"run_id": "abc", "status": "reserved"})
        rec = UsageRecord.objects.get(subscription=self.sub, metric_name="agent_task")
        assert rec.quantity == 1
        assert rec.metadata["run_id"] == "abc"

    def test_record_task_usage_no_metadata(self):
        self.sub.record_task_usage()
        rec = UsageRecord.objects.get(subscription=self.sub, metric_name="agent_task")
        assert rec.metadata == {}

    def test_record_feature_usage(self):
        self.sub.record_feature_usage(
            "sandbox_time", Decimal("60"), {"sandbox_id": "s1"}
        )
        rec = UsageRecord.objects.get(subscription=self.sub, metric_name="sandbox_time")
        assert rec.quantity == Decimal("60")

    def test_finalize_task_usage(self):
        UsageRecord.objects.create(
            subscription=self.sub,
            user=self.user,
            metric_name="agent_task",
            quantity=1,
            metadata={"run_id": "r1", "status": "reserved"},
        )
        self.sub.finalize_task_usage("r1")
        rec = UsageRecord.objects.get(subscription=self.sub, metric_name="agent_task")
        assert rec.metadata["status"] == "completed"

    def test_void_task_usage(self):
        UsageRecord.objects.create(
            subscription=self.sub,
            user=self.user,
            metric_name="agent_task",
            quantity=1,
            metadata={"run_id": "r1", "status": "reserved"},
        )
        self.sub.void_task_usage("r1")
        rec = UsageRecord.objects.get(subscription=self.sub, metric_name="agent_task")
        assert rec.metadata["status"] == "voided"


# ---------------------------------------------------------------------------
# UserSubscriptionManager
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUserSubscriptionManager:
    def test_by_dodo_id(self):
        user = UserFactory()
        plan = SubscriptionPlan.objects.create(
            name="P", tier="free", price=Decimal("0")
        )
        sub = UserSubscription.objects.create(
            user=user, plan=plan, status="active", dodo_subscription_id="sub_dodo_abc"
        )
        # by_dodo_id uses select_for_update, needs transaction

        # Just verify it returns the right object (select_for_update is a no-op in sqlite)
        found = UserSubscription.objects.by_dodo_id("sub_dodo_abc")
        assert found == sub

    def test_by_dodo_id_not_found(self):
        found = UserSubscription.objects.by_dodo_id("nonexistent")
        assert found is None


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPayment:
    def test_str(self):
        user = UserFactory()
        payment = Payment.objects.create(
            user=user, dodo_payment_id="pay_dodo_001", amount=Decimal("9.00")
        )
        assert user.email in str(payment)
        assert "9.00" in str(payment)
        assert "USD" in str(payment)

    def test_defaults(self):
        user = UserFactory()
        payment = Payment.objects.create(
            user=user, dodo_payment_id="pay_dodo_002", amount=Decimal("5.00")
        )
        assert payment.status == "created"
        assert payment.currency == "USD"
        assert payment.metadata == {}


# ---------------------------------------------------------------------------
# PaymentManager
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPaymentManager:
    def test_for_user(self):
        user = UserFactory()
        other_user = UserFactory()
        Payment.objects.create(
            user=user, dodo_payment_id="pay_dodo_o1", amount=Decimal("5")
        )
        Payment.objects.create(
            user=user, dodo_payment_id="pay_dodo_o2", amount=Decimal("10")
        )
        Payment.objects.create(
            user=other_user, dodo_payment_id="pay_dodo_o3", amount=Decimal("15")
        )

        payments = Payment.objects.for_user(user)
        assert payments.count() == 2
        # Most recent first
        assert list(payments.values_list("dodo_payment_id", flat=True)) == [
            "pay_dodo_o2",
            "pay_dodo_o1",
        ]


# ---------------------------------------------------------------------------
# SubscriptionHistory
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSubscriptionHistory:
    def test_str(self):
        user = UserFactory()
        plan = SubscriptionPlan.objects.create(
            name="F", tier="free", price=Decimal("0")
        )
        sub = UserSubscription.objects.create(user=user, plan=plan, status="active")
        history = SubscriptionHistory.objects.create(
            subscription=sub, user=user, action="created", new_plan=plan
        )
        assert user.email in str(history)
        assert "created" in str(history)

    def test_defaults(self):
        user = UserFactory()
        history = SubscriptionHistory.objects.create(user=user, action="created")
        assert history.notes == ""
        assert history.metadata == {}

    def test_ordering(self):
        user = UserFactory()
        h1 = SubscriptionHistory.objects.create(user=user, action="created")
        h2 = SubscriptionHistory.objects.create(user=user, action="upgraded")
        histories = list(SubscriptionHistory.objects.all())
        assert histories[0] == h2  # newest first


# ---------------------------------------------------------------------------
# SubscriptionHistoryManager
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSubscriptionHistoryManager:
    def test_for_user(self):
        user = UserFactory()
        other = UserFactory()
        plan = SubscriptionPlan.objects.create(
            name="F", tier="free", price=Decimal("0")
        )
        SubscriptionHistory.objects.create(user=user, action="created", new_plan=plan)
        SubscriptionHistory.objects.create(user=other, action="created")
        assert SubscriptionHistory.objects.for_user(user).count() == 1


# ---------------------------------------------------------------------------
# TrialPeriod
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTrialPeriod:
    def test_is_active_true(self):
        user = UserFactory()
        trial = TrialPeriod.objects.create(
            user=user, trial_end=timezone.now() + timedelta(days=7)
        )
        assert trial.is_active() is True

    def test_is_active_expired(self):
        user = UserFactory()
        trial = TrialPeriod.objects.create(
            user=user, trial_end=timezone.now() - timedelta(days=1)
        )
        assert trial.is_active() is False

    def test_is_active_converted(self):
        user = UserFactory()
        trial = TrialPeriod.objects.create(
            user=user,
            trial_end=timezone.now() + timedelta(days=7),
            converted_to_paid=True,
        )
        assert trial.is_active() is False

    def test_str(self):
        user = UserFactory()
        trial = TrialPeriod.objects.create(
            user=user, trial_end=timezone.now() + timedelta(days=7)
        )
        assert user.email in str(trial)

    def test_str_no_user(self):
        trial = TrialPeriod.objects.create(
            user=None, trial_end=timezone.now() + timedelta(days=7)
        )
        assert "Unknown" in str(trial)


# ---------------------------------------------------------------------------
# PromoCoupon
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPromoCoupon:
    def test_is_valid_true(self):
        coupon = PromoCoupon.objects.create(
            code="SAVE10",
            discount_type="percentage",
            discount_value=Decimal("10"),
            valid_from=timezone.now() - timedelta(days=1),
            valid_until=timezone.now() + timedelta(days=30),
        )
        assert coupon.is_valid() is True

    def test_is_valid_inactive(self):
        coupon = PromoCoupon.objects.create(
            code="DEAD",
            discount_type="fixed",
            discount_value=Decimal("5"),
            valid_from=timezone.now() - timedelta(days=1),
            valid_until=timezone.now() + timedelta(days=30),
            is_active=False,
        )
        assert coupon.is_valid() is False

    def test_is_valid_expired(self):
        coupon = PromoCoupon.objects.create(
            code="OLD",
            discount_type="percentage",
            discount_value=Decimal("10"),
            valid_from=timezone.now() - timedelta(days=60),
            valid_until=timezone.now() - timedelta(days=1),
        )
        assert coupon.is_valid() is False

    def test_is_valid_not_yet_started(self):
        coupon = PromoCoupon.objects.create(
            code="FUTURE",
            discount_type="percentage",
            discount_value=Decimal("10"),
            valid_from=timezone.now() + timedelta(days=1),
            valid_until=timezone.now() + timedelta(days=30),
        )
        assert coupon.is_valid() is False

    def test_is_valid_max_uses_reached(self):
        coupon = PromoCoupon.objects.create(
            code="LIMITED",
            discount_type="fixed",
            discount_value=Decimal("5"),
            valid_from=timezone.now() - timedelta(days=1),
            valid_until=timezone.now() + timedelta(days=30),
            max_uses=10,
            used_count=10,
        )
        assert coupon.is_valid() is False

    def test_is_valid_no_max_uses(self):
        coupon = PromoCoupon.objects.create(
            code="UNLIMITED",
            discount_type="fixed",
            discount_value=Decimal("5"),
            valid_from=timezone.now() - timedelta(days=1),
            valid_until=timezone.now() + timedelta(days=30),
            max_uses=None,
            used_count=999,
        )
        assert coupon.is_valid() is True

    def test_str_percentage(self):
        coupon = PromoCoupon.objects.create(
            code="PCT",
            discount_type="percentage",
            discount_value=Decimal("20"),
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=1),
        )
        assert "PCT" in str(coupon)
        assert "%" in str(coupon)

    def test_str_fixed(self):
        coupon = PromoCoupon.objects.create(
            code="FIX",
            discount_type="fixed",
            discount_value=Decimal("5"),
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=1),
        )
        assert "USD" in str(coupon)


# ---------------------------------------------------------------------------
# CouponUsage
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCouponUsage:
    def test_str(self):
        user = UserFactory()
        coupon = PromoCoupon.objects.create(
            code="USE1",
            discount_type="percentage",
            discount_value=Decimal("10"),
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=1),
        )
        usage = CouponUsage.objects.create(
            coupon=coupon, user=user, discount_applied=Decimal("1.80")
        )
        assert user.email in str(usage)
        assert "USE1" in str(usage)

    def test_unique_together(self):
        from django.db import IntegrityError

        user = UserFactory()
        coupon = PromoCoupon.objects.create(
            code="UNQ",
            discount_type="fixed",
            discount_value=Decimal("5"),
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(days=1),
        )
        CouponUsage.objects.create(
            coupon=coupon, user=user, discount_applied=Decimal("5")
        )
        with pytest.raises(IntegrityError):
            CouponUsage.objects.create(
                coupon=coupon, user=user, discount_applied=Decimal("5")
            )


# ---------------------------------------------------------------------------
# WebhookEvent
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestWebhookEvent:
    def test_str(self):
        event = WebhookEvent.objects.create(
            event_id="evt_1",
            event_type="subscription.activated",
            payload={"key": "val"},
        )
        assert "subscription.activated" in str(event)

    def test_defaults(self):
        event = WebhookEvent.objects.create(
            event_id="evt_2", event_type="payment.captured", payload={}
        )
        assert event.processed is False
        assert event.retry_count == 0
        assert event.error_message == ""

    def test_unique_event_id(self):
        from django.db import IntegrityError

        WebhookEvent.objects.create(event_id="evt_3", event_type="t", payload={})
        with pytest.raises(IntegrityError):
            WebhookEvent.objects.create(event_id="evt_3", event_type="t", payload={})

    def test_ordering(self):
        e1 = WebhookEvent.objects.create(event_id="e1", event_type="t", payload={})
        e2 = WebhookEvent.objects.create(event_id="e2", event_type="t", payload={})
        events = list(WebhookEvent.objects.all())
        assert events[0] == e2  # newest first


# ---------------------------------------------------------------------------
# UsageRecord
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUsageRecord:
    def test_str(self):
        user = UserFactory()
        rec = UsageRecord.objects.create(
            user=user, metric_name="api_calls", quantity=Decimal("42")
        )
        assert user.email in str(rec)
        assert "api_calls" in str(rec)

    def test_str_no_user(self):
        rec = UsageRecord.objects.create(
            user=None, metric_name="api_calls", quantity=Decimal("1")
        )
        assert "Unknown" in str(rec)

    def test_ordering(self):
        user = UserFactory()
        r1 = UsageRecord.objects.create(user=user, metric_name="m", quantity=1)
        r2 = UsageRecord.objects.create(user=user, metric_name="m", quantity=2)
        records = list(UsageRecord.objects.all())
        assert records[0] == r2  # newest first


# ---------------------------------------------------------------------------
# FailedPayment
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestFailedPayment:
    def test_str(self):
        user = UserFactory()
        fp = FailedPayment.objects.create(
            user=user, amount=Decimal("9.00"), error_code="CARD_DECLINED"
        )
        assert user.email in str(fp)
        assert "9.00" in str(fp)

    def test_defaults(self):
        user = UserFactory()
        fp = FailedPayment.objects.create(user=user, amount=Decimal("5"))
        assert fp.retry_count == 0
        assert fp.resolved is False


# ---------------------------------------------------------------------------
# SubscriptionPause
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSubscriptionPause:
    def test_str(self):
        user = UserFactory()
        pause = SubscriptionPause.objects.create(user=user, pause_reason="vacation")
        assert user.email in str(pause)

    def test_str_no_user(self):
        pause = SubscriptionPause.objects.create(user=None, pause_reason="test")
        assert "Unknown" in str(pause)

    def test_defaults(self):
        user = UserFactory()
        pause = SubscriptionPause.objects.create(user=user)
        assert pause.is_active is True
        assert pause.resumed_at is None


# ---------------------------------------------------------------------------
# CustomerSupportTicket
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCustomerSupportTicket:
    def test_str(self):
        user = UserFactory()
        ticket = CustomerSupportTicket.objects.create(
            user=user, title="Help!", message="I need help"
        )
        assert user.email in str(ticket)
        assert "Help!" in str(ticket)
        assert "open" in str(ticket)

    def test_defaults(self):
        user = UserFactory()
        ticket = CustomerSupportTicket.objects.create(
            user=user, title="Test", message="Body"
        )
        assert ticket.status == "open"

    def test_ordering(self):
        user = UserFactory()
        t1 = CustomerSupportTicket.objects.create(user=user, title="First", message="m")
        t2 = CustomerSupportTicket.objects.create(
            user=user, title="Second", message="m"
        )
        tickets = list(CustomerSupportTicket.objects.all())
        assert tickets[0] == t2  # newest first

    def test_cascade_delete(self):
        user = UserFactory()
        CustomerSupportTicket.objects.create(user=user, title="T", message="m")
        user.delete()
        assert CustomerSupportTicket.objects.count() == 0
