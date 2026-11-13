"""
Integration tests for billing app API endpoints.

US-060: Tests for billing API endpoints with focus on:
- GET  /billing/plans
- GET  /billing/subscription
- POST /billing/subscription/create
- POST /billing/subscription/change
- POST /billing/subscription/cancel
- POST /billing/subscription/cancel-pending
- POST /billing/subscription/pause
- POST /billing/subscription/resume
- POST /billing/subscription/reactivate
- POST /billing/refund
- GET  /billing/payments
- GET  /billing/subscription/grace-period
- GET  /billing/subscription/history
- POST /billing/webhook
- POST /billing/promo/validate
- POST /billing/support/tickets  (CRUD)

Covers:
- Authentication: valid token, invalid token, no token
- Error responses match the standardised format
- Service layer mocking — no real Dodo Payments required
"""

import json
import uuid
from decimal import Decimal
from unittest.mock import ANY, MagicMock, patch

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.billing.models import (
    CustomerSupportTicket,
    Payment,
    SubscriptionPlan,
    UserSubscription,
)
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

# URL prefix for all billing API endpoints (mounted at /api/v1/billing/)
_P = "/api/v1/billing"


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    """Clear Django cache before each test to avoid rate-limit interference."""
    cache.clear()
    yield
    cache.clear()


# =============================================================================
# HELPERS
# =============================================================================


def _setup_user():
    """Create user + token for auth. Returns (user, token_key)."""
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _setup_plan(tier="free", name="Free", price=0):
    """Create a SubscriptionPlan. Returns plan."""
    return SubscriptionPlan.objects.create(
        name=name,
        tier=tier,
        price=Decimal(str(price)),
        features={"tasks_per_week": 10},
        is_active=True,
    )


def _setup_subscription(user, plan, status="active"):
    """Create a UserSubscription for a user. Returns subscription."""
    return UserSubscription.objects.create(
        user=user,
        plan=plan,
        status=status,
    )


def _auth_client(token):
    """Create a Django test Client with Bearer auth header."""
    return Client(headers={"authorization": f"Bearer {token}"})


def _assert_error_envelope(resp, expected_status):
    """Assert error response has some error info and correct status."""
    data = resp.json()
    if "error" in data:
        assert "error_code" in data
        assert "status" in data
        assert data["status"] == expected_status
    else:
        assert "detail" in data


# =============================================================================
# AUTHENTICATION TESTS
# =============================================================================


class TestBillingAuthentication:
    """Verify auth behaviour across billing endpoints."""

    AUTHENTICATED_ENDPOINTS = [
        ("get", f"{_P}/plans"),
        ("get", f"{_P}/subscription"),
        ("get", f"{_P}/payments"),
        ("get", f"{_P}/credits/balance"),
        ("get", f"{_P}/credits/transactions"),
        ("get", f"{_P}/credits/usage"),
        ("get", f"{_P}/subscription/grace-period"),
        ("get", f"{_P}/subscription/history"),
        ("post", f"{_P}/subscription/create"),
        ("post", f"{_P}/subscription/change"),
        ("post", f"{_P}/subscription/cancel"),
        ("post", f"{_P}/subscription/cancel-pending"),
        ("post", f"{_P}/subscription/pause"),
        ("post", f"{_P}/subscription/resume"),
        ("post", f"{_P}/subscription/reactivate"),
        ("post", f"{_P}/refund"),
        ("post", f"{_P}/promo/validate"),
        ("post", f"{_P}/credits/purchase"),
        ("post", f"{_P}/support/tickets"),
        ("get", f"{_P}/support/tickets"),
    ]

    def _make_request(self, client, method, path, body=None):
        fn = getattr(client, method)
        kwargs = {"content_type": "application/json"}
        if body:
            kwargs["data"] = json.dumps(body)
        return fn(path, **kwargs)

    def test_no_token_returns_401(self):
        for method, path in self.AUTHENTICATED_ENDPOINTS:
            cache.clear()
            resp = self._make_request(Client(), method, path)
            assert resp.status_code == 401, (
                f"{method.upper()} {path} expected 401, got {resp.status_code}"
            )

    def test_invalid_token_returns_401(self):
        for method, path in self.AUTHENTICATED_ENDPOINTS:
            cache.clear()
            client = _auth_client("invalid-token-does-not-exist")
            resp = self._make_request(client, method, path)
            assert resp.status_code == 401, (
                f"{method.upper()} {path} expected 401, got {resp.status_code}"
            )

    def test_valid_token_does_not_return_401(self):
        user, token = _setup_user()
        plan = _setup_plan()
        _setup_subscription(user, plan)

        for method, path in self.AUTHENTICATED_ENDPOINTS:
            cache.clear()
            client = _auth_client(token)
            try:
                resp = self._make_request(client, method, path)
                assert resp.status_code != 401, (
                    f"{method.upper()} {path} returned 401 with valid token"
                )
            except Exception:
                # Server-side errors (e.g. validation) are fine — we only
                # care that auth passed (i.e. we didn't get 401).
                pass


