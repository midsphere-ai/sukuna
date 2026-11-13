"""Unit tests for AddonsService business logic."""

import logging
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from apps.billing.models import SubscriptionPlan, UserSubscription
from apps.storage.errors import (
    AddonAlreadyRegistered,
    AddonError,
    AlreadyAuthorised,
    AuthLinkNotExpired,
    NonExistentAddon,
    NoToolsFound,
)
from apps.storage.models import MarketplaceAddon, UserMarketplaceAddons
from apps.storage.services.addons import AddonsService
from apps.users.tests.factories import UserFactory
from config.errors.common import InvalidInputError, UnauthorizedAccessError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(user):
    request = MagicMock()
    request.auth = user
    return request


def _make_service(user):
    svc = AddonsService.__new__(AddonsService)
    svc._user_service = MagicMock()
    svc._cache_service = MagicMock()
    svc._cache_service.get.return_value = None  # default: no cache
    svc._logger = logging.getLogger("test.addons")
    svc._service_kwargs = {}
    svc._get_authenticated_user = MagicMock(return_value=user)
    return svc


def _setup_addon(user):
    """Create a marketplace addon, user subscription, and user addon."""
    plan = SubscriptionPlan.objects.create(
        name="AddonPlan",
        tier=f"addon_{uuid.uuid4().hex[:6]}",
        price=Decimal("10.00"),
        features={"max_addons": (10, "10")},
    )
    UserSubscription.objects.create(user=user, plan=plan, status="active")
    addon = MarketplaceAddon.objects.create(
        name="Slack",
        description="Slack integration",
        link="https://slack.com",
        logo="https://slack.com/logo.png",
        enum="SLACK",
    )
    return addon, plan


# ---------------------------------------------------------------------------
# _map_and_log_error
# ---------------------------------------------------------------------------
class TestAddonErrorMapping:
    def setup_method(self):
        self.svc = _make_service(MagicMock())

    def test_known_error_passthrough(self):
        e = NonExistentAddon("nope")
        assert self.svc._map_and_log_error(e, "ctx") is e

    def test_circuit_breaker_maps_to_addon_error(self):
        from circuitbreaker import CircuitBreakerError

        e = CircuitBreakerError(MagicMock())
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, AddonError)
        assert "temporarily unavailable" in str(result)

    def test_validation_error_maps_to_input(self):
        from django.core.exceptions import ValidationError

        e = ValidationError("bad")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, InvalidInputError)

    def test_unexpected_maps_to_addon_error(self):
        e = RuntimeError("boom")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, AddonError)


# ---------------------------------------------------------------------------
# register_addon
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRegisterAddon:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.addon, self.plan = _setup_addon(self.user)

    def test_register_success(self):
        result = self.svc.register_addon(self.request, str(self.addon.id))
        assert result.is_new is True
        assert UserMarketplaceAddons.objects.filter(owner=self.user).count() == 1

    def test_register_nonexistent_addon(self):
        fake_id = str(uuid.uuid4())
        with pytest.raises(NonExistentAddon):
            self.svc.register_addon(self.request, fake_id)

    def test_register_already_registered(self):
        self.svc.register_addon(self.request, str(self.addon.id))
        with pytest.raises(AddonAlreadyRegistered):
            self.svc.register_addon(self.request, str(self.addon.id))


# ---------------------------------------------------------------------------
# unregister_addon
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUnregisterAddon:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.addon, _ = _setup_addon(self.user)

    def test_unregister_success(self):
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        result = self.svc.unregister_addon(self.request, str(reg.user_addon_id))
        assert result.removed is True
        assert UserMarketplaceAddons.objects.filter(owner=self.user).count() == 0

    def test_unregister_nonexistent(self):
        fake_id = str(uuid.uuid4())
        with pytest.raises(NonExistentAddon):
            self.svc.unregister_addon(self.request, fake_id)


