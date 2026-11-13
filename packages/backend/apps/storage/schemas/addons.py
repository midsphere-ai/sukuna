"""Request/response schemas and DTOs for addon-related API endpoints."""

from dataclasses import dataclass
from typing import Any, List, Optional

from ninja import ModelSchema, Schema

from apps.storage.models import MarketplaceAddon, UserMarketplaceAddons
from apps.users.models import User


@dataclass(frozen=True)
class AddonBaseResult:
    """Base result DTO carrying an addon ID."""

    addon_id: str


@dataclass(frozen=True)
class UserAddonBaseResult:
    """Base result DTO carrying a user-addon ID."""

    user_addon_id: str


@dataclass(frozen=True)
class RegisterAddonResult(UserAddonBaseResult):
    """Result of registering a marketplace addon for a user."""

    is_new: bool


@dataclass(frozen=True)
class UnRegisterAddonResult(UserAddonBaseResult):
    """Result of unregistering a user addon."""

    removed: bool


@dataclass(frozen=True)
class AddonAuthLink(UserAddonBaseResult):
    """Result containing the Composio OAuth authentication link for an addon."""

    auth_link: str


@dataclass(frozen=True)
class AddonAuthenticationStatus(UserAddonBaseResult):
    """Result indicating whether an addon has completed authentication."""

    is_authorised: bool


@dataclass(frozen=True)
class AddonConnectionStatus(UserAddonBaseResult):
    """Connection status response with detailed Composio status."""

    addon_name: str
    status: str  # ACTIVE, INITIATED, PENDING, EXPIRED, FAILED, INACTIVE, NOT_INITIATED, UNKNOWN
    is_active: bool
    auth_complete: bool


@dataclass(frozen=True)
class UserAndUserAddonObject:
    """Internal DTO bundling a user, their addon object, and the cache key for lookups."""

    user: User
    user_addon_object: UserMarketplaceAddons
    cache_key: str


class MarketplaceAddonModelSchema(ModelSchema):
    """Model schema for Marketplace addon"""

    class Meta:
        model = MarketplaceAddon
        fields = "__all__"


class UserAddonModelSchema(ModelSchema):
    """Model schema for User addons"""

    enabled_addon: Optional[MarketplaceAddonModelSchema]

    class Config:
        from_attributes = True

    class Meta:
        model = UserMarketplaceAddons
        fields = "__all__"


class ExpandedAddon(Schema):
    """Response schema for a marketplace addon with user registration and Composio tool details."""

    marketplace_addon: Optional[MarketplaceAddonModelSchema]
    user_addon: Optional[UserAddonModelSchema]
    features: List[dict[str, Any]]


class RegisterAddon(Schema):
    """Request schema for registering a marketplace addon."""

    addon_id: str


class UserAddonRequest(Schema):
    """Request schema referencing a user addon by ID."""

    user_addon_id: str


class SearchUserAddons(Schema):
    """Request schema for searching user addons."""

    query: str
    auth_complete: bool


class SearchMarketAddons(Schema):
    """Request schema for searching marketplace addons."""

    query: str
