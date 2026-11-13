"""Shared fixtures for spaces tests."""

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Provide a valid Fernet key so that UserFactory works with EncryptedCharField."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PII_ENCRYPTION_KEY", key)


@pytest.fixture(autouse=True)
def _auto_enable_enterprise():
    """Auto-create EnterpriseConfig(enabled=True) for every new User.

    Share endpoints are gated behind enterprise mode.
    """
    from django.db.models.signals import post_save

    from apps.workspace.models import EnterpriseConfig

    def _enable(sender, instance, created, **kwargs):
        if created:
            EnterpriseConfig.objects.get_or_create(
                user=instance,
                defaults={"enabled": True},
            )

    from apps.users.models import User

    post_save.connect(_enable, sender=User)
    yield
    post_save.disconnect(_enable, sender=User)
