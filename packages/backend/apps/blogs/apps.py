"""Django app configuration for the blogs app."""

from django.apps import AppConfig


class CmsConfig(AppConfig):
    """Configuration class for the blogs (CMS) Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    label = "blogs"
    name = "apps." + label
