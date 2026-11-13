"""Unit tests for BillingService and CustomerSupportService business logic."""

import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.billing.models import (
    CustomerSupportTicket,
    Payment,
    PromoCoupon,
    SubscriptionPlan,
    UserSubscription,
)
from apps.billing.service import (
    BillingException,
    BillingService,
    CustomerSupportService,
)
from apps.users.tests.factories import UserFactory
from config.errors.common import InvalidInputError, NotFoundError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(user):
    """Build a mock WSGIRequest with an authenticated user."""
    request = MagicMock()
    request.auth = user
    return request


def _make_service(user):
    """Return a BillingService whose _get_authenticated_user returns *user*."""
    svc = BillingService.__new__(BillingService)
    # Manually initialise base attributes without calling __init__
    # (which would instantiate a real Dodo Payments client)
    import logging

    svc._user_service = MagicMock()
    svc._cache_service = MagicMock()
    svc._logger = logging.getLogger("test.billing")
    svc._service_kwargs = {}
    svc.dodo_client = MagicMock()
    # Patch _get_authenticated_user to return our user
    svc._get_authenticated_user = MagicMock(return_value=user)
    return svc


def _make_support_service(user):
    """Return a CustomerSupportService whose _get_authenticated_user returns *user*."""
    svc = CustomerSupportService.__new__(CustomerSupportService)
    import logging

    svc._user_service = MagicMock()
    svc._cache_service = MagicMock()
    svc._logger = logging.getLogger("test.support")
    svc._service_kwargs = {}
    svc._get_authenticated_user = MagicMock(return_value=user)
    return svc


# ---------------------------------------------------------------------------
# BillingService — get_user_subscription_plan
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetUserSubscriptionPlan:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.plan = SubscriptionPlan.objects.create(
            name="Free",
            tier="free",
            price=Decimal("0.00"),
            features={
                "weekly_tasks": (10, "10 tasks"),
                "max_sandbox_time": (60, "60 min"),
                "max_addons": (2, "2 addons"),
                "max_mcp_per_task": (3, "3 MCP"),
                "max_concurrent_tasks": (1, "1 task"),
            },
        )
        UserSubscription.objects.create(user=self.user, plan=self.plan, status="active")
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_returns_subscription_with_usage(self):
        result = self.svc.get_user_subscription_plan(self.request)
        assert result is not None
        assert hasattr(result, "usage_schema")
        assert "tasks_remaining_week" in result.usage_schema
        assert "sandbox_time_remaining_month" in result.usage_schema
        assert "addons_used" in result.usage_schema
        assert "mcp_servers_added" in result.usage_schema
        assert "concurrent_tasks" in result.usage_schema

    def test_no_subscription_raises_not_found(self):
        user2 = UserFactory()
        svc2 = _make_service(user2)
        req2 = _make_request(user2)
        with pytest.raises(NotFoundError, match="no subscription"):
            svc2.get_user_subscription_plan(req2)


# ---------------------------------------------------------------------------
# BillingService — cancel_pending_subscription
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCancelPendingSubscription:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.plan = SubscriptionPlan.objects.create(
            name="Basic", tier="basic", price=Decimal("9.00"), dodo_product_id="plan_b"
        )
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_cancel_no_pending(self):
        result = self.svc.cancel_pending_subscription(self.request)
        assert result["message"] == "No pending subscription found"

    def test_cancel_no_pending_return_bool(self):
        assert (
            self.svc.cancel_pending_subscription(self.request, return_as_bool=True)
            is True
        )

    def test_cancel_pending_with_dodo(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="pending",
            dodo_subscription_id="sub_dodo_pending",
        )
        result = self.svc.cancel_pending_subscription(self.request)
        assert result["message"] == "Pending subscription cancelled"
        self.svc.dodo_client.subscriptions.update.assert_called_once()

    def test_cancel_pending_dodo_failure(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="pending",
            dodo_subscription_id="sub_dodo_fail",
        )
        self.svc.dodo_client.subscriptions.update.side_effect = Exception("network")
        with pytest.raises(BillingException, match="cancelling Dodo"):
            self.svc.cancel_pending_subscription(self.request)


