"""Tests for GDPR compliance API endpoints — export and delete."""

import json

import pytest
from django.test import RequestFactory

from apps.billing.models import (
    CreditWallet,
    Payment,
    SubscriptionPlan,
    UserSubscription,
)
from apps.compliance.models import AuditAction, AuditLog
from apps.spaces.models import Project
from apps.storage.models import (
    AgentRun,
    Conversation,
    StoredFile,
    SystemWideMemory,
)
from apps.users.models import DeveloperAPIKey, User, UserSettings
from apps.users.tests.factories import UserFactory

# Django Ninja's test client does not exist out of the box for our auth adapter.
# Instead, we call the endpoint views directly with a mocked request.


@pytest.fixture
def rf():
    return RequestFactory()


def _authed_request(rf, method, path, user, body=None, **kwargs):
    """Build a request and attach the auth user (simulates NinjaAuthAdapter)."""
    factory_method = getattr(rf, method)
    if body is not None:
        request = factory_method(
            path,
            data=json.dumps(body),
            content_type="application/json",
            **kwargs,
        )
    else:
        request = factory_method(path, **kwargs)
    request.auth = user
    request.request_id = "test-req-id"
    return request


def _make_user_with_data():
    """Create a user with associated data across FK relationships."""
    user = UserFactory()
    user.settings.theme = "dark"
    user.settings.save()
    raw_key = DeveloperAPIKey.generate_key()
    DeveloperAPIKey.objects.create(
        name="test-key",
        key_hash=DeveloperAPIKey.hash_key(raw_key),
        key_prefix=raw_key[:8],
        user=user,
    )
    Project.objects.create(title="My Project", description="desc", user=user)
    conv = Conversation.objects.create(user=user, title="Test chat")
    AgentRun.objects.create(
        conversation=conv, user=user, task="Hello", status="completed"
    )
    StoredFile.objects.create(
        owner=user, name="f.txt", size=100, mime_type="text/plain"
    )
    SystemWideMemory.objects.create(user=user, memory_summary="mem")
    # Billing — signal auto-provisions CreditWallet on subscription create
    plan, _ = SubscriptionPlan.objects.get_or_create(
        tier="premium",
        defaults={"name": "Pro", "price": 20, "features": {}, "monthly_credits": 500},
    )
    sub = UserSubscription.objects.create(user=user, plan=plan, status="active")
    Payment.objects.create(user=user, subscription=sub, amount=20)
    wallet = CreditWallet.objects.get(user=user)
    wallet.free_credits = 100
    wallet.save()
    return user


# ── Export Endpoint ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestGDPRExportEndpoint:
    def test_export_returns_200_with_data(self, rf):
        user = _make_user_with_data()
        request = _authed_request(rf, "get", "/api/v1/compliance/users/me/export", user)

        from apps.compliance.api import gdpr_export

        response = gdpr_export(request)
        assert isinstance(response, dict)
        assert response["user_id"] == str(user.id)
        assert response["profile"]["email"] == user.email
        assert len(response["conversations"]) == 1
        assert len(response["files"]) == 1
        assert response["billing"]["subscription"]["plan"] == "Pro"

    def test_export_creates_audit_entry(self, rf):
        user = _make_user_with_data()
        AuditLog.objects.all().delete()
        request = _authed_request(
            rf,
            "get",
            "/api/v1/compliance/users/me/export",
            user,
            HTTP_X_FORWARDED_FOR="10.0.0.1",
        )

        from apps.compliance.api import gdpr_export

        gdpr_export(request)

        entry = AuditLog.objects.filter(action=AuditAction.EXPORT).first()
        assert entry is not None
        assert entry.resource_type == "user"
        assert entry.resource_id == str(user.id)
        assert entry.actor_ip == "10.0.0.1"

    def test_export_empty_user(self, rf):
        user = UserFactory()
        UserSettings.objects.filter(user=user).delete()
        user.refresh_from_db()
        request = _authed_request(rf, "get", "/api/v1/compliance/users/me/export", user)

        from apps.compliance.api import gdpr_export

        response = gdpr_export(request)
        assert response["settings"] is None
        assert response["conversations"] == []
        assert response["billing"]["subscription"] is None

    def test_export_excludes_secrets(self, rf):
        user = _make_user_with_data()
        request = _authed_request(rf, "get", "/api/v1/compliance/users/me/export", user)

        from apps.compliance.api import gdpr_export

        data = gdpr_export(request)
        for key in data["api_keys"]:
            assert "key_hash" not in key
            assert "key" not in key


