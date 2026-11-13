"""Template context processors for the users app."""

from django.conf import settings


def allauth_settings(request):
    """Expose django-allauth registration settings to templates.

    Args:
        request: The current HTTP request.

    Returns:
        A dict containing the ACCOUNT_ALLOW_REGISTRATION setting.
    """
    return {
        "ACCOUNT_ALLOW_REGISTRATION": settings.ACCOUNT_ALLOW_REGISTRATION,
    }