# ---------------------------------------------------------------------------
# BillingService — cancel_subscription
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCancelSubscription:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.plan = SubscriptionPlan.objects.create(
            name="Pro2", tier="pro2", price=Decimal("29.00"), dodo_product_id="plan_p2"
        )
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_no_active_sub_raises(self):
        with pytest.raises(NotFoundError, match="No subscription"):
            self.svc.cancel_subscription(self.request)

    def test_no_active_sub_return_bool(self):
        assert self.svc.cancel_subscription(self.request, return_as_bool=True) is True

    def test_cancel_immediate(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            dodo_subscription_id="sub_dodo_act",
        )
        result = self.svc.cancel_subscription(self.request, immediate=True)
        assert "immediately" in result["message"]

    def test_cancel_at_cycle_end(self):
        sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            end_date=timezone.now() + timedelta(days=15),
            dodo_subscription_id="sub_dodo_end",
        )
        result = self.svc.cancel_subscription(self.request, immediate=False)
        assert "will cancel" in result["message"]
        sub.refresh_from_db()
        assert sub.auto_renew is False


# ---------------------------------------------------------------------------
# BillingService — pause / resume subscription
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPauseResumeSubscription:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.plan = SubscriptionPlan.objects.create(
            name="Pause",
            tier="pause",
            price=Decimal("10.00"),
            dodo_product_id="plan_pa",
        )
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_pause_success(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            dodo_subscription_id="sub_dodo_pa",
        )
        result = self.svc.pause_subscription(self.request)
        assert result["message"] == "Subscription paused"

    def test_pause_already_paused(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            paused=True,
            dodo_subscription_id="sub_dodo_pa2",
        )
        with pytest.raises(BillingException, match="already paused"):
            self.svc.pause_subscription(self.request)

    def test_pause_no_subscription(self):
        with pytest.raises(NotFoundError, match="No active"):
            self.svc.pause_subscription(self.request)

    def test_resume_success(self):
        sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            paused=True,
            dodo_subscription_id="sub_dodo_re",
        )
        result = self.svc.resume_subscription(self.request)
        assert result["message"] == "Subscription resumed"
        sub.refresh_from_db()
        assert sub.paused is False

    def test_resume_not_paused(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            paused=False,
        )
        with pytest.raises(BillingException, match="not paused"):
            self.svc.resume_subscription(self.request)


# ---------------------------------------------------------------------------
# BillingService — reactivate_subscription
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestReactivateSubscription:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.plan = SubscriptionPlan.objects.create(
            name="React",
            tier="react",
            price=Decimal("15.00"),
            dodo_product_id="plan_re",
        )
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_reactivate_success(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="cancelled",
            end_date=timezone.now() + timedelta(days=5),
            dodo_subscription_id="sub_dodo_reac",
        )
        result = self.svc.reactivate_subscription(self.request)
        assert result["message"] == "Subscription re-activated"

    def test_reactivate_expired_raises(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="cancelled",
            end_date=timezone.now() - timedelta(days=1),
        )
        with pytest.raises(BillingException, match="expired"):
            self.svc.reactivate_subscription(self.request)


# ---------------------------------------------------------------------------
# BillingService — change_subscription_plan
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestChangeSubscriptionPlan:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.current_plan = SubscriptionPlan.objects.create(
            name="Cur", tier="cur", price=Decimal("10.00"), dodo_product_id="plan_cur"
        )
        self.free_plan = SubscriptionPlan.objects.create(
            name="FreePlan", tier="free", price=Decimal("0.00")
        )
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_same_plan_raises(self):
        UserSubscription.objects.create(
            user=self.user, plan=self.current_plan, status="active"
        )
        with pytest.raises(BillingException, match="Already subscribed"):
            self.svc.change_subscription_plan(
                self.request, str(self.current_plan.id), immediate=True
            )

    def test_downgrade_to_free_immediate(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.current_plan,
            status="active",
            dodo_subscription_id="sub_dodo_down",
        )
        result = self.svc.change_subscription_plan(
            self.request, str(self.free_plan.id), immediate=True
        )
        assert "downgraded" in result["message"]

    def test_downgrade_to_free_deferred(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.current_plan,
            status="active",
        )
        result = self.svc.change_subscription_plan(
            self.request, str(self.free_plan.id), immediate=False
        )
        assert "period end" in result["message"]