# ---------------------------------------------------------------------------
# get_addon_auth_link
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetAddonAuthLink:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.addon, _ = _setup_addon(self.user)

    def test_already_authorised(self):
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        ua = UserMarketplaceAddons.objects.get(id=reg.user_addon_id)
        ua.auth_complete = True
        ua.save()
        with pytest.raises(AlreadyAuthorised):
            self.svc.get_addon_auth_link(self.request, str(reg.user_addon_id))

    def test_existing_link_returned(self):
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        ua = UserMarketplaceAddons.objects.get(id=reg.user_addon_id)
        ua.auth_link = "https://composio.dev/auth/existing"
        ua.save()
        result = self.svc.get_addon_auth_link(self.request, str(reg.user_addon_id))
        assert result.auth_link == "https://composio.dev/auth/existing"

    @patch.object(AddonsService, "_get_auth_link")
    def test_generates_new_link(self, mock_get_auth):
        mock_get_auth.return_value = ("https://composio.dev/auth/new", "config_123")
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        result = self.svc.get_addon_auth_link(self.request, str(reg.user_addon_id))
        assert result.auth_link == "https://composio.dev/auth/new"

    @patch.object(AddonsService, "_get_auth_link")
    def test_composio_failure(self, mock_get_auth):
        mock_get_auth.return_value = (None, None)
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        with pytest.raises(AddonError, match="Composio failed"):
            self.svc.get_addon_auth_link(self.request, str(reg.user_addon_id))


# ---------------------------------------------------------------------------
# check_and_update_auth_status
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCheckAndUpdateAuthStatus:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.addon, _ = _setup_addon(self.user)

    @patch.object(AddonsService, "_check_connection_status")
    def test_with_config_id(self, mock_check):
        mock_check.return_value = (True, "ACTIVE")
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        ua = UserMarketplaceAddons.objects.get(id=reg.user_addon_id)
        ua.config_id = "conn_123"
        ua.save()
        result = self.svc.check_and_update_auth_status(
            self.request, str(reg.user_addon_id)
        )
        assert result.is_authorised is True

    @patch.object(AddonsService, "_check_service_auth")
    def test_fallback_without_config_id(self, mock_auth):
        mock_auth.return_value = False
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        result = self.svc.check_and_update_auth_status(
            self.request, str(reg.user_addon_id)
        )
        assert result.is_authorised is False


# ---------------------------------------------------------------------------
# regenerate_auth_link
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRegenerateAuthLink:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.addon, _ = _setup_addon(self.user)

    def test_already_authorised(self):
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        ua = UserMarketplaceAddons.objects.get(id=reg.user_addon_id)
        ua.auth_complete = True
        ua.save()
        with pytest.raises(AlreadyAuthorised):
            self.svc.regenerate_auth_link(self.request, str(reg.user_addon_id))

    @patch.object(AddonsService, "_check_connection_status")
    def test_active_connection_raises(self, mock_check):
        mock_check.return_value = (True, "ACTIVE")
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        ua = UserMarketplaceAddons.objects.get(id=reg.user_addon_id)
        ua.config_id = "conn_act"
        ua.save()
        with pytest.raises(AlreadyAuthorised):
            self.svc.regenerate_auth_link(self.request, str(reg.user_addon_id))

    @patch.object(AddonsService, "_check_connection_status")
    def test_pending_status_raises(self, mock_check):
        mock_check.return_value = (False, "PENDING")
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        ua = UserMarketplaceAddons.objects.get(id=reg.user_addon_id)
        ua.config_id = "conn_pend"
        ua.save()
        with pytest.raises(AuthLinkNotExpired):
            self.svc.regenerate_auth_link(self.request, str(reg.user_addon_id))

    @patch.object(AddonsService, "_get_auth_link")
    @patch.object(AddonsService, "_check_connection_status")
    def test_expired_regenerates(self, mock_check, mock_auth):
        mock_check.return_value = (False, "EXPIRED")
        mock_auth.return_value = ("https://composio.dev/auth/regen", "config_regen")
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        ua = UserMarketplaceAddons.objects.get(id=reg.user_addon_id)
        ua.config_id = "conn_exp"
        ua.save()
        result = self.svc.regenerate_auth_link(self.request, str(reg.user_addon_id))
        assert result.auth_link == "https://composio.dev/auth/regen"


