"""Tests for retention policy API endpoints."""

import json

import pytest
from django.test import RequestFactory

from apps.compliance.models import RetentionPolicy
from apps.users.tests.factories import UserFactory


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def superuser():
    return UserFactory(is_superuser=True)


@pytest.fixture
def regular_user():
    return UserFactory()


def _authed_request(rf, method, path, user, body=None, **kwargs):
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


@pytest.mark.django_db
class TestListRetentionPolicies:
    def test_superuser_can_list(self, rf, superuser):
        RetentionPolicy.objects.create(
            resource_type="test_type", retention_days=30, action="delete"
        )
        request = _authed_request(
            rf, "get", "/api/v1/compliance/retention-policies", superuser
        )

        from apps.compliance.api import list_retention_policies

        status, data = list_retention_policies(request)
        assert status == 200
        assert any(p["resource_type"] == "test_type" for p in data)

    def test_non_superuser_rejected(self, rf, regular_user):
        request = _authed_request(
            rf, "get", "/api/v1/compliance/retention-policies", regular_user
        )

        from apps.compliance.api import list_retention_policies

        status, data = list_retention_policies(request)
        assert status == 403

    def test_list_returns_all_fields(self, rf, superuser):
        policy = RetentionPolicy.objects.create(
            resource_type="fields_test", retention_days=90, action="anonymize"
        )
        request = _authed_request(
            rf, "get", "/api/v1/compliance/retention-policies", superuser
        )

        from apps.compliance.api import list_retention_policies

        status, data = list_retention_policies(request)
        assert status == 200
        p = next(item for item in data if item["resource_type"] == "fields_test")
        assert p["id"] == str(policy.pk)
        assert p["retention_days"] == 90
        assert p["action"] == "anonymize"
        assert p["is_active"] is True
        assert p["last_run_at"] is None
        assert p["records_affected_last_run"] == 0


@pytest.mark.django_db
class TestUpdateRetentionPolicy:
    def test_update_retention_days(self, rf, superuser):
        policy = RetentionPolicy.objects.create(
            resource_type="update_test", retention_days=30, action="delete"
        )
        request = _authed_request(
            rf,
            "patch",
            f"/api/v1/compliance/retention-policies/{policy.pk}",
            superuser,
            body={"retention_days": 60},
        )

        from apps.compliance.api import RetentionPolicyUpdate, update_retention_policy

        body = RetentionPolicyUpdate(retention_days=60)
        status, data = update_retention_policy(request, policy.pk, body)
        assert status == 200
        assert data["retention_days"] == 60
        policy.refresh_from_db()
        assert policy.retention_days == 60

    def test_update_action(self, rf, superuser):
        policy = RetentionPolicy.objects.create(
            resource_type="action_test", retention_days=30, action="delete"
        )
        request = _authed_request(
            rf,
            "patch",
            f"/api/v1/compliance/retention-policies/{policy.pk}",
            superuser,
            body={"action": "anonymize"},
        )

        from apps.compliance.api import RetentionPolicyUpdate, update_retention_policy

        body = RetentionPolicyUpdate(action="anonymize")
        status, data = update_retention_policy(request, policy.pk, body)
        assert status == 200
        assert data["action"] == "anonymize"

    def test_update_is_active(self, rf, superuser):
        policy = RetentionPolicy.objects.create(
            resource_type="active_test", retention_days=30, action="delete"
        )

        from apps.compliance.api import RetentionPolicyUpdate, update_retention_policy

        body = RetentionPolicyUpdate(is_active=False)
        request = _authed_request(
            rf,
            "patch",
            f"/api/v1/compliance/retention-policies/{policy.pk}",
            superuser,
            body={"is_active": False},
        )
        status, data = update_retention_policy(request, policy.pk, body)
        assert status == 200
        assert data["is_active"] is False

    def test_non_superuser_rejected(self, rf, regular_user):
        policy = RetentionPolicy.objects.create(
            resource_type="reject_test", retention_days=30, action="delete"
        )

        from apps.compliance.api import RetentionPolicyUpdate, update_retention_policy

        body = RetentionPolicyUpdate(retention_days=60)
        request = _authed_request(
            rf,
            "patch",
            f"/api/v1/compliance/retention-policies/{policy.pk}",
            regular_user,
            body={"retention_days": 60},
        )
        status, _ = update_retention_policy(request, policy.pk, body)
        assert status == 403

    def test_not_found(self, rf, superuser):
        import uuid

        from apps.compliance.api import RetentionPolicyUpdate, update_retention_policy

        fake_id = uuid.uuid4()
        body = RetentionPolicyUpdate(retention_days=60)
        request = _authed_request(
            rf,
            "patch",
            f"/api/v1/compliance/retention-policies/{fake_id}",
            superuser,
            body={"retention_days": 60},
        )
        status, _ = update_retention_policy(request, fake_id, body)
        assert status == 404