# ---------------------------------------------------------------------------
# BillingService — request_refund
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRequestRefund:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.plan = SubscriptionPlan.objects.create(
            name="Ref", tier="ref", price=Decimal("20.00")
        )
        self.sub = UserSubscription.objects.create(
            user=self.user, plan=self.plan, status="active"
        )
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_refund_success(self):
        Payment.objects.create(
            user=self.user,
            subscription=self.sub,
            dodo_payment_id="pay_dodo_ref",
            amount=Decimal("20.00"),
            status="captured",
        )
        mock_refund = MagicMock()
        mock_refund.refund_id = "refund_dodo_123"
        self.svc.dodo_client.refunds.create.return_value = mock_refund
        result = self.svc.request_refund(self.request, "pay_dodo_ref")
        assert result["refund_id"] == "refund_dodo_123"

    def test_refund_already_refunded(self):
        Payment.objects.create(
            user=self.user,
            subscription=self.sub,
            dodo_payment_id="pay_dodo_refd",
            amount=Decimal("20.00"),
            status="refunded",
        )
        result = self.svc.request_refund(self.request, "pay_dodo_refd")
        assert "Already refunded" in result["message"]

    def test_refund_no_payment(self):
        with pytest.raises(BillingException, match="does not exist"):
            self.svc.request_refund(self.request, "pay_missing")


# ---------------------------------------------------------------------------
# BillingService — retry_failed_payment
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRetryFailedPayment:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.plan = SubscriptionPlan.objects.create(
            name="Retry", tier="retry", price=Decimal("15.00")
        )
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_no_subscription(self):
        with pytest.raises(NotFoundError):
            self.svc.retry_failed_payment(self.request)

    def test_no_dodo_id(self):
        UserSubscription.objects.create(user=self.user, plan=self.plan, status="active")
        with pytest.raises(NotFoundError, match="No subscription"):
            self.svc.retry_failed_payment(self.request)

    def test_retry_success(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            dodo_subscription_id="sub_dodo_retry2",
        )
        mock_result = MagicMock()
        mock_result.checkout_url = "https://checkout.dodopayments.com/retry"
        self.svc.dodo_client.subscriptions.update_payment_method.return_value = (
            mock_result
        )
        result = self.svc.retry_failed_payment(self.request)
        assert "checkout_url" in result or "message" in result


# ---------------------------------------------------------------------------
# BillingService — get_subscription_plans / get_payment_history
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSimpleBillingMethods:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_get_subscription_plans(self):
        SubscriptionPlan.objects.create(
            name="A", tier="a_tier", price=Decimal("5.00"), is_active=True
        )
        SubscriptionPlan.objects.create(
            name="B", tier="b_tier", price=Decimal("10.00"), is_active=False
        )
        plans = self.svc.get_subscription_plans()
        names = [p.name for p in plans]
        assert "A" in names
        assert "B" not in names

    def test_get_payment_history(self):
        plan = SubscriptionPlan.objects.create(
            name="PH", tier="ph_tier", price=Decimal("5.00")
        )
        sub = UserSubscription.objects.create(
            user=self.user, plan=plan, status="active"
        )
        Payment.objects.create(
            user=self.user, subscription=sub, amount=Decimal("5.00"), status="captured"
        )
        payments = self.svc.get_payment_history(self.request)
        assert payments.count() == 1


