"""
Integration tests for workspace app API endpoints.

US-060: Tests for workspace API endpoints with focus on:
- POST /workspace/users                     (create user — public)
- DELETE /workspace/users/{user_id}         (remove user — authenticated)
- GET  /workspace/users/me/                 (get current user — authenticated)
- PATCH /workspace/users/{user_id}          (modify user — authenticated)
- POST /workspace/password/request-otp      (public)
- POST /workspace/password/verify-otp-only  (public)
- POST /workspace/password/verify-otp       (public)

Covers:
- Authentication and authorization
- User creation, retrieval, modification, deletion
- Password reset OTP flow
- Error cases
"""

import json
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

_P = "/api/v1/workspace"


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


# =============================================================================
# HELPERS
# =============================================================================


def _setup_user():
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _auth_client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


# =============================================================================
# AUTHENTICATION TESTS
# =============================================================================


class TestWorkspaceAuthentication:
    """Verify auth on authenticated workspace endpoints."""

    AUTHENTICATED_ENDPOINTS = [
        ("get", f"{_P}/users/me/"),
        ("delete", f"{_P}/users/1"),
        ("patch", f"{_P}/users/1"),
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
            client = _auth_client("invalid-token")
            resp = self._make_request(client, method, path)
            assert resp.status_code == 401, (
                f"{method.upper()} {path} expected 401, got {resp.status_code}"
            )


# =============================================================================
# PUBLIC ENDPOINTS (NO AUTH REQUIRED)
# =============================================================================


class TestPublicEndpoints:
    """Verify that public endpoints don't require auth."""

    def test_create_user_no_auth_required(self):
        resp = Client().post(
            f"{_P}/users",
            data=json.dumps(
                {
                    "user_name": "Test User",
                    "user_email": "newuser@example.com",
                    "password": "StrongPass123!",
                }
            ),
            content_type="application/json",
        )
        # Should not be 401 — this is a public endpoint
        assert resp.status_code != 401

    def test_request_otp_no_auth_required(self):
        resp = Client().post(
            f"{_P}/password/request-otp",
            data=json.dumps({"email": "test@example.com"}),
            content_type="application/json",
        )
        assert resp.status_code != 401

    def test_verify_otp_only_no_auth_required(self):
        resp = Client().post(
            f"{_P}/password/verify-otp-only",
            data=json.dumps({"email": "test@example.com", "otp": "123456"}),
            content_type="application/json",
        )
        assert resp.status_code != 401

    def test_verify_otp_reset_no_auth_required(self):
        resp = Client().post(
            f"{_P}/password/verify-otp",
            data=json.dumps(
                {
                    "email": "test@example.com",
                    "otp": "123456",
                    "new_password": "NewPass123!",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code != 401


# =============================================================================
# USER CREATION
# =============================================================================


class TestCreateUser:
    """Test POST /workspace/users."""

    def test_create_user_success(self):
        from apps.billing.models import SubscriptionPlan

        SubscriptionPlan.objects.create(
            name="Free", tier="free", price=0, is_active=True
        )

        resp = Client().post(
            f"{_P}/users",
            data=json.dumps(
                {
                    "user_name": "New User",
                    "user_email": "brand_new@example.com",
                    "password": "SecureP@ss1",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["message"] == "User created successfully"

    def test_create_duplicate_user(self):
        from apps.users.models import User

        User.objects.create_user(
            email="dup@example.com", password="pass123", name="Dup"
        )

        resp = Client().post(
            f"{_P}/users",
            data=json.dumps(
                {
                    "user_name": "Dup",
                    "user_email": "dup@example.com",
                    "password": "SecureP@ss1",
                }
            ),
            content_type="application/json",
        )
        # Should fail — duplicate email
        assert resp.status_code in (400, 409, 422, 500)


# =============================================================================
# GET CURRENT USER
# =============================================================================


class TestGetCurrentUser:
    """Test GET /workspace/users/me/."""

    def test_returns_current_user(self):
        user, token = _setup_user()
        resp = _auth_client(token).get(f"{_P}/users/me/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == user.email

    def test_unauthenticated_returns_401(self):
        resp = Client().get(f"{_P}/users/me/")
        assert resp.status_code == 401


# =============================================================================
# MODIFY USER
# =============================================================================


class TestModifyUser:
    """Test PATCH /workspace/users/{user_id}."""

    def test_modify_own_user(self):
        user, token = _setup_user()
        resp = _auth_client(token).patch(
            f"{_P}/users/{user.id}",
            data=json.dumps({"user_name": "Updated Name"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "User updated successfully"


# =============================================================================
# REMOVE USER
# =============================================================================


class TestRemoveUser:
    """Test DELETE /workspace/users/{user_id}."""

    def test_remove_own_user(self):
        user, token = _setup_user()
        resp = _auth_client(token).delete(f"{_P}/users/{user.id}")
        assert resp.status_code == 200
        assert resp.json()["message"] == "User removed successfully"


# =============================================================================
# PASSWORD RESET OTP FLOW
# =============================================================================


class TestPasswordResetOTP:
    """Test password reset OTP endpoints."""

    @patch(
        "apps.workspace.services.workspace.WorkspaceService.request_password_reset_otp"
    )
    def test_request_otp(self, mock_otp):
        mock_otp.return_value = (True, "OTP sent")
        resp = Client().post(
            f"{_P}/password/request-otp",
            data=json.dumps({"email": "user@example.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    @patch(
        "apps.workspace.services.workspace.WorkspaceService.request_password_reset_otp"
    )
    def test_request_otp_nonexistent_email_still_succeeds(self, mock_otp):
        """Should return success even for non-existent emails to prevent enumeration."""
        mock_otp.return_value = (True, "OTP sent")
        resp = Client().post(
            f"{_P}/password/request-otp",
            data=json.dumps({"email": "nonexistent@example.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 200

    @patch("apps.workspace.services.workspace.WorkspaceService.verify_otp")
    def test_verify_otp_only(self, mock_verify):
        mock_verify.return_value = (True, "OTP valid")
        resp = Client().post(
            f"{_P}/password/verify-otp-only",
            data=json.dumps({"email": "user@example.com", "otp": "123456"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch(
        "apps.workspace.services.workspace.WorkspaceService.verify_otp_and_reset_password"
    )
    def test_verify_otp_and_reset(self, mock_reset):
        mock_reset.return_value = (True, "Password reset")
        resp = Client().post(
            f"{_P}/password/verify-otp",
            data=json.dumps(
                {
                    "email": "user@example.com",
                    "otp": "123456",
                    "new_password": "NewSecure123!",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("apps.workspace.services.workspace.WorkspaceService.verify_otp")
    def test_verify_otp_invalid(self, mock_verify):
        mock_verify.return_value = (False, "Invalid OTP")
        resp = Client().post(
            f"{_P}/password/verify-otp-only",
            data=json.dumps({"email": "user@example.com", "otp": "000000"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
