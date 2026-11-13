"""Tests for consent API endpoints — current, update, history."""

import json

import pytest
from django.test import RequestFactory

from apps.compliance.api import ConsentRequest
from apps.compliance.models import AuditAction, AuditLog, ConsentType
from apps.compliance.services import grant_consent
from apps.users.models import UserSettings
from apps.users.tests.factories import UserFactory


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


# ── GET /consent ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestConsentCurrentEndpoint:
    def test_returns_all_types(self, rf):
        user = UserFactory()
        request = _authed_request(rf, "get", "/api/v1/compliance/consent", user)

        from apps.compliance.api import consent_current

        response = consent_current(request)
        assert isinstance(response, dict)
        assert set(response.keys()) == {c.value for c in ConsentType}

    def test_returns_latest_state(self, rf):
        user = UserFactory()
        grant_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")

        request = _authed_request(rf, "get", "/api/v1/compliance/consent", user)

        from apps.compliance.api import consent_current

        response = consent_current(request)
        assert response["analytics"]["action"] == "granted"
        assert response["analytics"]["version"] == "1.0"

    def test_empty_user_shows_nulls(self, rf):
        user = UserFactory()
        request = _authed_request(rf, "get", "/api/v1/compliance/consent", user)

        from apps.compliance.api import consent_current

        response = consent_current(request)
        for entry in response.values():
            assert entry["action"] is None


# ── POST /consent ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestConsentUpdateEndpoint:
    def test_grant_consent_succeeds(self, rf):
        user = UserFactory()
        request = _authed_request(
            rf,
            "post",
            "/api/v1/compliance/consent",
            user,
            body={"consent_type": "analytics", "action": "granted", "version": "1.0"},
            HTTP_X_FORWARDED_FOR="10.0.0.1",
        )

        from apps.compliance.api import consent_update

        body = ConsentRequest(consent_type="analytics", action="granted", version="1.0")
        status, response = consent_update(request, body)

        assert status == 200
        assert response["consent_type"] == "analytics"
        assert response["action"] == "granted"
        assert response["version"] == "1.0"
        assert response["ip_address"] == "10.0.0.1"
        assert response["id"] is not None

    def test_revoke_consent_succeeds(self, rf):
        user = UserFactory()
        request = _authed_request(
            rf,
            "post",
            "/api/v1/compliance/consent",
            user,
            body={"consent_type": "training", "action": "revoked", "version": "2.0"},
        )

        from apps.compliance.api import consent_update

        body = ConsentRequest(consent_type="training", action="revoked", version="2.0")
        status, response = consent_update(request, body)

        assert status == 200
        assert response["action"] == "revoked"

    def test_invalid_consent_type_returns_400(self, rf):
        user = UserFactory()
        request = _authed_request(
            rf,
            "post",
            "/api/v1/compliance/consent",
            user,
            body={"consent_type": "bogus", "action": "granted", "version": "1.0"},
        )

        from apps.compliance.api import consent_update

        body = ConsentRequest(consent_type="bogus", action="granted", version="1.0")
        status, response = consent_update(request, body)

        assert status == 400
        assert "Invalid consent_type" in response["detail"]

    def test_invalid_action_returns_400(self, rf):
        user = UserFactory()
        request = _authed_request(
            rf,
            "post",
            "/api/v1/compliance/consent",
            user,
            body={"consent_type": "analytics", "action": "maybe", "version": "1.0"},
        )

        from apps.compliance.api import consent_update

        body = ConsentRequest(consent_type="analytics", action="maybe", version="1.0")
        status, response = consent_update(request, body)

        assert status == 400
        assert "Invalid action" in response["detail"]

    def test_empty_version_returns_400(self, rf):
        user = UserFactory()
        request = _authed_request(
            rf,
            "post",
            "/api/v1/compliance/consent",
            user,
            body={"consent_type": "analytics", "action": "granted", "version": "  "},
        )

        from apps.compliance.api import consent_update

        body = ConsentRequest(consent_type="analytics", action="granted", version="  ")
        status, response = consent_update(request, body)

        assert status == 400
        assert "version" in response["detail"].lower()

    def test_creates_audit_log(self, rf):
        user = UserFactory()
        AuditLog.objects.all().delete()
        request = _authed_request(
            rf,
            "post",
            "/api/v1/compliance/consent",
            user,
            body={"consent_type": "analytics", "action": "granted", "version": "1.0"},
            HTTP_X_FORWARDED_FOR="10.0.0.5",
        )

        from apps.compliance.api import consent_update

        body = ConsentRequest(consent_type="analytics", action="granted", version="1.0")
        consent_update(request, body)

        entry = AuditLog.objects.filter(action=AuditAction.CONSENT_GRANTED).first()
        assert entry is not None
        assert entry.actor_ip == "10.0.0.5"
        assert entry.metadata["consent_type"] == "analytics"

    def test_syncs_user_settings(self, rf):
        user = UserFactory()
        UserSettings.objects.filter(user=user).update(data_share_analytics=False)
        settings_obj = UserSettings.objects.get(user=user)
        request = _authed_request(
            rf,
            "post",
            "/api/v1/compliance/consent",
            user,
            body={"consent_type": "analytics", "action": "granted", "version": "1.0"},
        )

        from apps.compliance.api import consent_update

        body = ConsentRequest(consent_type="analytics", action="granted", version="1.0")
        consent_update(request, body)

        settings_obj.refresh_from_db()
        assert settings_obj.data_share_analytics is True

    def test_version_is_stripped(self, rf):
        user = UserFactory()
        request = _authed_request(
            rf,
            "post",
            "/api/v1/compliance/consent",
            user,
            body={
                "consent_type": "analytics",
                "action": "granted",
                "version": "  1.0  ",
            },
        )

        from apps.compliance.api import consent_update

        body = ConsentRequest(
            consent_type="analytics", action="granted", version="  1.0  "
        )
        status, response = consent_update(request, body)

        assert status == 200
        assert response["version"] == "1.0"


# ── GET /consent/history ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestConsentHistoryEndpoint:
    def test_returns_all_records(self, rf):
        user = UserFactory()
        grant_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        grant_consent(user, consent_type=ConsentType.TRAINING, version="2.0")

        request = _authed_request(rf, "get", "/api/v1/compliance/consent/history", user)

        from apps.compliance.api import consent_history

        response = consent_history(request)
        assert isinstance(response, list)
        assert len(response) == 2

    def test_empty_history(self, rf):
        user = UserFactory()
        request = _authed_request(rf, "get", "/api/v1/compliance/consent/history", user)

        from apps.compliance.api import consent_history

        response = consent_history(request)
        assert response == []

    def test_does_not_leak_other_users(self, rf):
        user1 = UserFactory()
        user2 = UserFactory()
        grant_consent(user1, consent_type=ConsentType.ANALYTICS, version="1.0")
        grant_consent(user2, consent_type=ConsentType.ANALYTICS, version="1.0")

        request = _authed_request(
            rf, "get", "/api/v1/compliance/consent/history", user1
        )

        from apps.compliance.api import consent_history

        response = consent_history(request)
        assert len(response) == 1
