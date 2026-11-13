"""Django app configuration for the workspace app."""

from django.apps import AppConfig


class WorkspaceConfig(AppConfig):
    """Configuration for the workspace Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    label = "workspace"
    name = "apps." + label
