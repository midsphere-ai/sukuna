"""Django app configuration for the users application."""

import contextlib

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class UsersConfig(AppConfig):
    """App configuration for the users app, registering signals on startup."""

    name = "apps.users"
    verbose_name = _("Users")

    def ready(self):
        """Import signal handlers when the app is ready."""
        with contextlib.suppress(ImportError):
            import apps.users.signals  # noqa: F401, PLC0415
