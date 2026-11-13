"""Django app configuration for the compliance app."""

from django.apps import AppConfig


class ComplianceConfig(AppConfig):
    """Django application configuration for enterprise compliance (audit, GDPR, SOC2)."""

    default_auto_field = "django.db.models.BigAutoField"
    label = "compliance"
    name = "apps." + label

    def ready(self):
        import apps.compliance.signals  # noqa: F401
