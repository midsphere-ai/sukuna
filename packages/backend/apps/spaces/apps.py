"""Django app configuration for the spaces module."""

from django.apps import AppConfig


class SpacesConfig(AppConfig):
    """Configuration class for the spaces Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    label = "spaces"
    name = "apps." + label
