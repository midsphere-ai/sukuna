"""Root-level pytest configuration and shared fixtures for the Sukuna test suite."""

import pytest

from apps.users.models import User
from apps.users.tests.factories import UserFactory


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    """Override MEDIA_ROOT to use a temporary directory for each test."""
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def user(db) -> User:
    """Create and return a default test user via UserFactory."""
    return UserFactory()
