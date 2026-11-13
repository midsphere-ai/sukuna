"""Tests for outbound webhook CRUD API, delivery, HMAC, retry, auto-disable.

Covers:
- POST /{org_id}/webhooks — create webhook (admin+)
- GET /{org_id}/webhooks — list webhooks (admin+)
- GET /{org_id}/webhooks/{id} — get single webhook (admin+)
- PATCH /{org_id}/webhooks/{id} — update webhook (admin+)
- DELETE /{org_id}/webhooks/{id} — delete webhook (admin+)
- POST /{org_id}/webhooks/{id}/test — send test event
- GET /{org_id}/webhooks/{id}/deliveries — delivery log
- Webhook delivery with HMAC signing
- Retry logic with exponential backoff
- Auto-disable after 10 consecutive failures
- Event filtering
- Slack / Discord formatted payloads
"""

import hashlib
import hmac as hmac_mod
import json
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    OrgWebhook,
    WebhookDeliveryLog,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/workspace/organizations"


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


def _post(client, path, data):
    return client.post(path, data=json.dumps(data), content_type="application/json")


def _patch(client, path, data):
    return client.patch(path, data=json.dumps(data), content_type="application/json")


def _create_org(name="Test Org"):
    owner, token = _make_user()
    resp = _post(_client(token), f"{_BASE}/", {"name": name})
    assert resp.status_code == 201, resp.json()
    org = Organization.objects.get(pk=resp.json()["id"])
    return org, owner, token


def _add_member(org, role, invited_by=None):
    user, token = _make_user()
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        invited_by=invited_by,
    )
    return user, token


def _create_webhook(org, **overrides):
    defaults = {
        "url": "https://example.com/webhook",
        "secret": "test-secret-key",
        "events": ["agent_run.completed", "agent_run.failed"],
        "destination_type": "generic",
    }
    defaults.update(overrides)
    return OrgWebhook.objects.create(organization=org, **defaults)


# =============================================================================
# CREATE WEBHOOK
# =============================================================================


