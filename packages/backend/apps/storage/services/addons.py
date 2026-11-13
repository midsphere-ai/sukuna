"""Service layer for marketplace addon registration, authentication, and search."""

from functools import cached_property
from typing import List, Optional

from circuitbreaker import CircuitBreakerError, circuit
from composio import Composio
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, QuerySet, Value, When

from apps.storage.errors import (
    AddonAlreadyRegistered,
    AddonError,
    AddonNotAuthorised,
    AlreadyAuthorised,
    AuthLinkAlreadyExists,
    AuthLinkNotExpired,
    NonExistentAddon,
    NoToolsFound,
    RegisterFailed,
    UnRegisterFailed,
)
from apps.storage.models import MarketplaceAddon, UserMarketplaceAddons
from apps.storage.schemas.addons import (
    AddonAuthenticationStatus,
    AddonAuthLink,
    RegisterAddonResult,
    UnRegisterAddonResult,
    UserAndUserAddonObject,
)
from config.errors.common import (
    FileProcessingError,
    InvalidInputError,
    UnauthorizedAccessError,
)
from config.services.base import BaseService


class AddonsService(BaseService):
    """Service handling marketplace addon registration, auth flows, and search via Composio."""

    SERVICE_NAME = "addons_service"
    SERVICE_VERSION = "1.0.0"

    def __init__(self, **kwargs):
        """Initialize AddonsService with base infrastructure."""
        super().__init__(**kwargs)

    @cached_property
    def config(self):
        """Service configuration."""
        return {
            "version": "1.0.0",
            "extensions_limit": getattr(settings, "EXTENSIONS_LIMIT", 50),
            "per_user_extension_limit": getattr(
                settings, "PER_USER_EXTENSIONS_LIMIT", 4
            ),
            "cache_timeout": getattr(settings, "MEMORY_CACHE_TIMEOUT", 3600),  # 1 hour
        }

    def _map_and_log_error(self, e: Exception, context: str) -> Exception:
        """Map raw exceptions to domain-specific errors."""
        known_exceptions = (
            RegisterFailed,
            AddonAlreadyRegistered,
            UnauthorizedAccessError,
            InvalidInputError,
            AlreadyAuthorised,
            AddonNotAuthorised,
            UnRegisterFailed,
            AuthLinkAlreadyExists,
            AuthLinkNotExpired,
            FileProcessingError,
            NoToolsFound,
            NonExistentAddon,
        )

        if isinstance(e, known_exceptions):
            self._logger.info(f"AddonError in {context}: {e}")
            return e

        if isinstance(e, CircuitBreakerError):
            self._logger.warning(f"CircuitBreakerError in {context}: {e}")
            return AddonError(
                "Auth services temporarily unavailable, please try again later"
            )

        if isinstance(e, ValidationError):
            self._logger.warning(f"Validation error in {context}: {e}")
            return InvalidInputError(str(e))

        self._logger.error(f"Unexpected error in {context}: {e}", exc_info=True)
        return AddonError(f"An unexpected error occurred: {e}")

    def register_addon(
        self, request: WSGIRequest, addon_id: str
    ) -> RegisterAddonResult:
        """Register a marketplace addon for the authenticated user.

        Args:
            request: The HTTP request with authenticated user.
            addon_id: The marketplace addon ID to register.

        Returns:
            RegisterAddonResult: Result containing the new user addon ID.

        Raises:
            NonExistentAddon: If the addon does not exist.
            AddonAlreadyRegistered: If the user already registered this addon.
            AddonError: If the user's addon limit has been reached.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            user_subscription = self._get_user_subscription(user)

            addon_uuid = self._validate_uuid(addon_id)
            marketplace_addon = MarketplaceAddon.objects.get_by_id_with_user_prefetch(
                addon_id=addon_uuid, user_id=user.id
            )

            if not marketplace_addon:
                raise NonExistentAddon("Addon does not exists")

            if (
                hasattr(marketplace_addon, "user_specific_addons")
                and marketplace_addon.user_specific_addons
            ):
                raise AddonAlreadyRegistered("Addon has already been registered")

            with transaction.atomic():
                user_addon_object = UserMarketplaceAddons.objects.create_registration(
                    marketplace_addon=marketplace_addon, owner=user
                )
                self._logger.info(
                    f"New user addon {user_addon_object.id} has been created"
                )

            cache_key = self._get_cache_key("user_addon", f"{user_addon_object.id}")
            self._cache_set(cache_key, user_addon_object, self.config["cache_timeout"])
            return RegisterAddonResult(user_addon_id=user_addon_object.id, is_new=True)

    def unregister_addon(
        self, request: WSGIRequest, user_addon_id: str
    ) -> UnRegisterAddonResult:
        """Unregister and delete a user's addon.

        Args:
            request: The HTTP request with authenticated user.
            user_addon_id: The user addon ID to unregister.

        Returns:
            UnRegisterAddonResult: Result confirming removal.
        """
        with self._handle_service_errors():
            validation_response = self._get_user_and_user_addon_object(
                request, user_addon_id
            )
            user_addon_object = validation_response.user_addon_object
            cache_key = validation_response.cache_key

            with transaction.atomic():
                user_addon_object.delete()
                self._logger.info(f"User addon {user_addon_id} has been unregistered")

            self._cache_delete(cache_key)
            return UnRegisterAddonResult(user_addon_id=user_addon_id, removed=True)

    def get_addon_auth_link(
        self, request: WSGIRequest, user_addon_id: str
    ) -> AddonAuthLink:
        """Get or generate a Composio OAuth authentication link for an addon.

        Args:
            request: The HTTP request with authenticated user.
            user_addon_id: The user addon ID to get the auth link for.

        Returns:
            AddonAuthLink: The authentication link for the addon.

        Raises:
            AlreadyAuthorised: If the addon is already authorized.
            AddonError: If Composio fails to generate an auth link.
        """

        with self._handle_service_errors():
            validation_response = self._get_user_and_user_addon_object(
                request, user_addon_id
            )
            user = validation_response.user
            user_addon_object = validation_response.user_addon_object
            cache_key = validation_response.cache_key

            if user_addon_object.auth_complete:
                raise AlreadyAuthorised("You already have authorised this addon")

            if user_addon_object.auth_link:
                return AddonAuthLink(
                    user_addon_id=user_addon_id, auth_link=user_addon_object.auth_link
                )

            auth_link, auth_config_id = self._get_auth_link(
                user.id, user_addon_object.enabled_addon.enum
            )
            if not auth_link:
                raise AddonError("Composio failed to generate auth link")

            with transaction.atomic():
                user_addon_object.auth_link = auth_link
                user_addon_object.config_id = auth_config_id
                user_addon_object.save()
                self._logger.info(
                    f"User addon {user_addon_id} has generated a auth link for composio"
                )

            self._cache_set(cache_key, user_addon_object, self.config["cache_timeout"])
            return AddonAuthLink(
                user_addon_id=user_addon_id, auth_link=user_addon_object.auth_link
            )

    def check_and_update_auth_status(
        self, request: WSGIRequest, user_addon_id: str
    ) -> AddonAuthenticationStatus:
        """Check Composio connection status and update the addon's auth_complete flag.

        Args:
            request: The HTTP request with authenticated user.
            user_addon_id: The user addon ID to check.

        Returns:
            AddonAuthenticationStatus: Current authorization status.
        """
        with self._handle_service_errors():
            validation_response = self._get_user_and_user_addon_object(
                request, user_addon_id
            )
            user = validation_response.user
            user_addon_object = validation_response.user_addon_object
            cache_key = validation_response.cache_key

            # Use direct connection status lookup if config_id is available (more efficient)
            if user_addon_object.config_id:
                is_active, connection_status = self._check_connection_status(
                    user_addon_object.config_id
                )
                self._logger.info(
                    f"Connection status for addon {user_addon_id}: {connection_status}"
                )
            else:
                # Fallback to toolkit iteration if no config_id
                is_active = self._check_service_auth(
                    user.id, user_addon_object.enabled_addon.enum
                )
                connection_status = "ACTIVE" if is_active else "UNKNOWN"

            with transaction.atomic():
                self._logger.info(
                    f"Marking User addon {user_addon_id} as auth_complete = {is_active}"
                )
                user_addon_object.auth_complete = is_active
                user_addon_object.save()

            self._cache_set(cache_key, user_addon_object, self.config["cache_timeout"])
            return AddonAuthenticationStatus(
                user_addon_id=user_addon_id, is_authorised=is_active
            )

    def regenerate_auth_link(
        self, request: WSGIRequest, user_addon_id: str
    ) -> AddonAuthLink:
        """Regenerate an expired or failed authentication link.

        This method allows users to get a new auth link when their previous one has
        expired, failed, or was never completed. It will NOT regenerate if the addon
        is already authorized (ACTIVE).

        Args:
            request: The HTTP request with authenticated user
            user_addon_id: The user addon ID to regenerate auth link for

        Returns:
            AddonAuthLink: The newly generated auth link

        Raises:
            AlreadyAuthorised: If the addon is already authorized
            AuthLinkNotExpired: If the current link is still valid (INITIATED/PENDING)
        """
        with self._handle_service_errors():
            validation_response = self._get_user_and_user_addon_object(
                request, user_addon_id
            )
            user = validation_response.user
            user_addon_object = validation_response.user_addon_object
            cache_key = validation_response.cache_key

            # Check if already authorized
            if user_addon_object.auth_complete:
                raise AlreadyAuthorised("This addon is already authorized")

            # Check current connection status if config_id exists
            if user_addon_object.config_id:
                is_active, connection_status = self._check_connection_status(
                    user_addon_object.config_id
                )

                if is_active:
                    # Update auth_complete and raise error
                    with transaction.atomic():
                        user_addon_object.auth_complete = True
                        user_addon_object.save()
                    self._cache_set(
                        cache_key, user_addon_object, self.config["cache_timeout"]
                    )
                    raise AlreadyAuthorised("This addon is already authorized")

                # Only allow regeneration for expired, failed, or inactive connections
                allowed_statuses = {"EXPIRED", "FAILED", "INACTIVE", "UNKNOWN"}
                if connection_status not in allowed_statuses:
                    raise AuthLinkNotExpired(
                        f"Cannot regenerate auth link. Current status is '{connection_status}'. "
                        f"Regeneration is only allowed for: {', '.join(allowed_statuses)}"
                    )

            # Generate new auth link
            auth_link, auth_config_id = self._get_auth_link(
                user.id, user_addon_object.enabled_addon.enum
            )
            if not auth_link:
                raise AddonError("Composio failed to generate auth link")

            # Update the addon with new auth link and config_id
            with transaction.atomic():
                user_addon_object.auth_link = auth_link
                user_addon_object.config_id = auth_config_id
                user_addon_object.auth_complete = False
                user_addon_object.save()
                self._logger.info(
                    f"Regenerated auth link for user addon {user_addon_id}"
                )

            self._cache_set(cache_key, user_addon_object, self.config["cache_timeout"])
            return AddonAuthLink(user_addon_id=user_addon_id, auth_link=auth_link)

    def get_user_addons(
        self, request: WSGIRequest
    ) -> Optional[QuerySet[UserMarketplaceAddons]]:
        """Get all registered addons for the authenticated user.

        Args:
            request: The HTTP request with authenticated user.

        Returns:
            QuerySet[UserMarketplaceAddons]: The user's registered addons.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            return UserMarketplaceAddons.objects.for_user(user)

    def check_and_update_pending_authorizations(self, user_id: int) -> list[dict]:
        """Check and update all pending authorizations for a user.

        This method is designed to be called from Celery tasks to periodically
        check pending authorizations and update their status.

        Args:
            user_id: The user's ID

        Returns:
            List of dicts with update results: [{addon_id, status, updated}]
        """
        with self._handle_service_errors():
            pending_addons = UserMarketplaceAddons.objects.pending_authorizations(
                user_id
            )

            results = []
            for addon in pending_addons:
                try:
                    is_active, connection_status = self._check_connection_status(
                        addon.config_id
                    )

                    if is_active:
                        with transaction.atomic():
                            addon.auth_complete = True
                            addon.save()
                            self._logger.info(
                                f"Auto-updated addon {addon.id} to auth_complete=True"
                            )

                    results.append(
                        {
                            "addon_id": str(addon.id),
                            "addon_name": addon.enabled_addon.name,
                            "status": connection_status,
                            "updated": is_active,
                        }
                    )
                except Exception as e:
                    self._logger.warning(
                        f"Failed to check pending auth for addon {addon.id}: {e}"
                    )
                    results.append(
                        {
                            "addon_id": str(addon.id),
                            "addon_name": addon.enabled_addon.name,
                            "status": "ERROR",
                            "updated": False,
                            "error": str(e),
                        }
                    )

            return results

    def get_addon_connection_status(self, user_addon_id: str, user_id: int) -> dict:
        """Get the current connection status for an addon.

        This is a lightweight status check that doesn't require a full request object.

        Args:
            user_addon_id: The user addon ID
            user_id: The user ID (for ownership validation)

        Returns:
            Dict with connection info: {addon_id, status, is_active, auth_complete}
        """
        with self._handle_service_errors():
            addon_uuid = self._validate_uuid(user_addon_id)
            addon = UserMarketplaceAddons.objects.get_by_id(addon_uuid)
            if addon is None:
                raise NonExistentAddon("Addon not found")
            if addon.owner_id != user_id:
                raise UnauthorizedAccessError("Not authorized to access this addon")

            if addon.config_id:
                is_active, connection_status = self._check_connection_status(
                    addon.config_id
                )
            else:
                is_active = addon.auth_complete
                connection_status = "ACTIVE" if is_active else "NOT_INITIATED"

            return {
                "addon_id": str(addon.id),
                "addon_name": addon.enabled_addon.name,
                "status": connection_status,
                "is_active": is_active,
                "auth_complete": addon.auth_complete,
            }

    def get_all_addons(self) -> Optional[QuerySet[MarketplaceAddon]]:
        """Get all available marketplace addons.

        Returns:
            QuerySet[MarketplaceAddon]: All marketplace addons.
        """
        with self._handle_service_errors():
            return MarketplaceAddon.objects.get_all()

    def search_user_addons(
        self, request: WSGIRequest, query: str, auth_complete: bool
    ) -> Optional[QuerySet[UserMarketplaceAddons]]:
        """Search user addons by query with relevance-based ranking.

        Args:
            request: The HTTP request with authenticated user.
            query: The search query string.
            auth_complete: Filter by authentication completion status.

        Returns:
            QuerySet[UserMarketplaceAddons]: Matching addons ranked by relevance.

        Raises:
            InvalidInputError: If the query is empty.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)

            if not query or not query.strip():
                raise InvalidInputError("Query cannot be empty")

            query_lower = query.lower().strip()
            terms = query_lower.split()

            # Build search conditions for addon fields and config
            addon_name_q = Q()
            addon_desc_q = Q()
            config_q = Q()

            for term in terms:
                addon_name_q |= Q(enabled_addon__name__icontains=term)
                addon_desc_q |= Q(enabled_addon__description__icontains=term)
                config_q |= Q(config_id__icontains=term)

            base_queryset = (
                UserMarketplaceAddons.objects.select_related("enabled_addon", "owner")
                .annotate(
                    # Exact addon name match = 15 points
                    exact_addon_name=Case(
                        When(enabled_addon__name__iexact=query_lower, then=Value(15)),
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                    # Addon name contains = 10 points
                    addon_name_match=Case(
                        When(addon_name_q, then=Value(10)),
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                    # Addon description contains = 5 points
                    addon_desc_match=Case(
                        When(addon_desc_q, then=Value(5)),
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                    # Config ID contains = 3 points
                    config_match=Case(
                        When(config_q, then=Value(3)),
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                    # Auth complete bonus = +2 points
                    auth_bonus=Case(
                        When(auth_complete=True, then=Value(2)),
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                )
                .annotate(
                    relevance=F("exact_addon_name")
                    + F("addon_name_match")
                    + F("addon_desc_match")
                    + F("config_match")
                    + F("auth_bonus")
                )
                .filter(owner=user, relevance__gt=0)
            )

        if auth_complete is not None:
            base_queryset = base_queryset.filter(auth_complete=auth_complete)

        return base_queryset.order_by("-relevance", "enabled_addon__name").distinct()

    def search_marketplace_addons(
        self, query: str
    ) -> Optional[QuerySet[UserMarketplaceAddons]]:
        """Search marketplace addons by query with relevance-based ranking.

        Args:
            query: The search query string.

        Returns:
            QuerySet[MarketplaceAddon]: Matching marketplace addons ranked by relevance.
        """
        with self._handle_service_errors():
            query_lower = query.lower().strip()
            terms = query_lower.split()

            # Build search conditions
            name_q = Q()
            desc_q = Q()
            enum_q = Q()

            for term in terms:
                name_q |= Q(name__icontains=term)
                desc_q |= Q(description__icontains=term)
                enum_q |= Q(enum__icontains=term)

            queryset = MarketplaceAddon.objects.annotate(
                # Exact name match = 20 points
                exact_name=Case(
                    When(name__iexact=query_lower, then=Value(20)),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                # Name starts with query = 15 points
                name_starts=Case(
                    When(name__istartswith=query_lower, then=Value(15)),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                # Name contains = 10 points
                name_contains=Case(
                    When(name_q, then=Value(10)),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                # Description contains = 5 points
                desc_contains=Case(
                    When(desc_q, then=Value(5)),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                # Enum contains = 3 points
                enum_contains=Case(
                    When(enum_q, then=Value(3)),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
            ).annotate(
                relevance=F("exact_name")
                + F("name_starts")
                + F("name_contains")
                + F("desc_contains")
                + F("enum_contains")
            )
            return (
                queryset.filter(relevance__gt=0)
                .order_by("-relevance", "name")
                .distinct()
            )

    def get_expanded_addon(self, request: WSGIRequest, addon_id: str) -> Optional[dict]:
        """Get expanded addon details including marketplace info, user registration, and tool features.

        Args:
            request: The HTTP request with authenticated user.
            addon_id: The marketplace addon ID to expand.

        Returns:
            dict: Expanded addon details with 'marketplace_addon', 'user_addon', and 'features' keys.

        Raises:
            NonExistentAddon: If the marketplace addon does not exist.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            addon_uuid = self._validate_uuid(addon_id)
            marketplace_object = MarketplaceAddon.objects.get_by_id_with_user_prefetch(
                addon_id=addon_uuid, user_id=user.id
            )

            if not marketplace_object:
                raise NonExistentAddon("Marketplace object does not exists")

            user_addon_object = None
            user_specific_addons = getattr(
                marketplace_object, "user_specific_addons", None
            )
            if user_specific_addons:
                user_addon_object = user_specific_addons[0]

            expanded_details = {
                "user_addon": user_addon_object,
                "marketplace_addon": marketplace_object,
                "features": self._get_tools_info(marketplace_object.enum),
            }
            return expanded_details

    def _get_user_and_user_addon_object(
        self, request: WSGIRequest, user_addon_id: str
    ) -> UserAndUserAddonObject:
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)

            cache_key = self._get_cache_key("user_addon", f"{user_addon_id}")
            user_addon_object = self._cache_service.get(cache_key)

            if not user_addon_object:
                addon_uuid = self._validate_uuid(user_addon_id)
                user_addon_object = UserMarketplaceAddons.objects.get_by_id(addon_uuid)

            if user_addon_object is None:
                raise NonExistentAddon("User addon not found")

            if user_addon_object.owner != user:
                raise UnauthorizedAccessError("You are not the owner of this addon")

            return UserAndUserAddonObject(
                user=user, user_addon_object=user_addon_object, cache_key=cache_key
            )

    def _get_composio(self) -> Composio:
        return Composio()

    @circuit(failure_threshold=3, recovery_timeout=30)
    def _get_auth_link(self, user_id: str, enum: str) -> Optional[tuple]:
        with self._handle_service_errors():
            composio = self._get_composio()
            session = composio.create(user_id=f"{enum}:{user_id}")
            connection_request = session.authorize(enum)
            return (connection_request.redirect_url, connection_request.id)

    @circuit(failure_threshold=3, recovery_timeout=30)
    def _check_service_auth(self, user_id: str, enum: str) -> Optional[bool]:
        """Check if user has authorized the addon service by iterating toolkits.

        Note: This is a fallback method. Prefer _check_connection_status() when
        config_id is available for more efficient direct API lookup.
        """
        with self._handle_service_errors():
            composio = self._get_composio()
            session = composio.create(user_id=f"{enum}:{user_id}")
            toolkits = session.toolkits()
            for t in toolkits.items:
                if t.slug == enum and t.connection.is_active:
                    return True
            return False

    @circuit(failure_threshold=3, recovery_timeout=30)
    def _check_connection_status(self, config_id: str) -> tuple[bool, str]:
        """Check connection status directly by connected account ID.

        Uses Composio's connected_accounts.get() API for efficient direct lookup.

        Args:
            config_id: The connected account ID (stored during authorize flow)

        Returns:
            Tuple of (is_active: bool, status: str)
            Status values: ACTIVE, INITIATED, PENDING, EXPIRED, FAILED, INACTIVE
        """
        with self._handle_service_errors():
            composio = self._get_composio()
            try:
                connected_account = composio.connected_accounts.get(config_id)
                status = connected_account.status
                is_active = status == "ACTIVE"
                return (is_active, status)
            except Exception as e:
                self._logger.warning(
                    f"Failed to get connection status for {config_id}: {e}"
                )
                return (False, "UNKNOWN")

    @circuit(failure_threshold=3, recovery_timeout=30)
    def _get_tools_info(self, enum) -> List[dict]:
        with self._handle_service_errors():
            composio = self._get_composio()
            tools = composio.tools.get_raw_composio_tools(toolkits=[enum], limit=99)
            if not tools:
                raise NoToolsFound("No tools have returned from composio")

            feature_map = []
            for tool in tools:
                tool = tool.to_dict()
                tool_info = {"name": tool["name"], "description": tool["description"]}
                feature_map.append(tool_info)

            return feature_map


def build_composio_marketplace():
    """Rebuild the marketplace addons table from the full Composio toolkits catalog.

    Warning: This deletes all existing marketplace addons and user registrations.
    """
    UserMarketplaceAddons.objects.all().delete()
    MarketplaceAddon.objects.all().delete()
    composio = Composio()
    toolkits = composio.toolkits.list(limit=1000).items

    for tool in toolkits:
        tool = tool.to_dict()
        name = tool["name"]
        description = tool["meta"]["description"]
        logo = tool["meta"]["logo"]
        link = tool["meta"]["app_url"]
        enum = tool["slug"]

        MarketplaceAddon.objects.create(
            name=name, description=description, logo=logo, link=link, enum=enum
        )