# ---------------------------------------------------------------------------
# get_user_addons / get_all_addons
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetAddons:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.addon, _ = _setup_addon(self.user)

    def test_get_user_addons(self):
        self.svc.register_addon(self.request, str(self.addon.id))
        addons = self.svc.get_user_addons(self.request)
        assert addons.count() == 1

    def test_get_all_addons(self):
        addons = self.svc.get_all_addons()
        assert addons.count() >= 1


# ---------------------------------------------------------------------------
# search_user_addons
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSearchUserAddons:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.addon, _ = _setup_addon(self.user)
        self.svc.register_addon(self.request, str(self.addon.id))

    def test_search_by_name(self):
        results = self.svc.search_user_addons(self.request, "Slack", None)
        assert results.count() == 1

    def test_search_no_results(self):
        results = self.svc.search_user_addons(self.request, "nonexistent_xyz", None)
        assert results.count() == 0

    def test_search_empty_query(self):
        with pytest.raises(InvalidInputError, match="empty"):
            self.svc.search_user_addons(self.request, "", None)

    def test_search_whitespace_query(self):
        with pytest.raises(InvalidInputError, match="empty"):
            self.svc.search_user_addons(self.request, "   ", None)


# ---------------------------------------------------------------------------
# search_marketplace_addons
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSearchMarketplaceAddons:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svc = _make_service(MagicMock())
        MarketplaceAddon.objects.create(
            name="GitHub",
            description="GitHub integration",
            link="https://github.com",
            logo="https://github.com/logo.png",
            enum="GITHUB",
        )

    def test_search_by_name(self):
        results = self.svc.search_marketplace_addons("GitHub")
        assert results.count() == 1

    def test_search_partial(self):
        results = self.svc.search_marketplace_addons("Git")
        assert results.count() == 1

    def test_search_no_match(self):
        results = self.svc.search_marketplace_addons("zzzzz_nope")
        assert results.count() == 0


# ---------------------------------------------------------------------------
# get_expanded_addon
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetExpandedAddon:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.addon, _ = _setup_addon(self.user)

    @patch.object(AddonsService, "_get_tools_info")
    def test_expanded_without_registration(self, mock_tools):
        mock_tools.return_value = [{"name": "send_message", "description": "Send msg"}]
        result = self.svc.get_expanded_addon(self.request, str(self.addon.id))
        assert result["marketplace_addon"] is not None
        assert result["user_addon"] is None
        assert len(result["features"]) == 1

    @patch.object(AddonsService, "_get_tools_info")
    def test_expanded_with_registration(self, mock_tools):
        mock_tools.return_value = []
        self.svc.register_addon(self.request, str(self.addon.id))
        result = self.svc.get_expanded_addon(self.request, str(self.addon.id))
        assert result["user_addon"] is not None

    def test_expanded_nonexistent(self):
        fake_id = str(uuid.uuid4())
        with pytest.raises(NonExistentAddon):
            self.svc.get_expanded_addon(self.request, fake_id)


# ---------------------------------------------------------------------------
# get_addon_connection_status
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetAddonConnectionStatus:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.addon, _ = _setup_addon(self.user)

    @patch.object(AddonsService, "_check_connection_status")
    def test_with_config_id(self, mock_check):
        mock_check.return_value = (True, "ACTIVE")
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        ua = UserMarketplaceAddons.objects.get(id=reg.user_addon_id)
        ua.config_id = "conn_status"
        ua.save()
        result = self.svc.get_addon_connection_status(
            str(reg.user_addon_id), self.user.id
        )
        assert result["is_active"] is True
        assert result["status"] == "ACTIVE"

    def test_without_config_id(self):
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        result = self.svc.get_addon_connection_status(
            str(reg.user_addon_id), self.user.id
        )
        assert result["is_active"] is False
        assert result["status"] == "NOT_INITIATED"

    def test_wrong_owner(self):
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        other_user = UserFactory()
        with pytest.raises(UnauthorizedAccessError):
            self.svc.get_addon_connection_status(str(reg.user_addon_id), other_user.id)

    def test_nonexistent_addon(self):
        fake_id = str(uuid.uuid4())
        with pytest.raises(NonExistentAddon):
            self.svc.get_addon_connection_status(fake_id, self.user.id)


