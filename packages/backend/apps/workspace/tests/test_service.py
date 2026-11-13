"""Unit tests for WorkspaceService business logic."""

import logging
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.users.models import User
from apps.users.tests.factories import UserFactory
from apps.workspace.models import PasswordResetOTP
from apps.workspace.services.workspace import (
    OTP_RATE_LIMIT_MAX,
    WorkspaceService,
)
from config.errors.common import (
    InvalidInputError,
    NotFoundError,
    UnauthorizedAccessError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(user=None):
    svc = WorkspaceService.__new__(WorkspaceService)
    svc._user_service = MagicMock()
    svc._cache_service = MagicMock()
    svc._logger = logging.getLogger("test.workspace")
    svc._service_kwargs = {}
    if user:
        svc._get_authenticated_user = MagicMock(return_value=user)
    return svc


# ---------------------------------------------------------------------------
# _map_and_log_error
# ---------------------------------------------------------------------------
class TestWorkspaceErrorMapping:
    def setup_method(self):
        self.svc = _make_service()

    def test_known_error_passthrough(self):
        e = InvalidInputError("bad")
        assert self.svc._map_and_log_error(e, "ctx") is e

    def test_integrity_error(self):
        from django.db.utils import IntegrityError

        e = IntegrityError("dup")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, InvalidInputError)

    def test_does_not_exist(self):
        e = User.DoesNotExist("gone")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, NotFoundError)

    def test_validation_error(self):
        from django.core.exceptions import ValidationError

        e = ValidationError("bad")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, InvalidInputError)

    def test_unexpected_error(self):
        e = RuntimeError("boom")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, Exception)
        assert "unexpected" in str(result).lower()


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateUser:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svc = _make_service()

    def test_success(self):
        user = self.svc.create_user("Test User", "create@test.com", "Pass1234!")
        assert user.name == "Test User"
        assert user.email == "create@test.com"
        assert user.is_active is True
        assert user.check_password("Pass1234!")

    def test_empty_name(self):
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            self.svc.create_user("", "e@test.com", "Pass1234!")

    def test_empty_email(self):
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            self.svc.create_user("Name", "", "Pass1234!")

    def test_empty_password(self):
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            self.svc.create_user("Name", "e@test.com", "")

    def test_duplicate_email(self):
        self.svc.create_user("First", "dup@test.com", "Pass1234!")
        with pytest.raises(InvalidInputError, match="already exists"):
            self.svc.create_user("Second", "dup@test.com", "Pass1234!")


# ---------------------------------------------------------------------------
# get_user_by_id
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetUserById:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svc = _make_service()
        self.user = UserFactory()

    def test_success(self):
        result = self.svc.get_user_by_id(self.user.id)
        assert result.id == self.user.id

    def test_not_found(self):
        with pytest.raises(NotFoundError):
            self.svc.get_user_by_id(99999)


# ---------------------------------------------------------------------------
# get_user_by_token_sync
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetUserByTokenSync:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svc = _make_service()
        self.user = UserFactory()
        from dj_rest_auth.models import get_token_model

        Token = get_token_model()
        self.token, _ = Token.objects.get_or_create(user=self.user)

    def test_success(self):
        result = self.svc.get_user_by_token_sync(self.token.key)
        assert result.id == self.user.id

    def test_empty_token(self):
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            self.svc.get_user_by_token_sync("")

    def test_invalid_token(self):
        with pytest.raises(NotFoundError):
            self.svc.get_user_by_token_sync("nonexistent_token_key")


# ---------------------------------------------------------------------------
# remove_user
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRemoveUser:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svc = _make_service()
        self.user = UserFactory()

    def test_success(self):
        uid = self.user.id
        self.svc.remove_user(self.user, str(uid))
        assert User.objects.filter(id=uid).count() == 0

    def test_empty_id(self):
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            self.svc.remove_user(self.user, "")

    def test_user_not_found(self):
        with pytest.raises(NotFoundError, match="not found"):
            self.svc.remove_user(self.user, "99999")

    def test_wrong_user(self):
        other = UserFactory()
        with pytest.raises(UnauthorizedAccessError, match="own account"):
            self.svc.remove_user(other, str(self.user.id))


