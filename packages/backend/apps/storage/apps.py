"""Django app configuration for the storage application."""

from django.apps import AppConfig


class MemoryConfig(AppConfig):
    """Configuration for the storage Django app, which manages conversations, files, and addons."""

    default_auto_field = "django.db.models.BigAutoField"
    label = "storage"
    name = "apps." + label

    def ready(self):
        """Register signals when the app is ready."""
        # Import signals to register them
        from apps.storage import signals  # noqa: F401
