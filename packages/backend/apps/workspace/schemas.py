"""Request and response schemas for workspace API endpoints."""

from dataclasses import dataclass

from ninja import Schema


@dataclass(frozen=True)
class UserCreationResult:
    """Immutable result object returned after user creation."""

    message: str
    id: int


class RequestOTPSchema(Schema):
    """Schema for requesting a password reset OTP."""

    email: str


class VerifyOTPOnlySchema(Schema):
    """Schema for verifying OTP without resetting password."""

    email: str
    otp: str


class VerifyOTPSchema(Schema):
    """Schema for verifying OTP and resetting password."""

    email: str
    otp: str
    new_password: str


class OTPResponseSchema(Schema):
    """Response schema for OTP operations."""

    message: str
    success: bool
