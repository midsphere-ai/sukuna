"""Base Ninja API schemas and API instances.

Creates the public and authenticated ``NinjaAPI`` instances, registers
global error handlers, and defines shared request/response schemas
such as ``CreateUserRequest``, ``UserUpdateRequest``, and ``UserSchema``.
"""

from typing import Optional

from ninja import ModelSchema, NinjaAPI, Schema

from apps.users.adapters import NinjaAuthAdapter
from apps.users.models import User
from config.errors.handlers import register_error_handlers

api = NinjaAPI()
authenticated_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="secured_api")

register_error_handlers(api)
register_error_handlers(authenticated_api)


class CreateUserRequest(Schema):
    """
    CreateUserRequest schema for creating a new user.

    Attributes:
        user_name (str): The name of the user.
        user_email (str): The email address of the user.
        password (str): The password for the user account.
    """

    user_name: str
    user_email: str
    password: str


class UserUpdateRequest(Schema):
    """
    UserUpdateRequest schema for updating user details.
    """

    user_name: Optional[str] = None
    user_email: Optional[str] = None
    occupation: Optional[str] = None
    avatar: Optional[str] = None
    nickname: Optional[str] = None


class UserSchema(ModelSchema):
    """
    UserSchema is a schema for serializing and deserializing User model instances.
    It inherits from ModelSchema and specifies the User model as its target.
    Certain fields are excluded from the schema for security and privacy reasons.
    """

    enterprise_mode: bool = False
    onboarding_completed: bool = False
    mfa_enrolled: bool = False
    mfa_pending: bool = False

    class Meta:
        model = User
        exclude = ["password", "is_staff", "groups", "user_permissions", "is_superuser"]

    @staticmethod
    def resolve_mfa_enrolled(obj) -> bool:
        return bool(getattr(obj, "_mfa_enrolled", False))

    @staticmethod
    def resolve_mfa_pending(obj) -> bool:
        return bool(getattr(obj, "_mfa_pending", False))

    @staticmethod
    def resolve_enterprise_mode(obj) -> bool:
        from apps.workspace.models import EnterpriseConfig

        try:
            return obj.enterprise_config.enabled
        except EnterpriseConfig.DoesNotExist:
            return False

    @staticmethod
    def resolve_onboarding_completed(obj) -> bool:
        from apps.users.models import UserSettings

        # Backward compatibility:
        # - None means legacy/unknown and falls back to old heuristic.
        # - Explicit True/False is authoritative.
        try:
            settings = obj.settings
        except UserSettings.DoesNotExist:
            settings = None

        if settings is not None and settings.onboarding_completed is not None:
            return bool(settings.onboarding_completed)

        return bool((obj.name or "").strip()) and obj.last_login is not None
