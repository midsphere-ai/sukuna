"""Tests for automatic audit log capture via Django signals."""

import pytest
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.test import RequestFactory

from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def mock_request(rf):
    """Build a request with request_id and IP set."""
    request = rf.get("/")
    request.request_id = "sig-test-req"
    request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.1"
    return request


@pytest.mark.django_db
class TestAuthSignals:
    def test_login_creates_audit_entry(self, mock_request):
        user = UserFactory()
        # Clear any creation audit entries
        AuditLog.objects.all().delete()

        user_logged_in.send(sender=user.__class__, request=mock_request, user=user)

        entry = AuditLog.objects.filter(action="login").first()
        assert entry is not None
        assert entry.resource_type == "user"
        assert entry.resource_id == str(user.pk)
        assert entry.actor_email == user.email
        assert entry.actor_ip == "203.0.113.1"
        assert entry.request_id == "sig-test-req"

    def test_logout_creates_audit_entry(self, mock_request):
        user = UserFactory()
        AuditLog.objects.all().delete()

        user_logged_out.send(sender=user.__class__, request=mock_request, user=user)

        entry = AuditLog.objects.filter(action="logout").first()
        assert entry is not None
        assert entry.actor_id.int == user.pk

    def test_logout_with_none_user_is_ignored(self, mock_request):
        AuditLog.objects.all().delete()
        user_logged_out.send(sender=None, request=mock_request, user=None)
        assert AuditLog.objects.filter(action="logout").count() == 0

    def test_login_failed_creates_audit_entry(self, mock_request):
        AuditLog.objects.all().delete()
        user_login_failed.send(
            sender=None,
            credentials={"email": "attacker@example.com"},
            request=mock_request,
        )

        entry = AuditLog.objects.filter(action="login_failed").first()
        assert entry is not None
        assert entry.actor_ip == "203.0.113.1"
        assert entry.metadata["username"] == "attacker@example.com"


@pytest.mark.django_db
class TestUserModelSignals:
    def test_user_creation_logged(self):
        AuditLog.objects.all().delete()
        user = UserFactory()

        entries = AuditLog.objects.filter(action="create", resource_type="user")
        assert entries.exists()
        entry = entries.first()
        assert entry.resource_id == str(user.pk)
        assert entry.actor_email == user.email

    def test_user_update_logged(self):
        user = UserFactory()
        AuditLog.objects.all().delete()

        user.name = "Updated Name"
        user.save()

        entries = AuditLog.objects.filter(action="update", resource_type="user")
        assert entries.exists()

    def test_user_deletion_logged(self):
        user = UserFactory()
        pk = str(user.pk)
        email = user.email
        AuditLog.objects.all().delete()

        user.delete()

        entries = AuditLog.objects.filter(action="delete", resource_type="user")
        assert entries.exists()
        entry = entries.first()
        assert entry.resource_id == pk
        assert entry.actor_email == email