# ---------------------------------------------------------------------------
# BillingService — validate_promo_code
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestValidatePromoCode:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        now = timezone.now()
        self.coupon = PromoCoupon.objects.create(
            code="SAVE20",
            discount_type="percentage",
            discount_value=Decimal("20.00"),
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=30),
            is_active=True,
            max_uses=100,
            used_count=0,
        )

    def test_valid_code(self):
        result = self.svc.validate_promo_code("SAVE20")
        assert result["valid"] is True
        assert result["discount_percent"] == 20

    def test_invalid_code(self):
        result = self.svc.validate_promo_code("NOPE")
        assert result["valid"] is False

    def test_expired_code(self):
        self.coupon.valid_until = timezone.now() - timedelta(days=1)
        self.coupon.save()
        result = self.svc.validate_promo_code("SAVE20")
        assert result["valid"] is False
        assert "expired" in result["message"]

    def test_inactive_code(self):
        self.coupon.is_active = False
        self.coupon.save()
        result = self.svc.validate_promo_code("SAVE20")
        assert result["valid"] is False

    def test_max_uses_reached(self):
        self.coupon.max_uses = 5
        self.coupon.used_count = 5
        self.coupon.save()
        result = self.svc.validate_promo_code("SAVE20")
        assert result["valid"] is False
        assert "usage limit" in result["message"]


# ---------------------------------------------------------------------------
# BillingService — webhook handlers
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestWebhookHandlers:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.plan = SubscriptionPlan.objects.create(
            name="WH", tier="wh", price=Decimal("10.00")
        )
        self.svc = _make_service(self.user)

    def test_handle_sub_active(self):
        sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="pending",
            dodo_subscription_id="sub_dodo_wh1",
        )
        self.svc._handle_sub_active(
            {"subscription_id": "sub_dodo_wh1", "payment_id": "pay_dodo_wh1"}
        )
        sub.refresh_from_db()
        assert sub.status == "active"

    def test_handle_sub_cancelled(self):
        sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            dodo_subscription_id="sub_dodo_wh2",
        )
        self.svc._handle_sub_cancelled({"subscription_id": "sub_dodo_wh2"})
        sub.refresh_from_db()
        assert sub.status == "cancelled"

    def test_handle_sub_expired(self):
        SubscriptionPlan.objects.create(name="Free", tier="free", price=Decimal("0"))
        sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            dodo_subscription_id="sub_dodo_wh3",
        )
        self.svc._handle_sub_expired({"subscription_id": "sub_dodo_wh3"})
        sub.refresh_from_db()
        assert sub.status == "active"  # downgraded to free, status reset to active
        assert sub.plan.tier == "free"

    def test_handle_payment_failed(self):
        sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            dodo_subscription_id="sub_dodo_wh4",
        )
        self.svc._handle_payment_failed(
            {"payment_id": "pay_fail_1", "subscription_id": "sub_dodo_wh4"}
        )
        from apps.billing.models import FailedPayment

        assert FailedPayment.objects.filter(subscription=sub).count() == 1

    def test_handle_refund_succeeded(self):
        sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            dodo_subscription_id="sub_dodo_wh6",
        )
        pay = Payment.objects.create(
            user=self.user,
            subscription=sub,
            dodo_payment_id="pay_dodo_wh6",
            amount=Decimal("10.00"),
            status="captured",
        )
        self.svc._handle_refund_succeeded(
            {"payment_id": "pay_dodo_wh6", "refund_id": "ref_dodo_1"}
        )
        pay.refresh_from_db()
        assert pay.status == "refunded"
        assert pay.dodo_refund_id == "ref_dodo_1"

    def test_handle_refund_succeeded_missing_payment(self):
        # Should not raise — just logs a warning
        self.svc._handle_refund_succeeded(
            {"payment_id": "nonexistent", "refund_id": "ref_x"}
        )

    def test_handle_payment_succeeded(self):
        sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            dodo_subscription_id="sub_dodo_chg",
        )
        pay = Payment.objects.create(
            user=self.user,
            subscription=sub,
            dodo_payment_id="pay_dodo_chg",
            amount=Decimal("10.00"),
            status="created",
        )
        self.svc._handle_payment_succeeded(
            {"payment_id": "pay_dodo_chg", "metadata": {}}
        )
        pay.refresh_from_db()
        assert pay.status == "captured"