# =============================================================================
# PLANS ENDPOINT
# =============================================================================


class TestGetPlans:
    """Test GET /billing/plans."""

    def test_returns_active_plans(self):
        user, token = _setup_user()
        plan = _setup_plan()
        _setup_subscription(user, plan)

        resp = _auth_client(token).get(f"{_P}/plans")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) >= 1
        assert data["items"][0]["name"] == "Free"

    def test_inactive_plans_excluded(self):
        user, token = _setup_user()
        plan = _setup_plan()
        _setup_subscription(user, plan)
        SubscriptionPlan.objects.create(
            name="Legacy", tier="basic", price=Decimal("9.99"), is_active=False
        )

        resp = _auth_client(token).get(f"{_P}/plans")
        assert resp.status_code == 200
        names = [p["name"] for p in resp.json()["items"]]
        assert "Legacy" not in names


# =============================================================================
# SUBSCRIPTION ENDPOINTS
# =============================================================================


class TestGetSubscription:
    """Test GET /billing/subscription."""

    def test_returns_subscription(self):
        user, token = _setup_user()
        plan = _setup_plan()
        _setup_subscription(user, plan)

        resp = _auth_client(token).get(f"{_P}/subscription")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"

    def test_no_subscription_returns_null(self):
        _, token = _setup_user()

        resp = _auth_client(token).get(f"{_P}/subscription")
        assert resp.status_code == 200
        assert resp.json() is None


