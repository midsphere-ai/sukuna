"""Unit tests for workspace app models — PasswordResetOTP."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.users.tests.factories import UserFactory
from apps.workspace.models import PasswordResetOTP


@pytest.mark.django_db
class TestPasswordResetOTP:
    def test_str_active(self):
        user = UserFactory()
        otp = PasswordResetOTP.objects.create(
            user=user,
            otp="123456",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        assert user.email in str(otp)
        assert "Active" in str(otp)

    def test_str_used(self):
        user = UserFactory()
        otp = PasswordResetOTP.objects.create(
            user=user,
            otp="123456",
            expires_at=timezone.now() + timedelta(minutes=15),
            used=True,
        )
        assert "Used" in str(otp)

    def test_is_expired_false(self):
        user = UserFactory()
        otp = PasswordResetOTP.objects.create(
            user=user,
            otp="111111",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        assert otp.is_expired is False

    def test_is_expired_true(self):
        user = UserFactory()
        otp = PasswordResetOTP.objects.create(
            user=user,
            otp="222222",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        assert otp.is_expired is True

    def test_is_valid_true(self):
        user = UserFactory()
        otp = PasswordResetOTP.objects.create(
            user=user,
            otp="333333",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        assert otp.is_valid is True

    def test_is_valid_false_when_used(self):
        user = UserFactory()
        otp = PasswordResetOTP.objects.create(
            user=user,
            otp="444444",
            expires_at=timezone.now() + timedelta(minutes=15),
            used=True,
        )
        assert otp.is_valid is False

    def test_is_valid_false_when_expired(self):
        user = UserFactory()
        otp = PasswordResetOTP.objects.create(
            user=user,
            otp="555555",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        assert otp.is_valid is False

    def test_is_valid_false_when_used_and_expired(self):
        user = UserFactory()
        otp = PasswordResetOTP.objects.create(
            user=user,
            otp="666666",
            expires_at=timezone.now() - timedelta(minutes=1),
            used=True,
        )
        assert otp.is_valid is False

    def test_ordering(self):
        user = UserFactory()
        otp1 = PasswordResetOTP.objects.create(
            user=user, otp="111111", expires_at=timezone.now() + timedelta(minutes=15)
        )
        otp2 = PasswordResetOTP.objects.create(
            user=user, otp="222222", expires_at=timezone.now() + timedelta(minutes=15)
        )
        otps = list(PasswordResetOTP.objects.all())
        assert otps[0] == otp2  # newest first

    def test_cascade_delete(self):
        user = UserFactory()
        PasswordResetOTP.objects.create(
            user=user, otp="000000", expires_at=timezone.now() + timedelta(minutes=15)
        )
        user.delete()
        assert PasswordResetOTP.objects.count() == 0

    def test_defaults(self):
        user = UserFactory()
        otp = PasswordResetOTP.objects.create(
            user=user, otp="777777", expires_at=timezone.now() + timedelta(minutes=15)
        )
        assert otp.used is False
        assert otp.created_at is not None