# ── Delete Endpoint ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestGDPRDeleteEndpoint:
    def test_delete_requires_confirmation(self, rf):
        user = UserFactory()

        from apps.compliance.api import DeleteAccountRequest, gdpr_delete

        request = _authed_request(
            rf,
            "delete",
            "/api/v1/compliance/users/me",
            user,
            body={"confirm": False},
        )
        body = DeleteAccountRequest(confirm=False)
        status, response = gdpr_delete(request, body)

        assert status == 400
        assert "confirm" in response["detail"].lower()

    def test_delete_succeeds_with_confirmation(self, rf):
        user = _make_user_with_data()
        user_id = user.id

        from apps.compliance.api import DeleteAccountRequest, gdpr_delete

        request = _authed_request(
            rf,
            "delete",
            "/api/v1/compliance/users/me",
            user,
            body={"confirm": True, "reason": "Moving to competitor"},
        )
        body = DeleteAccountRequest(confirm=True, reason="Moving to competitor")
        status, response = gdpr_delete(request, body)

        assert status == 200
        assert response["success"] is True
        assert not User.objects.filter(id=user_id).exists()

    def test_delete_cascades_all_data(self, rf):
        user = _make_user_with_data()
        user_id = user.id

        from apps.compliance.api import DeleteAccountRequest, gdpr_delete

        request = _authed_request(
            rf,
            "delete",
            "/api/v1/compliance/users/me",
            user,
            body={"confirm": True},
        )
        body = DeleteAccountRequest(confirm=True)
        gdpr_delete(request, body)

        assert not User.objects.filter(id=user_id).exists()
        assert Conversation.objects.filter(user_id=user_id).count() == 0
        assert Project.objects.filter(user_id=user_id).count() == 0
        assert StoredFile.objects.filter(owner_id=user_id).count() == 0
        assert UserSettings.objects.filter(user_id=user_id).count() == 0
        assert UserSubscription.objects.filter(user_id=user_id).count() == 0
        assert CreditWallet.objects.filter(user_id=user_id).count() == 0

    def test_delete_creates_audit_record(self, rf):
        user = _make_user_with_data()
        user_email = user.email
        AuditLog.objects.all().delete()

        from apps.compliance.api import DeleteAccountRequest, gdpr_delete

        request = _authed_request(
            rf,
            "delete",
            "/api/v1/compliance/users/me",
            user,
            body={"confirm": True, "reason": "GDPR request"},
            HTTP_X_FORWARDED_FOR="192.168.1.100",
        )
        body = DeleteAccountRequest(confirm=True, reason="GDPR request")
        gdpr_delete(request, body)

        # The service entry has request_id; the signal entry does not.
        entry = AuditLog.objects.filter(
            action=AuditAction.DELETE,
            resource_type="user",
            request_id="test-req-id",
        ).first()
        assert entry is not None
        assert entry.actor_email == user_email
        assert entry.actor_ip == "192.168.1.100"
        assert entry.metadata["reason"] == "GDPR request"

    def test_delete_response_includes_summary(self, rf):
        user = _make_user_with_data()

        from apps.compliance.api import DeleteAccountRequest, gdpr_delete

        request = _authed_request(
            rf,
            "delete",
            "/api/v1/compliance/users/me",
            user,
            body={"confirm": True},
        )
        body = DeleteAccountRequest(confirm=True)
        status, response = gdpr_delete(request, body)

        summary = response["summary"]
        assert summary["conversations_deleted"] == 1
        assert summary["projects_deleted"] == 1
        assert summary["files_deleted"] == 1

    def test_delete_with_ip_from_remote_addr(self, rf):
        user = UserFactory()
        AuditLog.objects.all().delete()

        from apps.compliance.api import DeleteAccountRequest, gdpr_delete

        # No X-Forwarded-For — should fall back to REMOTE_ADDR
        request = _authed_request(
            rf,
            "delete",
            "/api/v1/compliance/users/me",
            user,
            body={"confirm": True},
            REMOTE_ADDR="172.16.0.1",
        )
        body = DeleteAccountRequest(confirm=True)
        gdpr_delete(request, body)

        # Filter for the service-created entry (has request_id)
        entry = AuditLog.objects.filter(
            action=AuditAction.DELETE,
            resource_type="user",
            request_id="test-req-id",
        ).first()
        assert entry is not None
        assert entry.actor_ip == "172.16.0.1"


# ── IP Extraction Helper ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestGetClientIP:
    def test_x_forwarded_for_preferred(self, rf):
        from apps.compliance.api import _get_client_ip

        request = rf.get(
            "/", HTTP_X_FORWARDED_FOR="1.2.3.4, 5.6.7.8", REMOTE_ADDR="127.0.0.1"
        )
        assert _get_client_ip(request) == "1.2.3.4"

    def test_falls_back_to_remote_addr(self, rf):
        from apps.compliance.api import _get_client_ip

        request = rf.get("/", REMOTE_ADDR="10.0.0.1")
        assert _get_client_ip(request) == "10.0.0.1"