# ---------------------------------------------------------------------------
# BillingService — check_subscription_grace_period
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCheckGracePeriod:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.plan = SubscriptionPlan.objects.create(
            name="GP", tier="gp", price=Decimal("10.00")
        )
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_no_subscription(self):
        with pytest.raises(NotFoundError):
            self.svc.check_subscription_grace_period(self.request)

    def test_active_with_end_date(self):
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status="active",
            end_date=timezone.now() + timedelta(days=10),
        )
        result = self.svc.check_subscription_grace_period(self.request)
        assert result["status"] == "active"
        assert result["days_remaining"] > 0
        assert result["in_grace_period"] is False

    def test_no_end_date(self):
        UserSubscription.objects.create(user=self.user, plan=self.plan, status="active")
        result = self.svc.check_subscription_grace_period(self.request)
        assert result["days_remaining"] is None


# ---------------------------------------------------------------------------
# BillingService — _map_and_log_error
# ---------------------------------------------------------------------------
class TestBillingErrorMapping:
    def setup_method(self):
        self.svc = _make_service(MagicMock())

    def test_known_exceptions_passthrough(self):
        e = BillingException("test")
        result = self.svc._map_and_log_error(e, "ctx")
        assert result is e

    def test_validation_error_maps_to_input(self):
        from django.core.exceptions import ValidationError

        e = ValidationError("bad field")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, InvalidInputError)

    def test_unexpected_error_maps_to_billing(self):
        e = RuntimeError("boom")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, BillingException)


# ---------------------------------------------------------------------------
# CustomerSupportService
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCustomerSupportService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_support_service(self.user)
        self.request = _make_request(self.user)

    def test_create_ticket(self):
        ticket = self.svc.create_ticket(self.request, "Bug", "Something broke")
        assert ticket.title == "Bug"
        assert ticket.status == "open"

    def test_get_ticket(self):
        ticket = CustomerSupportTicket.objects.create(
            user=self.user, title="T1", message="M1", status="open"
        )
        result = self.svc.get_ticket(self.request, str(ticket.id))
        assert result.id == ticket.id

    def test_get_ticket_not_found(self):
        fake_id = str(uuid.uuid4())
        with pytest.raises(NotFoundError):
            self.svc.get_ticket(self.request, fake_id)

    def test_list_tickets(self):
        CustomerSupportTicket.objects.create(
            user=self.user, title="T1", message="M1", status="open"
        )
        CustomerSupportTicket.objects.create(
            user=self.user, title="T2", message="M2", status="open"
        )
        tickets = self.svc.list_tickets(self.request)
        assert tickets.count() == 2

    def test_update_ticket(self):
        ticket = CustomerSupportTicket.objects.create(
            user=self.user, title="T1", message="M1", status="open"
        )
        updated = self.svc.update_ticket(
            self.request, str(ticket.id), title="Updated", status="resolved"
        )
        assert updated.title == "Updated"
        assert updated.status == "resolved"

    def test_update_ticket_invalid_status(self):
        ticket = CustomerSupportTicket.objects.create(
            user=self.user, title="T1", message="M1", status="open"
        )
        with pytest.raises(InvalidInputError, match="Invalid status"):
            self.svc.update_ticket(self.request, str(ticket.id), status="bad_status")

    def test_delete_ticket(self):
        ticket = CustomerSupportTicket.objects.create(
            user=self.user, title="T1", message="M1", status="open"
        )
        result = self.svc.delete_ticket(self.request, str(ticket.id))
        assert "deleted" in result["message"]
        assert CustomerSupportTicket.objects.filter(id=ticket.id).count() == 0
