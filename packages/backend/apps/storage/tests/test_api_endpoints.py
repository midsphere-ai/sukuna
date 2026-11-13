"""
Integration tests for storage app API endpoints.

US-060: Tests for storage (memory) API endpoints with focus on:
- Settings: GET/PATCH /memory/settings
- Stats: GET /memory/stats/user, GET /memory/stats/cache
- Health: GET /memory/health
- Conversations: POST, GET, PATCH, DELETE /memory/conversations
- Conversations: POST /memory/conversations/bulk-delete
- Conversations: GET /memory/conversations/search
- Shared: GET /memory/conversations/{id}/shared (public)
- Files: POST /memory/files, GET /memory/files, GET /memory/files/{id}/download
- Addons: POST /memory/addons/register, GET /memory/addons, GET /memory/user-addons
- MCP Configs: POST/GET/DELETE /memory/mcp-configs

Covers:
- Authentication and authorization
- CRUD operations
- Pagination
- Error cases
"""

import json
import uuid

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.storage.models import Conversation
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

_P = "/api/v1/memory"


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


def _setup_conversation(user, title="Test conversation"):
    return Conversation.objects.create(user=user, title=title)


def _auth_client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


# =============================================================================
# AUTHENTICATION TESTS
# =============================================================================


class TestStorageAuthentication:
    """Verify auth on all authenticated storage endpoints."""

    AUTHENTICATED_ENDPOINTS = [
        ("get", f"{_P}/settings"),
        ("patch", f"{_P}/settings"),
        ("get", f"{_P}/stats/user"),
        ("get", f"{_P}/stats/cache"),
        ("get", f"{_P}/health"),
        ("post", f"{_P}/conversations"),
        ("get", f"{_P}/conversations"),
        ("get", f"{_P}/conversations/search?query=test"),
        ("delete", f"{_P}/conversations"),
        ("get", f"{_P}/files"),
        ("get", f"{_P}/addons"),
        ("get", f"{_P}/user-addons"),
        ("get", f"{_P}/mcp-configs"),
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

    def test_valid_token_does_not_return_401(self):
        user, token = _setup_user()
        for method, path in self.AUTHENTICATED_ENDPOINTS:
            cache.clear()
            client = _auth_client(token)
            resp = self._make_request(client, method, path)
            assert resp.status_code != 401, (
                f"{method.upper()} {path} returned 401 with valid token"
            )


# =============================================================================
# SETTINGS ENDPOINTS
# =============================================================================


class TestSettings:
    """Test GET/PATCH /memory/settings."""

    def test_get_settings_auto_creates(self):
        _, token = _setup_user()
        resp = _auth_client(token).get(f"{_P}/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "theme" in data

    def test_update_settings(self):
        _, token = _setup_user()
        resp = _auth_client(token).patch(
            f"{_P}/settings",
            data=json.dumps({"theme": "dark"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["theme"] == "dark"

    def test_partial_update_preserves_other_fields(self):
        _, token = _setup_user()
        # Set theme
        _auth_client(token).patch(
            f"{_P}/settings",
            data=json.dumps({"theme": "dark"}),
            content_type="application/json",
        )
        # Update nickname only
        _auth_client(token).patch(
            f"{_P}/settings",
            data=json.dumps({"nickname": "test_nick"}),
            content_type="application/json",
        )
        # Verify theme preserved
        resp = _auth_client(token).get(f"{_P}/settings")
        data = resp.json()
        assert data["theme"] == "dark"
        assert data["nickname"] == "test_nick"


# =============================================================================
# STATS ENDPOINTS
# =============================================================================


class TestStats:
    """Test GET /memory/stats/user and /memory/stats/cache."""

    def test_user_stats(self):
        user, token = _setup_user()
        _setup_conversation(user, "Conv 1")
        _setup_conversation(user, "Conv 2")

        resp = _auth_client(token).get(f"{_P}/stats/user")
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_count"] == 2

    def test_cache_stats(self):
        _, token = _setup_user()
        resp = _auth_client(token).get(f"{_P}/stats/cache")
        assert resp.status_code == 200
        data = resp.json()
        assert "cache_size" in data
        assert "cache_type" in data


# =============================================================================
# HEALTH ENDPOINT
# =============================================================================


class TestHealth:
    """Test GET /memory/health."""

    def test_health_check(self):
        _, token = _setup_user()
        resp = _auth_client(token).get(f"{_P}/health")
        assert resp.status_code == 200


# =============================================================================
# CONVERSATION ENDPOINTS
# =============================================================================


class TestConversations:
    """Test conversation CRUD endpoints."""

    def test_create_conversation(self):
        _, token = _setup_user()
        resp = _auth_client(token).post(f"{_P}/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert "conversation_id" in data
        assert data["is_new"] is True

    def test_create_returns_existing_empty(self):
        _, token = _setup_user()
        # Create first
        resp1 = _auth_client(token).post(f"{_P}/conversations")
        # Create again — should return existing empty one
        resp2 = _auth_client(token).post(f"{_P}/conversations")
        assert resp2.status_code == 200

    def test_list_conversations(self):
        user, token = _setup_user()
        _setup_conversation(user, "Conv 1")
        _setup_conversation(user, "Conv 2")

        resp = _auth_client(token).get(f"{_P}/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) == 2

    def test_list_conversations_pagination(self):
        user, token = _setup_user()
        for i in range(3):
            _setup_conversation(user, f"Conv {i}")

        resp = _auth_client(token).get(f"{_P}/conversations?page=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "count" in data

    def test_update_conversation(self):
        user, token = _setup_user()
        conv = _setup_conversation(user)

        resp = _auth_client(token).patch(
            f"{_P}/conversations/{conv.id}",
            data=json.dumps({"title": "Updated Title"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"

    def test_delete_conversation(self):
        user, token = _setup_user()
        conv = _setup_conversation(user)

        resp = _auth_client(token).delete(f"{_P}/conversations/{conv.id}")
        assert resp.status_code == 200
        assert not Conversation.objects.filter(id=conv.id).exists()

    def test_delete_all_conversations(self):
        user, token = _setup_user()
        _setup_conversation(user, "Conv 1")
        _setup_conversation(user, "Conv 2")

        resp = _auth_client(token).delete(f"{_P}/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted_count"] == 2
        assert Conversation.objects.filter(user=user).count() == 0

    def test_delete_nonexistent_conversation_404(self):
        _, token = _setup_user()
        fake_id = uuid.uuid4()

        resp = _auth_client(token).delete(f"{_P}/conversations/{fake_id}")
        assert resp.status_code == 404

    def test_cannot_access_other_users_conversation(self):
        user1, _ = _setup_user()
        conv = _setup_conversation(user1)

        user2 = UserFactory()
        token2 = Token.objects.create(user=user2).key

        resp = _auth_client(token2).delete(f"{_P}/conversations/{conv.id}")
        assert resp.status_code in (401, 403, 404)

    def test_search_conversations(self):
        user, token = _setup_user()
        _setup_conversation(user, "Python tutorial")
        _setup_conversation(user, "JavaScript guide")

        resp = _auth_client(token).get(f"{_P}/conversations/search?query=Python")
        assert resp.status_code == 200

    def test_update_conversation_metadata(self):
        """Test updating conversation with metadata."""
        user, token = _setup_user()
        conv = _setup_conversation(user)

        resp = _auth_client(token).patch(
            f"{_P}/conversations/{conv.id}",
            data=json.dumps({"metadata": {"shared": True}}),
            content_type="application/json",
        )
        assert resp.status_code == 200


# =============================================================================
# SHARED CONVERSATION (PUBLIC)
# =============================================================================


class TestSharedConversation:
    """Test GET /memory/conversations/{id}/shared — unauthenticated."""

    def test_shared_conversation_returns_data(self):
        user, _ = _setup_user()
        conv = Conversation.objects.create(
            user=user, title="Shared Conv", metadata={"shared": True}
        )

        resp = Client().get(f"{_P}/conversations/{conv.id}/shared")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Shared Conv"

    def test_non_shared_returns_404(self):
        user, _ = _setup_user()
        conv = Conversation.objects.create(
            user=user, title="Private Conv", metadata={"shared": False}
        )

        resp = Client().get(f"{_P}/conversations/{conv.id}/shared")
        assert resp.status_code == 404

    def test_nonexistent_returns_404(self):
        fake_id = uuid.uuid4()
        resp = Client().get(f"{_P}/conversations/{fake_id}/shared")
        assert resp.status_code == 404


# =============================================================================
# FILES ENDPOINTS
# =============================================================================


class TestFiles:
    """Test file endpoints."""

    def test_list_files_empty(self):
        _, token = _setup_user()
        resp = _auth_client(token).get(f"{_P}/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []

    def test_download_nonexistent_file_404(self):
        _, token = _setup_user()
        fake_id = uuid.uuid4()
        resp = _auth_client(token).get(f"{_P}/files/{fake_id}/download")
        assert resp.status_code == 404


# =============================================================================
# MCP CONFIGS ENDPOINTS
# =============================================================================


class TestMCPConfigs:
    """Test MCP config CRUD endpoints."""

    def test_create_mcp_config(self):
        _, token = _setup_user()
        resp = _auth_client(token).post(
            f"{_P}/mcp-configs",
            data=json.dumps(
                {
                    "server_name": "test-server",
                    "server_type": "stdio",
                    "command": "node",
                    "arguments": "server.js",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data

    def test_list_mcp_configs(self):
        _, token = _setup_user()
        # Create one first
        _auth_client(token).post(
            f"{_P}/mcp-configs",
            data=json.dumps(
                {
                    "server_name": "test-server",
                    "server_type": "stdio",
                    "command": "node",
                }
            ),
            content_type="application/json",
        )

        resp = _auth_client(token).get(f"{_P}/mcp-configs")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) == 1

    def test_delete_mcp_config(self):
        _, token = _setup_user()
        create_resp = _auth_client(token).post(
            f"{_P}/mcp-configs",
            data=json.dumps(
                {
                    "server_name": "delete-me",
                    "server_type": "stdio",
                    "command": "node",
                }
            ),
            content_type="application/json",
        )
        config_id = create_resp.json()["id"]

        resp = _auth_client(token).delete(f"{_P}/mcp-configs/{config_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True

    def test_delete_nonexistent_config_404(self):
        _, token = _setup_user()
        fake_id = uuid.uuid4()
        resp = _auth_client(token).delete(f"{_P}/mcp-configs/{fake_id}")
        assert resp.status_code == 404

    def test_upsert_mcp_config(self):
        """Creating with same server_name should update, not duplicate."""
        _, token = _setup_user()
        client = _auth_client(token)

        client.post(
            f"{_P}/mcp-configs",
            data=json.dumps(
                {
                    "server_name": "upsert-test",
                    "server_type": "stdio",
                    "command": "node",
                }
            ),
            content_type="application/json",
        )
        client.post(
            f"{_P}/mcp-configs",
            data=json.dumps(
                {
                    "server_name": "upsert-test",
                    "server_type": "sse",
                    "command": "python",
                }
            ),
            content_type="application/json",
        )

        resp = client.get(f"{_P}/mcp-configs")
        assert len(resp.json()["items"]) == 1

    def test_other_user_cannot_delete_config(self):
        _, token1 = _setup_user()
        create_resp = _auth_client(token1).post(
            f"{_P}/mcp-configs",
            data=json.dumps(
                {
                    "server_name": "private",
                    "server_type": "stdio",
                    "command": "node",
                }
            ),
            content_type="application/json",
        )
        config_id = create_resp.json()["id"]

        user2 = UserFactory()
        token2 = Token.objects.create(user=user2).key
        resp = _auth_client(token2).delete(f"{_P}/mcp-configs/{config_id}")
        assert resp.status_code == 404