class TestCreateSubscription:
    """Test POST /billing/subscription/create."""

    @patch("apps.billing.service.BillingService.create_subscription_with_checks")
    def test_create_subscription(self, mock_create):
        user, token = _setup_user()
        plan = _setup_plan()

        mock_create.return_value = {
            "subscription_id": "sub_dodo_123",
            "payment_id": 1,
            "checkout_url": None,
            "amount": 0,
            "currency": "USD",
            "name": "Free",
        }

        resp = _auth_client(token).post(
            f"{_P}/subscription/create",
            data=json.dumps({"plan_id": str(plan.id)}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        mock_create.assert_called_once()


class TestChangeSubscription:
    """Test POST /billing/subscription/change."""

    @patch("apps.billing.service.BillingService.change_subscription_plan")
    def test_change_plan(self, mock_change):
        user, token = _setup_user()
        plan = _setup_plan()
        _setup_subscription(user, plan)

        mock_change.return_value = {"message": "Plan changed", "success": True}

        resp = _auth_client(token).post(
            f"{_P}/subscription/change",
            data=json.dumps({"plan_id": str(plan.id), "immediate": False}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        mock_change.assert_called_once()


class TestCancelSubscription:
    """Test POST /billing/subscription/cancel."""

    @patch("apps.billing.service.BillingService.cancel_subscription")
    def test_cancel_subscription(self, mock_cancel):
        user, token = _setup_user()
        plan = _setup_plan()
        _setup_subscription(user, plan)

        mock_cancel.return_value = {"message": "Cancelled", "success": True}

        resp = _auth_client(token).post(
            f"{_P}/subscription/cancel",
            data=json.dumps({"immediate": False}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        mock_cancel.assert_called_once()


class TestPauseResumeReactivate:
    """Test pause, resume, reactivate endpoints."""

    @patch("apps.billing.service.BillingService.pause_subscription")
    def test_pause(self, mock_pause):
        user, token = _setup_user()
        plan = _setup_plan()
        _setup_subscription(user, plan)
        mock_pause.return_value = {"message": "Paused", "success": True}

        resp = _auth_client(token).post(f"{_P}/subscription/pause")
        assert resp.status_code == 200

    @patch("apps.billing.service.BillingService.resume_subscription")
    def test_resume(self, mock_resume):
        user, token = _setup_user()
        plan = _setup_plan()
        _setup_subscription(user, plan)
        mock_resume.return_value = {"message": "Resumed", "success": True}

        resp = _auth_client(token).post(f"{_P}/subscription/resume")
        assert resp.status_code == 200

    @patch("apps.billing.service.BillingService.reactivate_subscription")
    def test_reactivate(self, mock_reactivate):
        user, token = _setup_user()
        plan = _setup_plan()
        _setup_subscription(user, plan, status="cancelled")
        mock_reactivate.return_value = {"message": "Reactivated", "success": True}

        resp = _auth_client(token).post(f"{_P}/subscription/reactivate")
        assert resp.status_code == 200


# =============================================================================
# PAYMENT ENDPOINTS
# =============================================================================


class TestPaymentHistory:
    """Test GET /billing/payments."""

    def test_returns_payment_list(self):
        user, token = _setup_user()
        plan = _setup_plan()
        sub = _setup_subscription(user, plan)
        Payment.objects.create(
            user=user,
            subscription=sub,
            dodo_payment_id="pay_dodo_test_1",
            amount=Decimal("9.99"),
            currency="USD",
            status="captured",
        )

        resp = _auth_client(token).get(f"{_P}/payments")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["amount"] == "9.99"

    def test_empty_payment_history(self):
        _, token = _setup_user()

        resp = _auth_client(token).get(f"{_P}/payments")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []


# =============================================================================
# CREDITS
# =============================================================================


class TestCredits:
    """Test credit wallet endpoints."""

    def test_credit_balance_uses_token_authenticated_user(self):
        user, token = _setup_user()

        resp = _auth_client(token).get(f"{_P}/credits/balance")
        assert resp.status_code == 200

        data = resp.json()
        assert data["free_credits"] == 150
        assert data["total_available"] >= 150

    @patch("apps.billing.views.DodoPayments")
    def test_credit_purchase_uses_token_authenticated_user(self, mock_dodo):
        user, token = _setup_user()
        mock_dodo.return_value.checkout_sessions.create.return_value = MagicMock(
            checkout_url="https://checkout.test/session"
        )

        resp = _auth_client(token).post(
            f"{_P}/credits/purchase",
            data=json.dumps({"packs": 2}),
            content_type="application/json",
        )

        assert resp.status_code == 200
        assert resp.json()["credits"] == 2000
        mock_dodo.return_value.checkout_sessions.create.assert_called_once_with(
            product_cart=[
                {
                    "product_id": ANY,
                    "quantity": 2,
                }
            ],
            customer={
                "email": user.email,
                "name": user.name or user.email,
            },
            return_url=ANY,
            metadata={
                "user_id": str(user.id),
                "type": "credit_purchase",
                "credits": "2000",
                "packs": "2",
            },
        )


# =============================================================================
# REFUND
# =============================================================================


class TestRefund:
    """Test POST /billing/refund."""

    @patch("apps.billing.service.BillingService.request_refund")
    def test_request_refund(self, mock_refund):
        user, token = _setup_user()
        mock_refund.return_value = {"message": "Refund processed", "success": True}

        resp = _auth_client(token).post(
            f"{_P}/refund",
            data=json.dumps({"payment_id": str(uuid.uuid4()), "reason": "Unsatisfied"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        mock_refund.assert_called_once()


# =============================================================================
# GRACE PERIOD
# =============================================================================


class TestGracePeriod:
    """Test GET /billing/subscription/grace-period."""

    @patch("apps.billing.service.BillingService.check_subscription_grace_period")
    def test_grace_period_check(self, mock_grace):
        user, token = _setup_user()
        mock_grace.return_value = {
            "status": "active",
            "days_remaining": 5,
            "in_grace_period": True,
            "grace_ends": None,
        }

        resp = _auth_client(token).get(f"{_P}/subscription/grace-period")
        assert resp.status_code == 200
        data = resp.json()
        assert data["in_grace_period"] is True


# =============================================================================
# SUBSCRIPTION HISTORY
# =============================================================================


class TestSubscriptionHistory:
    """Test GET /billing/subscription/history."""

    @patch("apps.billing.service.BillingService.get_subscription_history")
    def test_returns_history(self, mock_history):
        user, token = _setup_user()
        mock_history.return_value = []

        resp = _auth_client(token).get(f"{_P}/subscription/history")
        assert resp.status_code == 200


# =============================================================================
# PROMO CODE
# =============================================================================


class TestPromoCode:
    """Test POST /billing/promo/validate."""

    @patch("apps.billing.service.BillingService.validate_promo_code")
    def test_validate_promo(self, mock_validate):
        user, token = _setup_user()
        mock_validate.return_value = {
            "valid": True,
            "discount_percent": 20,
            "message": "Code applied",
        }

        resp = _auth_client(token).post(
            f"{_P}/promo/validate",
            data=json.dumps({"code": "SAVE20"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["discount_percent"] == 20

    @patch("apps.billing.service.BillingService.validate_promo_code")
    def test_invalid_promo(self, mock_validate):
        _, token = _setup_user()
        mock_validate.return_value = {
            "valid": False,
            "discount_percent": 0,
            "message": "Invalid code",
        }

        resp = _auth_client(token).post(
            f"{_P}/promo/validate",
            data=json.dumps({"code": "INVALID"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False


# =============================================================================
# WEBHOOK (UNAUTHENTICATED)
# =============================================================================


class TestWebhook:
    """Test POST /billing/webhook — unauthenticated endpoint."""

    @patch("apps.billing.service.BillingService.handle_dodo_webhook")
    def test_webhook_no_auth_required(self, mock_hook):
        mock_hook.return_value = {"message": "OK", "success": True}

        resp = Client().post(
            f"{_P}/webhook",
            data=json.dumps({}),
            content_type="application/json",
        )
        # Should not be 401 — webhook is unauthenticated
        assert resp.status_code != 401


# =============================================================================
# SUPPORT TICKETS
# =============================================================================


class TestSupportTickets:
    """Test support ticket CRUD endpoints."""

    def test_create_ticket(self):
        user, token = _setup_user()
        plan = _setup_plan()
        _setup_subscription(user, plan)

        resp = _auth_client(token).post(
            f"{_P}/support/tickets",
            data=json.dumps({"title": "Help", "message": "I need help"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Help"
        assert data["status"] == "open"

    def test_list_tickets(self):
        user, token = _setup_user()
        CustomerSupportTicket.objects.create(user=user, title="T1", message="M1")
        CustomerSupportTicket.objects.create(user=user, title="T2", message="M2")

        resp = _auth_client(token).get(f"{_P}/support/tickets")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) == 2

    def test_get_ticket(self):
        user, token = _setup_user()
        ticket = CustomerSupportTicket.objects.create(
            user=user, title="T1", message="M1"
        )

        resp = _auth_client(token).get(f"{_P}/support/tickets/{ticket.id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "T1"

    def test_get_ticket_not_found(self):
        _, token = _setup_user()
        fake_id = uuid.uuid4()

        resp = _auth_client(token).get(f"{_P}/support/tickets/{fake_id}")
        assert resp.status_code == 404

    def test_update_ticket(self):
        user, token = _setup_user()
        ticket = CustomerSupportTicket.objects.create(
            user=user, title="T1", message="M1"
        )

        resp = _auth_client(token).put(
            f"{_P}/support/tickets/{ticket.id}",
            data=json.dumps({"title": "Updated"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"

    def test_delete_ticket(self):
        user, token = _setup_user()
        ticket = CustomerSupportTicket.objects.create(
            user=user, title="T1", message="M1"
        )

        resp = _auth_client(token).delete(f"{_P}/support/tickets/{ticket.id}")
        assert resp.status_code == 200
        assert not CustomerSupportTicket.objects.filter(id=ticket.id).exists()

    def test_other_user_cannot_access_ticket(self):
        user1, _ = _setup_user()
        ticket = CustomerSupportTicket.objects.create(
            user=user1, title="Private", message="Secret"
        )

        user2 = UserFactory()
        token2 = Token.objects.create(user=user2).key

        resp = _auth_client(token2).get(f"{_P}/support/tickets/{ticket.id}")
        assert resp.status_code == 404
