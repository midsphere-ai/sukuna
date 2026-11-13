"""Tests for the notification system — models, service, API, tasks.

Covers:
- Notification creation and preference enforcement
- Coalescing rapid-fire events
- Muted project suppression
- Email batching via Redis timestamp check
- SSE event cache signal
- API: list, mark read, mark all read, preferences CRUD
- Slack/Discord webhook dispatch
- Preference re-read at delivery time
"""

import json
import uuid
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Notification,
    NotificationPreference,
    NotificationType,
    Organization,
    OrgDiscordIntegration,
    OrgSlackIntegration,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/notifications"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_user():
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


# ── Model tests ──────────────────────────────────────────────────────────────


class TestNotificationModel:
    def test_create_notification(self):
        user, _ = _make_user()
        n = Notification.objects.create(
            user=user,
            type=NotificationType.INJECTION,
            title="Test notification",
            body="Hello world",
            data={"conversation_id": str(uuid.uuid4())},
        )
        assert n.id is not None
        assert n.is_read is False
        assert n.type == "injection"

    def test_notification_ordering(self):
        user, _ = _make_user()
        n1 = Notification.objects.create(
            user=user, type=NotificationType.SHARE, title="First"
        )
        n2 = Notification.objects.create(
            user=user, type=NotificationType.SHARE, title="Second"
        )
        notifs = list(Notification.objects.filter(user=user))
        assert notifs[0].title == "Second"  # Newest first
        assert notifs[1].title == "First"

    def test_notification_str(self):
        user, _ = _make_user()
        n = Notification.objects.create(
            user=user, type=NotificationType.MENTION, title="@you"
        )
        assert "mention" in str(n)
        assert "@you" in str(n)


class TestNotificationPreferenceModel:
    def test_create_preference(self):
        user, _ = _make_user()
        pref = NotificationPreference.objects.create(
            user=user,
            notification_type=NotificationType.INJECTION,
            in_app=True,
            email=False,
            push=False,
            slack=True,
            discord=False,
        )
        assert pref.in_app is True
        assert pref.email is False
        assert pref.slack is True

    def test_unique_constraint(self):
        user, _ = _make_user()
        NotificationPreference.objects.create(
            user=user, notification_type=NotificationType.INJECTION
        )
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            NotificationPreference.objects.create(
                user=user, notification_type=NotificationType.INJECTION
            )

    def test_muted_project_ids(self):
        user, _ = _make_user()
        pid = str(uuid.uuid4())
        pref = NotificationPreference.objects.create(
            user=user,
            notification_type=NotificationType.SHARE,
            muted_project_ids=[pid],
        )
        assert pid in pref.muted_project_ids


# ── Service tests ────────────────────────────────────────────────────────────


class TestNotificationService:
    def test_create_notification_default_preferences(self):
        """Without preferences, in_app + email are enabled."""
        from apps.workspace.notifications import create_notification

        user, _ = _make_user()
        n = create_notification(
            user=user,
            type="injection",
            title="Hello",
            body="World",
        )
        assert n is not None
        assert Notification.objects.filter(user=user).count() == 1

    def test_muted_project_skipped(self):
        """Notification for a muted project is suppressed."""
        from apps.workspace.notifications import create_notification

        user, _ = _make_user()
        pid = str(uuid.uuid4())
        NotificationPreference.objects.create(
            user=user,
            notification_type=NotificationType.INJECTION,
            muted_project_ids=[pid],
        )
        n = create_notification(
            user=user,
            type="injection",
            title="Test",
            data={"project_id": pid},
        )
        assert n is None
        assert Notification.objects.filter(user=user).count() == 0

    def test_in_app_disabled(self):
        """When in_app is disabled, no DB notification is created."""
        from apps.workspace.notifications import create_notification

        user, _ = _make_user()
        NotificationPreference.objects.create(
            user=user,
            notification_type=NotificationType.SHARE,
            in_app=False,
            email=False,
        )
        n = create_notification(user=user, type="share", title="Shared!")
        assert n is None
        assert Notification.objects.filter(user=user).count() == 0

    def test_sse_event_published(self):
        """Creating an in-app notification sets a cache signal."""
        from apps.workspace.notifications import create_notification

        user, _ = _make_user()
        n = create_notification(user=user, type="injection", title="Test")
        assert n is not None
        key = f"notification_signal:{user.id}"
        assert cache.get(key) == str(n.id)

    def test_coalesce_suppresses_after_threshold(self):
        """After COALESCE_THRESHOLD events, subsequent ones are suppressed."""
        from apps.workspace.notifications import COALESCE_THRESHOLD, create_notification

        user, _ = _make_user()
        conv_id = str(uuid.uuid4())
        created = []
        for i in range(COALESCE_THRESHOLD + 2):
            n = create_notification(
                user=user,
                type="injection",
                title=f"Message {i}",
                data={"conversation_id": conv_id, "actor_name": "Alice"},
            )
            created.append(n)

        # First 4 should be created normally (count < threshold)
        for n in created[: COALESCE_THRESHOLD - 1]:
            assert n is not None

        # 5th (threshold) is the coalesced one
        coalesced = created[COALESCE_THRESHOLD - 1]
        assert coalesced is not None
        assert "5 messages" in coalesced.title

        # 6th+ are suppressed
        for n in created[COALESCE_THRESHOLD:]:
            assert n is None

    def test_coalesce_only_applies_to_conversation_scoped(self):
        """Events without conversation_id are not coalesced."""
        from apps.workspace.notifications import create_notification

        user, _ = _make_user()
        for i in range(7):
            n = create_notification(
                user=user,
                type="invitation",
                title=f"Invite {i}",
            )
            assert n is not None  # None should be suppressed