# ---------------------------------------------------------------------------
# check_and_update_pending_authorizations
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCheckPendingAuthorizations:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.addon, _ = _setup_addon(self.user)

    @patch.object(AddonsService, "_check_connection_status")
    def test_updates_active(self, mock_check):
        mock_check.return_value = (True, "ACTIVE")
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        ua = UserMarketplaceAddons.objects.get(id=reg.user_addon_id)
        ua.config_id = "conn_pend"
        ua.auth_link = "https://composio.dev/auth"
        ua.save()
        results = self.svc.check_and_update_pending_authorizations(self.user.id)
        assert len(results) == 1
        assert results[0]["updated"] is True
        ua.refresh_from_db()
        assert ua.auth_complete is True

    @patch.object(AddonsService, "_check_connection_status")
    def test_handles_errors(self, mock_check):
        mock_check.side_effect = Exception("network error")
        reg = self.svc.register_addon(self.request, str(self.addon.id))
        ua = UserMarketplaceAddons.objects.get(id=reg.user_addon_id)
        ua.config_id = "conn_err"
        ua.auth_link = "https://composio.dev/auth"
        ua.save()
        results = self.svc.check_and_update_pending_authorizations(self.user.id)
        assert len(results) == 1
        assert results[0]["status"] == "ERROR"
        assert results[0]["updated"] is False


# ---------------------------------------------------------------------------
# Composio integration methods (mocked)
# ---------------------------------------------------------------------------
class TestComposioIntegration:
    def setup_method(self):
        self.svc = _make_service(MagicMock())

    @patch.object(AddonsService, "_get_composio")
    def test_get_auth_link(self, mock_composio):
        mock_session = MagicMock()
        mock_conn = MagicMock()
        mock_conn.redirect_url = "https://composio.dev/auth/link"
        mock_conn.id = "config_abc"
        mock_session.authorize.return_value = mock_conn
        mock_composio.return_value.create.return_value = mock_session

        result = self.svc._get_auth_link("user_1", "SLACK")
        assert result == ("https://composio.dev/auth/link", "config_abc")

    @patch.object(AddonsService, "_get_composio")
    def test_check_service_auth_true(self, mock_composio):
        mock_toolkit = MagicMock()
        mock_toolkit.slug = "SLACK"
        mock_toolkit.connection.is_active = True
        mock_session = MagicMock()
        mock_session.toolkits.return_value.items = [mock_toolkit]
        mock_composio.return_value.create.return_value = mock_session

        result = self.svc._check_service_auth("user_1", "SLACK")
        assert result is True

    @patch.object(AddonsService, "_get_composio")
    def test_check_service_auth_false(self, mock_composio):
        mock_session = MagicMock()
        mock_session.toolkits.return_value.items = []
        mock_composio.return_value.create.return_value = mock_session

        result = self.svc._check_service_auth("user_1", "SLACK")
        assert result is False

    @patch.object(AddonsService, "_get_composio")
    def test_check_connection_status(self, mock_composio):
        mock_account = MagicMock()
        mock_account.status = "ACTIVE"
        mock_composio.return_value.connected_accounts.get.return_value = mock_account

        result = self.svc._check_connection_status("config_123")
        assert result == (True, "ACTIVE")

    @patch.object(AddonsService, "_get_composio")
    def test_check_connection_status_failure(self, mock_composio):
        mock_composio.return_value.connected_accounts.get.side_effect = Exception("err")

        result = self.svc._check_connection_status("config_bad")
        assert result == (False, "UNKNOWN")

    @patch.object(AddonsService, "_get_composio")
    def test_get_tools_info(self, mock_composio):
        mock_tool = MagicMock()
        mock_tool.to_dict.return_value = {
            "name": "send_message",
            "description": "Send a message",
        }
        mock_composio.return_value.tools.get_raw_composio_tools.return_value = [
            mock_tool
        ]

        result = self.svc._get_tools_info("SLACK")
        assert len(result) == 1
        assert result[0]["name"] == "send_message"

    @patch.object(AddonsService, "_get_composio")
    def test_get_tools_info_no_tools(self, mock_composio):
        mock_composio.return_value.tools.get_raw_composio_tools.return_value = []
        with pytest.raises(NoToolsFound):
            self.svc._get_tools_info("EMPTY_ENUM")
