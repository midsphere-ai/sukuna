"""Django app configuration for the billing app."""

from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    """Django application configuration for billing and payments."""

    default_auto_field = "django.db.models.BigAutoField"
    label = "billing"
    name = "apps." + label

    def ready(self):
        import apps.billing.signals  # noqa: F401