# ── API tests ────────────────────────────────────────────────────────────────


class TestNotificationAPI:
    def test_list_empty(self):
        _, token = _make_user()
        resp = _client(token).get(f"{_BASE}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["unread_count"] == 0
        assert data["notifications"] == []

    def test_list_with_notifications(self):
        user, token = _make_user()
        Notification.objects.create(
            user=user, type=NotificationType.INJECTION, title="N1"
        )
        Notification.objects.create(
            user=user, type=NotificationType.SHARE, title="N2", is_read=True
        )

        resp = _client(token).get(f"{_BASE}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["unread_count"] == 1
        assert len(data["notifications"]) == 2

    def test_list_pagination(self):
        user, token = _make_user()
        for i in range(5):
            Notification.objects.create(
                user=user, type=NotificationType.SHARE, title=f"N{i}"
            )

        resp = _client(token).get(f"{_BASE}/?offset=0&limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["notifications"]) == 2

    def test_list_only_own_notifications(self):
        user1, token1 = _make_user()
        user2, token2 = _make_user()
        Notification.objects.create(
            user=user1, type=NotificationType.SHARE, title="For user1"
        )
        Notification.objects.create(
            user=user2, type=NotificationType.SHARE, title="For user2"
        )

        resp = _client(token1).get(f"{_BASE}/")
        data = resp.json()
        assert data["total"] == 1
        assert data["notifications"][0]["title"] == "For user1"

    def test_mark_read(self):
        user, token = _make_user()
        n = Notification.objects.create(
            user=user, type=NotificationType.INJECTION, title="Test"
        )

        resp = _client(token).patch(
            f"{_BASE}/{n.id}",
            data=json.dumps({"is_read": True}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        n.refresh_from_db()
        assert n.is_read is True

    def test_mark_read_not_found(self):
        _, token = _make_user()
        fake_id = uuid.uuid4()
        resp = _client(token).patch(
            f"{_BASE}/{fake_id}",
            data=json.dumps({"is_read": True}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_mark_read_other_user(self):
        user1, token1 = _make_user()
        user2, token2 = _make_user()
        n = Notification.objects.create(
            user=user1, type=NotificationType.SHARE, title="Mine"
        )

        resp = _client(token2).patch(
            f"{_BASE}/{n.id}",
            data=json.dumps({"is_read": True}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_mark_all_read(self):
        user, token = _make_user()
        for i in range(3):
            Notification.objects.create(
                user=user, type=NotificationType.INJECTION, title=f"N{i}"
            )

        resp = _client(token).patch(
            f"{_BASE}/read-all",
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert Notification.objects.filter(user=user, is_read=False).count() == 0

    def test_unauthenticated(self):
        resp = Client().get(f"{_BASE}/")
        assert resp.status_code == 401


class TestPreferencesAPI:
    def test_get_defaults(self):
        _, token = _make_user()
        resp = _client(token).get(f"{_BASE}/preferences")
        assert resp.status_code == 200
        prefs = resp.json()["preferences"]
        assert len(prefs) == len(NotificationType.choices)
        for p in prefs:
            assert p["in_app"] is True
            assert p["email"] is True
            assert p["push"] is False
            assert p["slack"] is False
            assert p["discord"] is False

    def test_update_preference(self):
        user, token = _make_user()
        resp = _client(token).patch(
            f"{_BASE}/preferences",
            data=json.dumps(
                {
                    "preferences": [
                        {
                            "notification_type": "injection",
                            "email": False,
                            "slack": True,
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200

        pref = NotificationPreference.objects.get(
            user=user, notification_type="injection"
        )
        assert pref.email is False
        assert pref.slack is True
        assert pref.in_app is True  # Default preserved

    def test_update_muted_projects(self):
        user, token = _make_user()
        pid = str(uuid.uuid4())
        resp = _client(token).patch(
            f"{_BASE}/preferences",
            data=json.dumps(
                {
                    "preferences": [
                        {
                            "notification_type": "share",
                            "muted_project_ids": [pid],
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200

        pref = NotificationPreference.objects.get(user=user, notification_type="share")
        assert pid in pref.muted_project_ids

    def test_invalid_type_ignored(self):
        _, token = _make_user()
        resp = _client(token).patch(
            f"{_BASE}/preferences",
            data=json.dumps(
                {"preferences": [{"notification_type": "nonexistent", "email": False}]}
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert NotificationPreference.objects.count() == 0

    def test_get_with_saved_preference(self):
        user, token = _make_user()
        NotificationPreference.objects.create(
            user=user,
            notification_type=NotificationType.MENTION,
            in_app=True,
            email=False,
            push=True,
        )
        resp = _client(token).get(f"{_BASE}/preferences")
        data = resp.json()["preferences"]
        mention_pref = next(p for p in data if p["notification_type"] == "mention")
        assert mention_pref["email"] is False
        assert mention_pref["push"] is True


# ── Celery task tests ────────────────────────────────────────────────────────


class TestEmailTask:
    def test_send_email_success(self):
        """Email is sent and batch window is set."""
        from apps.workspace.tasks import send_notification_email

        user, _ = _make_user()
        send_notification_email(
            user_id=str(user.id),
            notification_type="injection",
            title="Test",
            body="Hello",
        )
        assert len(mail.outbox) == 1
        assert "Test" in mail.outbox[0].subject
        # Batch window is set
        from apps.workspace.tasks import _email_batch_key

        assert cache.get(_email_batch_key(str(user.id))) is not None

    def test_email_batching(self):
        """Second email within batch window is skipped."""
        from apps.workspace.tasks import _email_batch_key, send_notification_email

        user, _ = _make_user()
        # Set batch window
        cache.set(_email_batch_key(str(user.id)), "1", timeout=300)

        send_notification_email(
            user_id=str(user.id),
            notification_type="injection",
            title="Should be skipped",
            body="",
        )
        assert len(mail.outbox) == 0

    def test_email_preference_disabled_at_delivery(self):
        """If email preference is disabled between creation and delivery, skip."""
        from apps.workspace.tasks import send_notification_email

        user, _ = _make_user()
        NotificationPreference.objects.create(
            user=user,
            notification_type=NotificationType.INJECTION,
            email=False,
        )
        send_notification_email(
            user_id=str(user.id),
            notification_type="injection",
            title="Test",
            body="Hello",
        )
        assert len(mail.outbox) == 0

    def test_email_user_not_found(self):
        """Task handles missing user gracefully."""
        from apps.workspace.tasks import send_notification_email

        send_notification_email(
            user_id="999999",
            notification_type="injection",
            title="Test",
            body="Hello",
        )
        assert len(mail.outbox) == 0


class TestWebhookTask:
    def test_slack_webhook_sent(self):
        """Slack webhook is called when integration is active."""
        from apps.workspace.tasks import send_webhook_notification

        org = Organization.objects.create(name="TestOrg", slug="test-org")
        OrgSlackIntegration.objects.create(
            organization=org,
            webhook_url="https://hooks.slack.com/test",
            is_active=True,
        )

        with patch("urllib.request.urlopen") as mock_open:
            send_webhook_notification(
                organization_id=str(org.id),
                notification_type="injection",
                title="Test",
                body="Hello",
                send_slack=True,
                send_discord=False,
            )
            mock_open.assert_called_once()

    def test_discord_webhook_sent(self):
        """Discord webhook is called when integration is active."""
        from apps.workspace.tasks import send_webhook_notification

        org = Organization.objects.create(name="TestOrg", slug="test-org-dc")
        OrgDiscordIntegration.objects.create(
            organization=org,
            webhook_url="https://discord.com/api/webhooks/test",
            is_active=True,
        )

        with patch("urllib.request.urlopen") as mock_open:
            send_webhook_notification(
                organization_id=str(org.id),
                notification_type="share",
                title="Shared!",
                body="A project was shared",
                send_slack=False,
                send_discord=True,
            )
            mock_open.assert_called_once()

    def test_slack_no_integration(self):
        """No error when org has no Slack integration."""
        from apps.workspace.tasks import send_webhook_notification

        org = Organization.objects.create(name="NoSlack", slug="no-slack")
        # Should not raise
        send_webhook_notification(
            organization_id=str(org.id),
            notification_type="injection",
            title="Test",
            body="Hello",
            send_slack=True,
        )

    def test_slack_inactive_integration(self):
        """Inactive integration is not used."""
        from apps.workspace.tasks import send_webhook_notification

        org = Organization.objects.create(name="TestOrg", slug="test-org-inactive")
        OrgSlackIntegration.objects.create(
            organization=org,
            webhook_url="https://hooks.slack.com/test",
            is_active=False,
        )

        with patch("urllib.request.urlopen") as mock_open:
            send_webhook_notification(
                organization_id=str(org.id),
                notification_type="injection",
                title="Test",
                body="Hello",
                send_slack=True,
            )
            mock_open.assert_not_called()
