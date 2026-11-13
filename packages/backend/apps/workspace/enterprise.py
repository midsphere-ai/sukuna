"""Enterprise mode gate utilities.

Provides ``require_enterprise`` for checking enterprise mode on authenticated
requests, and ``get_or_create_enterprise_config`` for lazy config provisioning.
"""

from django.utils import timezone

from apps.workspace.models import EnterpriseConfig


class EnterpriseDisabledError(Exception):
    """Raised when an enterprise-gated endpoint is called with enterprise mode off."""

    pass


def get_or_create_enterprise_config(user) -> EnterpriseConfig:
    """Return the user's EnterpriseConfig, creating one (disabled) if missing."""
    config, _ = EnterpriseConfig.objects.get_or_create(user=user)
    return config


def is_enterprise_enabled(user) -> bool:
    """Check whether enterprise mode is active for *user*."""
    try:
        return user.enterprise_config.enabled
    except EnterpriseConfig.DoesNotExist:
        return False


def require_enterprise(request) -> None:
    """Raise ``EnterpriseDisabledError`` if the authenticated user does not
    have enterprise mode enabled.

    Call this at the top of any endpoint that should be gated behind enterprise
    mode. The error handler in ``org_api`` / ``scim_api`` will convert this to
    a 403 response with error code ``enterprise_features_disabled``.
    """
    user = getattr(request, "auth", None) or getattr(request, "user", None)
    if user is None or not is_enterprise_enabled(user):
        raise EnterpriseDisabledError()


def auto_enable_enterprise(user) -> EnterpriseConfig:
    """Enable enterprise mode for *user* if not already enabled.

    Used when accepting an org invite or being SCIM-provisioned — the user
    didn't go to settings first, so we auto-enable.
    """
    config = get_or_create_enterprise_config(user)
    if not config.enabled:
        config.enabled = True
        config.enabled_at = timezone.now()
        config.save(update_fields=["enabled", "enabled_at", "updated_at"])
    return config