# ---------------------------------------------------------------------------
# modify_user
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestModifyUser:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svc = _make_service()
        self.user = UserFactory()

    def test_modify_name(self):
        result = self.svc.modify_user(
            self.user, str(self.user.id), {"user_name": "New Name"}
        )
        assert result.name == "New Name"

    def test_modify_email(self):
        result = self.svc.modify_user(
            self.user, str(self.user.id), {"user_email": "new@test.com"}
        )
        assert result.email == "new@test.com"

    def test_modify_occupation(self):
        result = self.svc.modify_user(
            self.user, str(self.user.id), {"occupation": "Engineer"}
        )
        assert result.occupation == "Engineer"

    def test_modify_wrong_user(self):
        other = UserFactory()
        with pytest.raises(UnauthorizedAccessError, match="own profile"):
            self.svc.modify_user(other, str(self.user.id), {"user_name": "hack"})

    def test_modify_empty_id(self):
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            self.svc.modify_user(self.user, "", {})


# ---------------------------------------------------------------------------
# _generate_otp
# ---------------------------------------------------------------------------
class TestGenerateOTP:
    def test_default_length(self):
        otp = WorkspaceService._generate_otp()
        assert len(otp) == 6
        assert otp.isdigit()

    def test_custom_length(self):
        otp = WorkspaceService._generate_otp(length=8)
        assert len(otp) == 8
        assert otp.isdigit()

    def test_uniqueness(self):
        otps = {WorkspaceService._generate_otp() for _ in range(100)}
        # With 6-digit OTPs and 100 trials, should have significant variety
        assert len(otps) > 50


