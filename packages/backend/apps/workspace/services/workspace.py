"""Workspace service handling user CRUD, authentication tokens, and password reset OTP logic."""

import secrets
import string
from contextlib import contextmanager
from datetime import timedelta
from functools import cached_property

from dj_rest_auth.models import get_token_model
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.utils import IntegrityError
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

from apps.users.models import User
from apps.workspace.models import PasswordResetOTP
from config.errors.common import (
    InvalidInputError,
    NotFoundError,
    UnauthorizedAccessError,
)
from config.services.base import BaseService

# OTP expiration time in minutes
OTP_EXPIRY_MINUTES = 15
# Rate limiting: max attempts per window
OTP_RATE_LIMIT_MAX = 5
OTP_RATE_LIMIT_WINDOW = 15 * 60  # 15 minutes in seconds


class WorkspaceService(BaseService):
    """
    Manages user and workspace-related business logic.

    This services provides a clean, asynchronous interface for creating,
    retrieving, and deleting users, abstracting away the data layer
    and handling all relevant business rules and errors.
    """

    SERVICE_NAME = "workspace_service"
    SERVICE_VERSION = "1.0.0"

    @cached_property
    def config(self):
        """Service configuration."""
        return {"version": "1.0.0"}

    # region Error Handling
    def _map_and_log_error(self, e: Exception, context: str) -> Exception:
        """Maps raw exceptions to domain-specific services errors."""
        known_exceptions = (
            InvalidInputError,
            UnauthorizedAccessError,
            NotFoundError,
        )
        if isinstance(e, known_exceptions):
            self._logger.info(f"Service error in {context}: {e}")
            return e

        if isinstance(e, IntegrityError):
            self._logger.warning(f"IntegrityError in {context}: {e}")
            return InvalidInputError(
                "A resource with the provided details already exists."
            )

        if isinstance(e, (User.DoesNotExist, get_token_model().DoesNotExist)):
            self._logger.info(f"DoesNotExist error in {context}: {e}")
            return NotFoundError("The requested resource was not found.")

        if isinstance(e, ValidationError):
            self._logger.warning(f"Validation error in {context}: {e}")
            return InvalidInputError(str(e))

        self._logger.error(f"Unexpected error in {context}: {e}", exc_info=True)
        return Exception(f"An unexpected internal error occurred: {e}")

    @contextmanager
    def _handle_service_errors(self):
        """Async context manager for consistent error handling."""
        try:
            yield
        except Exception as e:
            raise self._map_and_log_error(e, self.__class__.__name__)

    def create_user(self, name: str, email: str, password: str) -> User:
        """Create a new active user in the system.

        Args:
            name: The user's display name.
            email: The user's email address.
            password: The user's plain-text password (will be hashed).

        Returns:
            The newly created User instance.

        Raises:
            InvalidInputError: If any required field is empty.
        """
        with self._handle_service_errors():
            if not all([name, email, password]):
                raise InvalidInputError("Name, email, and password cannot be empty.")

            with transaction.atomic():
                user = User.objects.create_user(
                    name=name, email=email, password=password, is_active=True
                )
                self._logger.info(f"Successfully created user {user.id} ({user.email})")
                return user

    def get_user_by_id(self, user_id: str) -> User:
        """Retrieve a single user by their UUID.

        Args:
            user_id: The UUID of the user to retrieve.

        Returns:
            The matching User instance.

        Raises:
            NotFoundError: If no user exists with the given ID.
        """
        with self._handle_service_errors():
            return User.objects.get(id=user_id)

    def get_user_by_token_sync(self, token_key: str) -> User:
        """Retrieve the user associated with an authentication token synchronously.

        Args:
            token_key: The authentication token string.

        Returns:
            The User associated with the token.

        Raises:
            InvalidInputError: If the token key is empty.
            NotFoundError: If no token matches the given key.
        """
        with self._handle_service_errors():
            if not token_key:
                raise InvalidInputError("Token key cannot be empty.")

            Token = get_token_model()
            return Token.objects.select_related("user").get(key=token_key).user

    async def get_user_by_token(self, token_key: str) -> User:
        """Retrieve the user associated with an authentication token asynchronously.

        Args:
            token_key: The authentication token string.

        Returns:
            The User associated with the token.

        Raises:
            InvalidInputError: If the token key is empty.
            NotFoundError: If no token matches the given key.
        """
        from asgiref.sync import sync_to_async

        with self._handle_service_errors():
            if not token_key:
                raise InvalidInputError("Token key cannot be empty.")

            Token = get_token_model()
            token_instance = await Token.objects.aget(key=token_key)
            user = await sync_to_async(lambda: token_instance.user)()
            return user

    def remove_user(self, requesting_user: User, user_id: str) -> None:
        """Delete a user account. Only the user themselves can delete their account.

        Args:
            requesting_user: The authenticated user making the request.
            user_id: The UUID of the user to delete.

        Raises:
            InvalidInputError: If the user ID is empty.
            NotFoundError: If the user does not exist.
            UnauthorizedAccessError: If the requesting user is not the account owner.
        """
        with self._handle_service_errors():
            if not user_id:
                raise InvalidInputError("User ID cannot be empty.")

            try:
                user_to_remove = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise NotFoundError("User not found.")

            if str(requesting_user.id) != str(user_to_remove.id):
                raise UnauthorizedAccessError("You can only delete your own account.")

            user_to_remove.delete()
            self._logger.info(f"User {user_id} deleted by {requesting_user.id}")

    def modify_user(self, requesting_user: User, user_id: str, data: dict) -> User:
        """Update a user's profile fields. Only the user themselves can modify their profile.

        Args:
            requesting_user: The authenticated user making the request.
            user_id: The UUID of the user to modify.
            data: Dictionary of fields to update (e.g., user_name, user_email,
                occupation, avatar, nickname).

        Returns:
            The updated User instance.

        Raises:
            InvalidInputError: If the user ID is empty.
            NotFoundError: If the user does not exist.
            UnauthorizedAccessError: If the requesting user is not the account owner.
        """
        with self._handle_service_errors():
            if not user_id:
                raise InvalidInputError("User ID cannot be empty.")

            try:
                user_to_modify = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise NotFoundError("User not found.")

            if str(requesting_user.id) != str(user_to_modify.id):
                raise UnauthorizedAccessError("You can only modify your own profile.")

            from apps.workspace.security import sanitize_display_name

            if "user_name" in data and data["user_name"]:
                user_to_modify.name = (
                    sanitize_display_name(data["user_name"]) or data["user_name"]
                )
            if "user_email" in data and data["user_email"]:
                user_to_modify.email = data["user_email"]
            if "occupation" in data:
                user_to_modify.occupation = data["occupation"] or ""
            if "avatar" in data:
                user_to_modify.avatar = data["avatar"] or ""
            if "nickname" in data:
                user_to_modify.nickname = (
                    sanitize_display_name(data["nickname"]) or data["nickname"]
                    if data["nickname"]
                    else ""
                )

            user_to_modify.save()
            self._logger.info(f"User {user_id} modified by {requesting_user.id}")
            return user_to_modify

    # region Password Reset OTP

    @staticmethod
    def _generate_otp(length: int = 6) -> str:
        """Generate a random numeric OTP of specified length."""
        return "".join(secrets.choice(string.digits) for _ in range(length))

    def request_password_reset_otp(self, email: str) -> tuple[bool, str]:
        """
        Request a password reset OTP for the given email.

        Args:
            email: The user's email address.

        Returns:
            A tuple of (success, message).
        """
        with self._handle_service_errors():
            if not email:
                raise InvalidInputError("Email cannot be empty.")

            # Rate limiting: max 5 requests per 15 minutes
            rate_key = f"otp_request:{email}"
            request_count = cache.get(rate_key, 0)
            if request_count >= OTP_RATE_LIMIT_MAX:
                return False, "Too many OTP requests. Please try again later."
            cache.set(rate_key, request_count + 1, OTP_RATE_LIMIT_WINDOW)

            try:
                user = User.objects.get_by_email(email)
            except User.DoesNotExist:
                # Return success to prevent email enumeration attacks
                self._logger.info(
                    f"Password reset requested for non-existent email: {email}"
                )
                return (
                    True,
                    "If an account exists with this email, an OTP has been sent.",
                )

            with transaction.atomic():
                # Invalidate any existing unused OTPs for this user
                PasswordResetOTP.objects.filter(user=user, used=False).update(used=True)

                # Generate new OTP
                otp_code = self._generate_otp()
                expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)

                otp = PasswordResetOTP.objects.create(
                    user=user, otp=otp_code, expires_at=expires_at
                )

                # Send OTP email
                email_sent = self._send_otp_email(user, otp)

                if email_sent:
                    self._logger.info(f"Password reset OTP sent to {user.email}")
                    return (
                        True,
                        "If an account exists with this email, an OTP has been sent.",
                    )
                else:
                    self._logger.error(
                        f"Failed to send password reset OTP to {user.email}"
                    )
                    return False, "Failed to send OTP email. Please try again."

    def verify_otp(self, email: str, otp_code: str) -> tuple[bool, str]:
        """
        Verify an OTP without consuming it or resetting the password.

        Used to validate the OTP before allowing the user to enter a new password.

        Args:
            email: The user's email address.
            otp_code: The OTP to verify.

        Returns:
            A tuple of (success, message).
        """
        with self._handle_service_errors():
            if not all([email, otp_code]):
                raise InvalidInputError("Email and OTP are required.")

            # Rate limiting: max 5 verification attempts per 15 minutes
            verify_key = f"otp_verify:{email}"
            verify_count = cache.get(verify_key, 0)
            if verify_count >= OTP_RATE_LIMIT_MAX:
                return False, "Too many failed attempts. Please request a new OTP."
            cache.set(verify_key, verify_count + 1, OTP_RATE_LIMIT_WINDOW)

            try:
                user = User.objects.get_by_email(email)
            except User.DoesNotExist:
                return False, "Invalid OTP or email."

            otp = (
                PasswordResetOTP.objects.filter(user=user, otp=otp_code, used=False)
                .order_by("-created_at")
                .first()
            )

            if not otp:
                return False, "Invalid OTP or email."

            if otp.is_expired:
                return False, "OTP has expired. Please request a new one."

            return True, "OTP verified successfully."

    def verify_otp_and_reset_password(
        self, email: str, otp_code: str, new_password: str
    ) -> tuple[bool, str]:
        """
        Verify an OTP and reset the user's password.

        Args:
            email: The user's email address.
            otp_code: The OTP to verify.
            new_password: The new password to set.

        Returns:
            A tuple of (success, message).
        """
        with self._handle_service_errors():
            if not all([email, otp_code, new_password]):
                raise InvalidInputError("Email, OTP, and new password are required.")

            if len(new_password) < 8:
                raise InvalidInputError("Password must be at least 8 characters long.")

            # Rate limiting: max 5 verification attempts per 15 minutes
            verify_key = f"otp_verify:{email}"
            verify_count = cache.get(verify_key, 0)
            if verify_count >= OTP_RATE_LIMIT_MAX:
                # Invalidate all OTPs for this email's user
                try:
                    user = User.objects.get_by_email(email)
                    PasswordResetOTP.objects.filter(user=user, used=False).update(
                        used=True
                    )
                except User.DoesNotExist:
                    pass
                return (
                    False,
                    "Too many failed attempts. All OTPs have been invalidated.",
                )
            cache.set(verify_key, verify_count + 1, OTP_RATE_LIMIT_WINDOW)

            try:
                user = User.objects.get_by_email(email)
            except User.DoesNotExist:
                return False, "Invalid OTP or email."

            # Get the most recent unused OTP for this user
            otp = (
                PasswordResetOTP.objects.filter(user=user, otp=otp_code, used=False)
                .order_by("-created_at")
                .first()
            )

            if not otp:
                return False, "Invalid OTP or email."

            if otp.is_expired:
                return False, "OTP has expired. Please request a new one."

            with transaction.atomic():
                # Mark OTP as used
                otp.used = True
                otp.save(update_fields=["used"])

                # Reset password
                user.set_password(new_password)
                user.save(update_fields=["password"])

                # Send confirmation email
                self._send_password_reset_confirmation_email(user)

            # Clear the verification rate limit counter on success
            cache.delete(verify_key)
            self._logger.info(f"Password reset successfully for user {user.email}")
            return True, "Password reset successfully."

    def _send_otp_email(self, user: User, otp: PasswordResetOTP) -> bool:
        """Send OTP email to user."""
        subject = "Your Password Reset Code"

        try:
            # Build absolute logo URL for email
            site_url = getattr(settings, "SITE_URL", "https://midsphere.ai")
            logo_url = f"{site_url}/static/images/logo.png"

            html_message = render_to_string(
                "emails/password_reset_otp.html",
                {
                    "user": user,
                    "otp": otp.otp,
                    "expiry_minutes": OTP_EXPIRY_MINUTES,
                    "logo_url": logo_url,
                },
            )
            plain_message = strip_tags(html_message)
        except Exception:
            # Fallback to simple plain text if template doesn't exist
            plain_message = f"""
Hello{" " + user.name if user.name else ""},

Your password reset code is: {otp.otp}

This code will expire in {OTP_EXPIRY_MINUTES} minutes.

If you did not request this password reset, please ignore this email.

Best regards,
The Jatayu AI Team
"""
            html_message = None

        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            return True
        except Exception as e:
            self._logger.error(f"Failed to send OTP email to {user.email}: {e}")
            return False

    def _send_password_reset_confirmation_email(self, user: User) -> bool:
        """Send password reset confirmation email."""
        subject = "Your Password Has Been Reset"

        try:
            # Build absolute logo URL for email
            site_url = getattr(settings, "SITE_URL", "https://midsphere.ai")
            logo_url = f"{site_url}/static/images/logo.png"

            html_message = render_to_string(
                "emails/password_reset_confirmation.html",
                {
                    "user": user,
                    "logo_url": logo_url,
                },
            )
            plain_message = strip_tags(html_message)
        except Exception:
            plain_message = f"""
Hello{" " + user.name if user.name else ""},

Your password has been successfully reset.

If you did not make this change, please contact support immediately.

Best regards,
The Jatayu AI Team
"""
            html_message = None

        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            return True
        except Exception as e:
            self._logger.error(
                f"Failed to send password reset confirmation to {user.email}: {e}"
            )
            return False

    # endregion