class TestCreateWebhook:
    def test_admin_can_create(self):
        org, owner, token = _create_org()
        c = _client(token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/webhooks",
            {
                "url": "https://example.com/hook",
                "secret": "my-secret",
                "events": ["agent_run.completed"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"] == "https://example.com/hook"
        assert data["events"] == ["agent_run.completed"]
        assert data["destination_type"] == "generic"
        assert data["is_active"] is True
        assert data["failure_count"] == 0
        # Verify audit log
        assert AuditLog.objects.filter(action="webhook_created").exists()

    def test_create_with_slack_destination(self):
        org, owner, token = _create_org()
        c = _client(token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/webhooks",
            {
                "url": "https://hooks.slack.com/test",
                "secret": "s",
                "events": ["agent_run.completed"],
                "destination_type": "slack",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["destination_type"] == "slack"

    def test_create_with_discord_destination(self):
        org, owner, token = _create_org()
        c = _client(token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/webhooks",
            {
                "url": "https://discord.com/api/webhooks/test",
                "secret": "s",
                "events": ["dlp.violation"],
                "destination_type": "discord",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["destination_type"] == "discord"

    def test_invalid_event_type_rejected(self):
        org, owner, token = _create_org()
        c = _client(token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/webhooks",
            {
                "url": "https://example.com/hook",
                "secret": "s",
                "events": ["invalid.event"],
            },
        )
        assert resp.status_code == 400
        assert "Invalid event types" in resp.json()["detail"]

    def test_empty_events_rejected(self):
        org, owner, token = _create_org()
        c = _client(token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/webhooks",
            {
                "url": "https://example.com/hook",
                "secret": "s",
                "events": [],
            },
        )
        assert resp.status_code == 400

    def test_invalid_destination_type_rejected(self):
        org, owner, token = _create_org()
        c = _client(token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/webhooks",
            {
                "url": "https://example.com/hook",
                "secret": "s",
                "events": ["agent_run.completed"],
                "destination_type": "invalid",
            },
        )
        assert resp.status_code == 400

    def test_member_cannot_create(self):
        org, owner, token = _create_org()
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        c = _client(member_token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/webhooks",
            {
                "url": "https://example.com/hook",
                "secret": "s",
                "events": ["agent_run.completed"],
            },
        )
        assert resp.status_code == 401

    def test_viewer_cannot_create(self):
        org, owner, token = _create_org()
        viewer, viewer_token = _add_member(org, OrganizationRole.VIEWER)
        c = _client(viewer_token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/webhooks",
            {
                "url": "https://example.com/hook",
                "secret": "s",
                "events": ["agent_run.completed"],
            },
        )
        assert resp.status_code == 401

    def test_nonmember_cannot_create(self):
        org, owner, token = _create_org()
        other, other_token = _make_user()
        c = _client(other_token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/webhooks",
            {
                "url": "https://example.com/hook",
                "secret": "s",
                "events": ["agent_run.completed"],
            },
        )
        assert resp.status_code == 401


# =============================================================================
# LIST WEBHOOKS
# =============================================================================


class TestListWebhooks:
    def test_list_returns_all(self):
        org, owner, token = _create_org()
        _create_webhook(org, url="https://a.com/1")
        _create_webhook(org, url="https://b.com/2")
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/webhooks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_list_empty(self):
        org, owner, token = _create_org()
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/webhooks")
        assert resp.status_code == 200
        assert resp.json() == []


# =============================================================================
# GET WEBHOOK
# =============================================================================


class TestGetWebhook:
    def test_get_by_id(self):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/webhooks/{wh.pk}")
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://example.com/webhook"

    def test_get_not_found(self):
        org, owner, token = _create_org()
        import uuid

        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/webhooks/{uuid.uuid4()}")
        assert resp.status_code == 404


# =============================================================================
# UPDATE WEBHOOK
# =============================================================================


class TestUpdateWebhook:
    def test_update_url(self):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        c = _client(token)
        resp = _patch(
            c,
            f"{_BASE}/{org.pk}/webhooks/{wh.pk}",
            {
                "url": "https://new.example.com/hook",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://new.example.com/hook"
        # Verify audit log
        assert AuditLog.objects.filter(action="webhook_updated").exists()

    def test_update_events(self):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        c = _client(token)
        resp = _patch(
            c,
            f"{_BASE}/{org.pk}/webhooks/{wh.pk}",
            {
                "events": ["member.joined", "member.removed"],
            },
        )
        assert resp.status_code == 200
        assert set(resp.json()["events"]) == {"member.joined", "member.removed"}

    def test_update_invalid_events(self):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        c = _client(token)
        resp = _patch(
            c,
            f"{_BASE}/{org.pk}/webhooks/{wh.pk}",
            {
                "events": ["bad.event"],
            },
        )
        assert resp.status_code == 400

    def test_update_empty_events_rejected(self):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        c = _client(token)
        resp = _patch(
            c,
            f"{_BASE}/{org.pk}/webhooks/{wh.pk}",
            {
                "events": [],
            },
        )
        assert resp.status_code == 400

    def test_reenable_resets_failure_count(self):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        OrgWebhook.objects.filter(pk=wh.pk).update(failure_count=5, is_active=False)
        c = _client(token)
        resp = _patch(c, f"{_BASE}/{org.pk}/webhooks/{wh.pk}", {"is_active": True})
        assert resp.status_code == 200
        assert resp.json()["failure_count"] == 0
        assert resp.json()["is_active"] is True

    def test_update_not_found(self):
        org, owner, token = _create_org()
        import uuid

        c = _client(token)
        resp = _patch(c, f"{_BASE}/{org.pk}/webhooks/{uuid.uuid4()}", {"url": "x"})
        assert resp.status_code == 404


# =============================================================================
# DELETE WEBHOOK
# =============================================================================


class TestDeleteWebhook:
    def test_delete_webhook(self):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        c = _client(token)
        resp = c.delete(f"{_BASE}/{org.pk}/webhooks/{wh.pk}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert not OrgWebhook.objects.filter(pk=wh.pk).exists()
        assert AuditLog.objects.filter(action="webhook_deleted").exists()

    def test_delete_not_found(self):
        org, owner, token = _create_org()
        import uuid

        c = _client(token)
        resp = c.delete(f"{_BASE}/{org.pk}/webhooks/{uuid.uuid4()}")
        assert resp.status_code == 404


# =============================================================================
# TEST WEBHOOK ENDPOINT
# =============================================================================


class TestTestWebhook:
    @patch("apps.workspace.tasks.send_test_webhook_event")
    def test_sends_test_event(self, mock_send):
        mock_send.return_value = {
            "ok": True,
            "message": "Test event delivered (HTTP 200)",
        }
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        c = _client(token)
        resp = _post(c, f"{_BASE}/{org.pk}/webhooks/{wh.pk}/test", {})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_send.assert_called_once_with(str(wh.pk))

    @patch("apps.workspace.tasks.send_test_webhook_event")
    def test_test_webhook_failure(self, mock_send):
        mock_send.return_value = {"ok": False, "message": "Connection refused"}
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        c = _client(token)
        resp = _post(c, f"{_BASE}/{org.pk}/webhooks/{wh.pk}/test", {})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_test_not_found(self):
        org, owner, token = _create_org()
        import uuid

        c = _client(token)
        resp = _post(c, f"{_BASE}/{org.pk}/webhooks/{uuid.uuid4()}/test", {})
        assert resp.status_code == 404


# =============================================================================
# DELIVERY LOG
# =============================================================================


class TestWebhookDeliveries:
    def test_list_deliveries(self):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        WebhookDeliveryLog.objects.create(
            webhook=wh,
            event_type="agent_run.completed",
            status_code=200,
            response_time_ms=50,
            success=True,
        )
        WebhookDeliveryLog.objects.create(
            webhook=wh,
            event_type="agent_run.failed",
            status_code=500,
            response_time_ms=120,
            success=False,
            error_message="Server error",
        )
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/webhooks/{wh.pk}/deliveries")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Most recent first
        assert data[0]["event_type"] == "agent_run.failed"
        assert data[0]["success"] is False
        assert data[1]["event_type"] == "agent_run.completed"
        assert data[1]["success"] is True

    def test_deliveries_not_found(self):
        org, owner, token = _create_org()
        import uuid

        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/webhooks/{uuid.uuid4()}/deliveries")
        assert resp.status_code == 404


# =============================================================================
# WEBHOOK DELIVERY TASK
# =============================================================================


class TestDeliverWebhookEvent:
    @patch("apps.workspace.tasks.urllib.request.urlopen")
    def test_successful_delivery(self, mock_urlopen):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        from apps.workspace.tasks import deliver_webhook_event

        deliver_webhook_event(
            str(wh.pk),
            "agent_run.completed",
            {
                "event_type": "agent_run.completed",
                "data": {},
                "organization_id": str(org.pk),
            },
        )

        # Should have created a delivery log
        assert WebhookDeliveryLog.objects.filter(webhook=wh, success=True).count() == 1

    @patch("apps.workspace.tasks.urllib.request.urlopen")
    def test_hmac_signature(self, mock_urlopen):
        """Verify the HMAC-SHA256 signature is computed correctly."""
        org, owner, token = _create_org()
        secret = "my-test-secret"
        wh = _create_webhook(org, secret=secret)

        captured_requests = []

        def capture_request(req, **kwargs):
            captured_requests.append(req)
            resp = MagicMock()
            resp.status = 200
            return resp

        mock_urlopen.side_effect = capture_request

        from apps.workspace.tasks import deliver_webhook_event

        payload = {
            "event_type": "agent_run.completed",
            "data": {},
            "organization_id": str(org.pk),
        }
        deliver_webhook_event(str(wh.pk), "agent_run.completed", payload)

        assert len(captured_requests) == 1
        req = captured_requests[0]
        sig = req.get_header("X-midsphere-signature")
        body = req.data
        expected = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert sig == expected

    @patch("apps.workspace.tasks.urllib.request.urlopen")
    def test_failure_increments_count(self, mock_urlopen):
        import urllib.error

        org, owner, token = _create_org()
        wh = _create_webhook(org)

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        from apps.workspace.tasks import deliver_webhook_event

        # Prevent actual retry by mocking apply_async
        with patch.object(deliver_webhook_event, "apply_async"):
            deliver_webhook_event(
                str(wh.pk),
                "agent_run.completed",
                {
                    "event_type": "agent_run.completed",
                    "data": {},
                    "organization_id": str(org.pk),
                },
            )

        wh.refresh_from_db()
        assert wh.failure_count == 1
        assert WebhookDeliveryLog.objects.filter(webhook=wh, success=False).count() == 1

    @patch("apps.workspace.tasks.urllib.request.urlopen")
    def test_retry_on_failure(self, mock_urlopen):
        import urllib.error

        org, owner, token = _create_org()
        wh = _create_webhook(org)

        mock_urlopen.side_effect = urllib.error.URLError("timeout")

        from apps.workspace.tasks import deliver_webhook_event

        with patch.object(deliver_webhook_event, "apply_async") as mock_retry:
            deliver_webhook_event(
                str(wh.pk),
                "agent_run.completed",
                {"event_type": "test", "data": {}, "organization_id": str(org.pk)},
                retry_count=0,
            )
            # Should schedule a retry with countdown=1 (first retry delay)
            mock_retry.assert_called_once()
            call_kwargs = mock_retry.call_args
            assert call_kwargs.kwargs["countdown"] == 1
            # retry_count is 4th element of the args list
            retry_args = call_kwargs.kwargs.get("args") or call_kwargs.args[0]
            assert retry_args[3] == 1  # retry_count incremented

    @patch("apps.workspace.tasks.urllib.request.urlopen")
    def test_auto_disable_after_threshold(self, mock_urlopen):
        import urllib.error

        org, owner, token = _create_org()
        wh = _create_webhook(org)
        # Set failure count just below threshold
        OrgWebhook.objects.filter(pk=wh.pk).update(failure_count=9)

        mock_urlopen.side_effect = urllib.error.URLError("fail")

        from apps.workspace.tasks import deliver_webhook_event

        with patch.object(deliver_webhook_event, "apply_async"):
            deliver_webhook_event(
                str(wh.pk),
                "agent_run.completed",
                {"event_type": "test", "data": {}, "organization_id": str(org.pk)},
                retry_count=3,  # past max retries so no retry scheduling
            )

        wh.refresh_from_db()
        assert wh.failure_count == 10
        assert wh.is_active is False
        # Auto-disable audit log
        assert AuditLog.objects.filter(action="webhook_auto_disabled").exists()

    @patch("apps.workspace.tasks.urllib.request.urlopen")
    def test_success_resets_failure_count(self, mock_urlopen):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        OrgWebhook.objects.filter(pk=wh.pk).update(failure_count=5)

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        from apps.workspace.tasks import deliver_webhook_event

        deliver_webhook_event(
            str(wh.pk),
            "agent_run.completed",
            {"event_type": "test", "data": {}, "organization_id": str(org.pk)},
        )

        wh.refresh_from_db()
        assert wh.failure_count == 0

    def test_inactive_webhook_skipped(self):
        org, owner, token = _create_org()
        wh = _create_webhook(org)
        OrgWebhook.objects.filter(pk=wh.pk).update(is_active=False)

        from apps.workspace.tasks import deliver_webhook_event

        deliver_webhook_event(
            str(wh.pk),
            "agent_run.completed",
            {"event_type": "test", "data": {}, "organization_id": str(org.pk)},
        )

        # No delivery log created for inactive webhook
        assert WebhookDeliveryLog.objects.filter(webhook=wh).count() == 0


# =============================================================================
# EVENT FILTERING (fire_webhook_event)
# =============================================================================


class TestFireWebhookEvent:
    @patch("apps.workspace.tasks.deliver_webhook_event")
    def test_filters_by_subscribed_events(self, mock_deliver):
        org, owner, token = _create_org()
        wh = _create_webhook(org, events=["agent_run.completed"])

        from apps.workspace.tasks import fire_webhook_event

        # Matching event
        fire_webhook_event(str(org.pk), "agent_run.completed", {"msg": "ok"})
        assert mock_deliver.delay.call_count == 1

        mock_deliver.delay.reset_mock()

        # Non-matching event — should not fire
        fire_webhook_event(str(org.pk), "member.joined", {"msg": "new"})
        assert mock_deliver.delay.call_count == 0

    @patch("apps.workspace.tasks.deliver_webhook_event")
    def test_fires_to_multiple_webhooks(self, mock_deliver):
        org, owner, token = _create_org()
        _create_webhook(org, url="https://a.com", events=["agent_run.completed"])
        _create_webhook(org, url="https://b.com", events=["agent_run.completed"])

        from apps.workspace.tasks import fire_webhook_event

        fire_webhook_event(str(org.pk), "agent_run.completed", {})
        assert mock_deliver.delay.call_count == 2

    @patch("apps.workspace.tasks.deliver_webhook_event")
    def test_skips_inactive_webhooks(self, mock_deliver):
        org, owner, token = _create_org()
        wh = _create_webhook(org, events=["agent_run.completed"])
        OrgWebhook.objects.filter(pk=wh.pk).update(is_active=False)

        from apps.workspace.tasks import fire_webhook_event

        fire_webhook_event(str(org.pk), "agent_run.completed", {})
        assert mock_deliver.delay.call_count == 0


# =============================================================================
# SLACK / DISCORD PAYLOAD FORMATTING
# =============================================================================


class TestPayloadFormatting:
    def test_slack_format(self):
        from apps.workspace.tasks import _format_slack_payload

        result = _format_slack_payload(
            "agent_run.completed",
            {"description": "Run finished", "conversation_id": "abc123"},
            "org-1",
        )
        assert "blocks" in result
        # Header, section, context, actions (deep link)
        assert len(result["blocks"]) == 4
        assert result["blocks"][3]["type"] == "actions"

    def test_slack_format_no_conversation(self):
        from apps.workspace.tasks import _format_slack_payload

        result = _format_slack_payload(
            "member.joined", {"description": "New member"}, "org-1"
        )
        assert "blocks" in result
        # Header, section, context (no actions without conversation_id)
        assert len(result["blocks"]) == 3

    def test_discord_format_completed(self):
        from apps.workspace.tasks import _format_discord_payload

        result = _format_discord_payload(
            "agent_run.completed",
            {"description": "Run finished"},
            "org-1",
        )
        assert "embeds" in result
        assert result["embeds"][0]["color"] == 0x2ECC71  # green

    def test_discord_format_failed(self):
        from apps.workspace.tasks import _format_discord_payload

        result = _format_discord_payload(
            "agent_run.failed",
            {"description": "Run failed"},
            "org-1",
        )
        assert result["embeds"][0]["color"] == 0xE74C3C  # red

    def test_discord_format_info(self):
        from apps.workspace.tasks import _format_discord_payload

        result = _format_discord_payload(
            "member.joined",
            {"description": "A member joined"},
            "org-1",
        )
        assert result["embeds"][0]["color"] == 0x3498DB  # blue default


# =============================================================================
# DELIVERY LOG PRUNING
# =============================================================================


class TestDeliveryLogPruning:
    @patch("apps.workspace.tasks.urllib.request.urlopen")
    def test_prunes_logs_beyond_100(self, mock_urlopen):
        org, owner, token = _create_org()
        wh = _create_webhook(org)

        # Create 100 existing logs
        for i in range(100):
            WebhookDeliveryLog.objects.create(
                webhook=wh,
                event_type="agent_run.completed",
                status_code=200,
                response_time_ms=10,
                success=True,
            )

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        from apps.workspace.tasks import deliver_webhook_event

        deliver_webhook_event(
            str(wh.pk),
            "agent_run.completed",
            {"event_type": "test", "data": {}, "organization_id": str(org.pk)},
        )

        # Should still have 100 (pruned the oldest)
        assert WebhookDeliveryLog.objects.filter(webhook=wh).count() == 100