# ---------------------------------------------------------------------------
# request_password_reset_otp
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRequestPasswordResetOTP:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svc = _make_service()
        self.user = UserFactory()
        cache.clear()

    def test_empty_email(self):
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            self.svc.request_password_reset_otp("")

    def test_success(self):
        with patch.object(self.svc, "_send_otp_email", return_value=True):
            success, msg = self.svc.request_password_reset_otp(self.user.email)
        assert success is True
        assert "OTP has been sent" in msg
        assert PasswordResetOTP.objects.filter(user=self.user, used=False).count() == 1

    def test_nonexistent_email(self):
        """Should return success to prevent email enumeration."""
        success, msg = self.svc.request_password_reset_otp("nobody@test.com")
        assert success is True

    def test_invalidates_old_otps(self):
        PasswordResetOTP.objects.create(
            user=self.user,
            otp="111111",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        with patch.object(self.svc, "_send_otp_email", return_value=True):
            self.svc.request_password_reset_otp(self.user.email)
        assert PasswordResetOTP.objects.filter(user=self.user, used=True).count() == 1

    def test_rate_limiting(self):
        cache.set(f"otp_request:{self.user.email}", OTP_RATE_LIMIT_MAX, 900)
        success, msg = self.svc.request_password_reset_otp(self.user.email)
        assert success is False
        assert "Too many" in msg

    def test_email_send_failure(self):
        with patch.object(self.svc, "_send_otp_email", return_value=False):
            success, msg = self.svc.request_password_reset_otp(self.user.email)
        assert success is False
        assert "Failed" in msg


# ---------------------------------------------------------------------------
# verify_otp
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestVerifyOTP:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svc = _make_service()
        self.user = UserFactory()
        cache.clear()
        self.otp = PasswordResetOTP.objects.create(
            user=self.user,
            otp="123456",
            expires_at=timezone.now() + timedelta(minutes=15),
        )

    def test_empty_fields(self):
        with pytest.raises(InvalidInputError, match="required"):
            self.svc.verify_otp("", "123456")

    def test_success(self):
        success, msg = self.svc.verify_otp(self.user.email, "123456")
        assert success is True
        assert "verified" in msg

    def test_wrong_otp(self):
        success, msg = self.svc.verify_otp(self.user.email, "000000")
        assert success is False
        assert "Invalid" in msg

    def test_expired_otp(self):
        self.otp.expires_at = timezone.now() - timedelta(minutes=1)
        self.otp.save()
        success, msg = self.svc.verify_otp(self.user.email, "123456")
        assert success is False
        assert "expired" in msg

    def test_nonexistent_email(self):
        success, msg = self.svc.verify_otp("nope@test.com", "123456")
        assert success is False

    def test_rate_limiting(self):
        cache.set(f"otp_verify:{self.user.email}", OTP_RATE_LIMIT_MAX, 900)
        success, msg = self.svc.verify_otp(self.user.email, "123456")
        assert success is False
        assert "Too many" in msg


# ---------------------------------------------------------------------------
# verify_otp_and_reset_password
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestVerifyOTPAndResetPassword:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svc = _make_service()
        self.user = UserFactory(password="OldPass123!")
        cache.clear()
        self.otp = PasswordResetOTP.objects.create(
            user=self.user,
            otp="654321",
            expires_at=timezone.now() + timedelta(minutes=15),
        )

    def test_empty_fields(self):
        with pytest.raises(InvalidInputError, match="required"):
            self.svc.verify_otp_and_reset_password("", "654321", "NewPass123!")

    def test_short_password(self):
        with pytest.raises(InvalidInputError, match="8 characters"):
            self.svc.verify_otp_and_reset_password(self.user.email, "654321", "short")

    def test_success(self):
        with patch.object(
            self.svc, "_send_password_reset_confirmation_email", return_value=True
        ):
            success, msg = self.svc.verify_otp_and_reset_password(
                self.user.email, "654321", "NewSecure123!"
            )
        assert success is True
        assert "successfully" in msg
        self.user.refresh_from_db()
        assert self.user.check_password("NewSecure123!")
        # OTP should be marked as used
        self.otp.refresh_from_db()
        assert self.otp.used is True

    def test_wrong_otp(self):
        success, msg = self.svc.verify_otp_and_reset_password(
            self.user.email, "000000", "NewSecure123!"
        )
        assert success is False
        assert "Invalid" in msg

    def test_expired_otp(self):
        self.otp.expires_at = timezone.now() - timedelta(minutes=1)
        self.otp.save()
        success, msg = self.svc.verify_otp_and_reset_password(
            self.user.email, "654321", "NewSecure123!"
        )
        assert success is False
        assert "expired" in msg

    def test_rate_limiting_invalidates_otps(self):
        cache.set(f"otp_verify:{self.user.email}", OTP_RATE_LIMIT_MAX, 900)
        success, msg = self.svc.verify_otp_and_reset_password(
            self.user.email, "654321", "NewSecure123!"
        )
        assert success is False
        assert "invalidated" in msg
        self.otp.refresh_from_db()
        assert self.otp.used is True


# ---------------------------------------------------------------------------
# _send_otp_email / _send_password_reset_confirmation_email
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEmailSending:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svc = _make_service()
        self.user = UserFactory()

    @patch("apps.workspace.services.workspace.send_mail")
    def test_send_otp_email_success(self, mock_mail):
        otp = PasswordResetOTP.objects.create(
            user=self.user,
            otp="999999",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        result = self.svc._send_otp_email(self.user, otp)
        assert result is True
        mock_mail.assert_called_once()

    @patch(
        "apps.workspace.services.workspace.send_mail",
        side_effect=Exception("smtp error"),
    )
    def test_send_otp_email_failure(self, mock_mail):
        otp = PasswordResetOTP.objects.create(
            user=self.user,
            otp="999999",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        result = self.svc._send_otp_email(self.user, otp)
        assert result is False

    @patch("apps.workspace.services.workspace.send_mail")
    def test_send_confirmation_email_success(self, mock_mail):
        result = self.svc._send_password_reset_confirmation_email(self.user)
        assert result is True

    @patch(
        "apps.workspace.services.workspace.send_mail",
        side_effect=Exception("smtp error"),
    )
    def test_send_confirmation_email_failure(self, mock_mail):
        result = self.svc._send_password_reset_confirmation_email(self.user)
        assert result is False
