import pytest

from apps.users.models import User
from apps.users.tests.factories import UserFactory


@pytest.fixture
def user(db) -> User:
    return UserFactory()
