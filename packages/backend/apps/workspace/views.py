"""API views for workspace user management, Google OAuth, and password reset OTP flows."""

import logging

from allauth.socialaccount.models import SocialAccount, SocialApp
from dj_rest_auth.models import get_token_model
from django.core.handlers.wsgi import WSGIRequest
from google.auth.transport import requests
from google.oauth2 import id_token

from apps.billing.models import SubscriptionPlan, UserSubscription
from apps.workspace.schemas import (
    OTPResponseSchema,
    RequestOTPSchema,
    VerifyOTPOnlySchema,
    VerifyOTPSchema,
)
from apps.workspace.services.workspace import WorkspaceService
from config.schemas.base import (  # noqa: F401
    CreateUserRequest,
    Schema,
    User,
    UserSchema,
    UserUpdateRequest,
    api,
    authenticated_api,
)
from config.schemas.responses import ActionResponse

logger = logging.getLogger(__name__)

workspace_service = WorkspaceService()


class GoogleAuthSchema(Schema):
    """Schema for Google authentication request containing the ID token."""

    id_token: str


class GoogleAuthUserSchema(Schema):
    """Schema representing the user portion of a Google auth response."""

    pk: int
    email: str
    name: str


class GoogleAuthResponseSchema(Schema):
    """Schema for the full Google authentication response with token and user info."""

    key: str
    user: GoogleAuthUserSchema


@api.post("/users", response={201: ActionResponse})
def create_user(request: WSGIRequest, data: CreateUserRequest):
    """
    Create a new user in the workspace.
    """
    user = workspace_service.create_user(
        name=data.user_name, email=data.user_email, password=data.password
    )

    # Assign free subscription plan
    try:
        free_plan = SubscriptionPlan.objects.filter(tier="free").get()
        UserSubscription.objects.create(user=user, plan=free_plan, status="active")
    except SubscriptionPlan.DoesNotExist:
        logger.error(
            "Free subscription plan not found. User created without subscription."
        )
    except Exception as e:
        logger.error(
            f"Failed to create subscription for user {user.id}: {e}", exc_info=True
        )

    return 201, {"message": "User created successfully"}


@authenticated_api.delete("/users/{user_id}", response=ActionResponse)
def remove_user(request: WSGIRequest, user_id: str):
    """
    Remove a user profile from the workspace.
    """
    workspace_service.remove_user(requesting_user=request.auth, user_id=user_id)
    return {"message": "User removed successfully"}


@authenticated_api.get("/users/me/", response=UserSchema)
def get_logged_in_user(request: WSGIRequest):
    """
    Retrieve the authenticated user from the request.

    Args:
        request (WSGIRequest): The HTTP request object containing authentication information.

    Returns:
        User: The authenticated user object.
    """
    user = request.auth
    from apps.users.mfa_api import (
        _bearer_token,
        is_token_mfa_verified,
        user_has_mfa,
    )

    enrolled = user_has_mfa(user)
    token = _bearer_token(request)
    user._mfa_enrolled = enrolled
    user._mfa_pending = enrolled and not (token and is_token_mfa_verified(token))
    return user


# ── Enterprise Mode ────────────────────────────────────────────────────────


class EnterpriseModeOut(Schema):
    """Enterprise mode status in API responses."""

    enabled: bool
    available: bool


class EnterpriseModeUpdateRequest(Schema):
    """Request body for toggling enterprise mode.

    Requires current_password for re-authentication (security hardening).
    """

    enabled: bool
    current_password: str


@authenticated_api.get("/enterprise-mode", response=EnterpriseModeOut)
def get_enterprise_mode(request: WSGIRequest):
    """Get the current user's enterprise mode status."""
    from apps.workspace.enterprise import get_or_create_enterprise_config

    user = request.auth
    config = get_or_create_enterprise_config(user)
    # Available = user is on a paid plan (not free tier)
    available = _is_paid_user(user)
    return {"enabled": config.enabled, "available": available}


@authenticated_api.patch(
    "/enterprise-mode",
    response={200: EnterpriseModeOut, 400: dict, 402: dict, 403: dict, 409: dict},
)
def update_enterprise_mode(request: WSGIRequest, body: EnterpriseModeUpdateRequest):
    """Enable or disable enterprise mode for the current user.

    Requires password re-authentication for security.
    - Only paid users can enable (402 for free tier).
    - Cannot disable while member of any org (409 with list of orgs).
    """
    from django.utils import timezone as tz

    from apps.compliance.models import AuditLog
    from apps.workspace.enterprise import get_or_create_enterprise_config
    from apps.workspace.models import OrganizationMembership

    user = request.auth

    # Re-authentication: verify current password before toggling
    if not body.current_password:
        return 400, {
            "detail": "Current password is required to toggle enterprise mode."
        }
    if not user.check_password(body.current_password):
        return 403, {"detail": "Invalid password. Re-authentication failed."}

    config = get_or_create_enterprise_config(user)

    if body.enabled:
        # Must be paid user to enable
        if not _is_paid_user(user):
            return 402, {"detail": "Enterprise features require a paid subscription."}

        if not config.enabled:
            config.enabled = True
            config.enabled_at = tz.now()
            config.grace_period_end = None
            config.save(
                update_fields=[
                    "enabled",
                    "enabled_at",
                    "grace_period_end",
                    "updated_at",
                ]
            )

            AuditLog.log(
                action="enterprise_mode_enabled",
                resource_type="enterprise_config",
                resource_id=str(config.pk),
                actor_id=user.pk,
                actor_email=user.email,
                actor_ip=_get_client_ip(request),
                request_id=getattr(request, "request_id", ""),
            )
    else:
        # Cannot disable while member of any org
        memberships = OrganizationMembership.objects.filter(user=user).select_related(
            "organization"
        )
        if memberships.exists():
            orgs = [
                {
                    "id": str(m.organization_id),
                    "name": m.organization.name,
                    "role": m.role,
                }
                for m in memberships
            ]
            return 409, {
                "detail": "Cannot disable enterprise mode while member of organizations.",
                "organizations": orgs,
            }

        if config.enabled:
            config.enabled = False
            config.disabled_at = tz.now()
            config.save(update_fields=["enabled", "disabled_at", "updated_at"])

            AuditLog.log(
                action="enterprise_mode_disabled",
                resource_type="enterprise_config",
                resource_id=str(config.pk),
                actor_id=user.pk,
                actor_email=user.email,
                actor_ip=_get_client_ip(request),
                request_id=getattr(request, "request_id", ""),
            )

    return 200, {"enabled": config.enabled, "available": _is_paid_user(user)}


def _is_paid_user(user) -> bool:
    """Check if user has an active paid subscription (not free tier)."""
    try:
        sub = user.subscription
        if sub.status == "active" and sub.plan and sub.plan.tier != "free":
            return True
        # Also count grace period as "available"
        if sub.in_grace_period():
            return True
    except UserSubscription.DoesNotExist:
        pass
    return False


def _get_client_ip(request) -> str | None:
    """Extract client IP from X-Forwarded-For or REMOTE_ADDR."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ── Multi-Org Context ─────────────────────────────────────────────────────


class SwitchOrgRequest(Schema):
    """Request body for switching active organization."""

    organization_id: str | None = None


class ActiveOrgOut(Schema):
    """Active organization context in API responses."""

    organization_id: str | None = None
    organization_name: str | None = None
    organization_slug: str | None = None
    your_role: str | None = None


@authenticated_api.post(
    "/switch-org",
    response={200: ActiveOrgOut, 403: dict, 404: dict},
)
def switch_org(request: WSGIRequest, body: SwitchOrgRequest):
    """Set the active organization context for the current user.

    Pass organization_id=null to switch back to personal space.
    """
    from apps.users.models import UserSettings
    from apps.workspace.models import Organization, OrganizationMembership

    user = request.auth
    settings, _ = UserSettings.objects.get_or_create(user=user)

    if body.organization_id is None:
        # Switch to personal space
        settings.last_active_org = None
        settings.save(update_fields=["last_active_org"])
        return 200, {
            "organization_id": None,
            "organization_name": None,
            "organization_slug": None,
            "your_role": None,
        }

    # Validate org exists and user is a member
    try:
        org = Organization.objects.get(pk=body.organization_id)
    except (Organization.DoesNotExist, ValueError):
        return 404, {"detail": "Organization not found."}

    try:
        membership = OrganizationMembership.objects.get(organization=org, user=user)
    except OrganizationMembership.DoesNotExist:
        return 403, {"detail": "You are not a member of this organization."}

    settings.last_active_org = org
    settings.save(update_fields=["last_active_org"])

    return 200, {
        "organization_id": str(org.pk),
        "organization_name": org.name,
        "organization_slug": org.slug,
        "your_role": membership.role,
    }


@authenticated_api.get("/active-org", response={200: ActiveOrgOut})
def get_active_org(request: WSGIRequest):
    """Get the current active organization context (or null for personal space)."""
    from apps.users.models import UserSettings
    from apps.workspace.models import OrganizationMembership

    user = request.auth
    settings, _ = UserSettings.objects.get_or_create(user=user)
    org = settings.last_active_org

    if org is None:
        return 200, {
            "organization_id": None,
            "organization_name": None,
            "organization_slug": None,
            "your_role": None,
        }

    # Verify user is still a member (could have been removed since last switch)
    try:
        membership = OrganizationMembership.objects.get(organization=org, user=user)
    except OrganizationMembership.DoesNotExist:
        # User no longer in this org — reset to personal
        settings.last_active_org = None
        settings.save(update_fields=["last_active_org"])
        return 200, {
            "organization_id": None,
            "organization_name": None,
            "organization_slug": None,
            "your_role": None,
        }

    return 200, {
        "organization_id": str(org.pk),
        "organization_name": org.name,
        "organization_slug": org.slug,
        "your_role": membership.role,
    }


# ── SSO Resilience (Emergency Bypass) ────────────────────────────────────


class SSOBypassRequest(Schema):
    """Request body for SSO emergency bypass login."""

    email: str
    password: str


class SSOBypassOut(Schema):
    """Response for a successful SSO bypass login."""

    key: str
    user_id: int
    email: str


class SSOOrgIdP(Schema):
    """SSO org entry for IdP selection."""

    organization_id: str
    organization_name: str
    organization_slug: str
    provider_type: str
    metadata_url: str
    entity_id: str


@api.post(
    "/auth/sso-bypass/{org_slug}",
    response={200: SSOBypassOut, 400: dict, 403: dict, 404: dict, 429: dict},
    auth=None,
)
def sso_bypass_login(request: WSGIRequest, org_slug: str, body: SSOBypassRequest):
    """Emergency bypass login when SSO is enforced but IdP is down.

    Only works when emergency_bypass_enabled=True on the org's SSO config.
    Rate-limited to 5 attempts per org per minute.
    """
    from django.core.cache import cache

    from apps.compliance.models import AuditLog
    from apps.users.models import User
    from apps.workspace.models import Organization, SSOConfiguration

    # Find the org
    try:
        org = Organization.objects.get(slug=org_slug)
    except Organization.DoesNotExist:
        return 404, {"detail": "Organization not found."}

    # Rate limit: 5 attempts per org per minute
    cache_key = f"sso_bypass_rate:{org.pk}"
    attempts = cache.get(cache_key, 0)
    if attempts >= 5:
        return 429, {"detail": "Too many bypass attempts. Try again in one minute."}
    cache.set(cache_key, attempts + 1, timeout=60)

    # Check SSO config exists and bypass is enabled
    try:
        sso_config = org.sso_config
    except SSOConfiguration.DoesNotExist:
        return 404, {"detail": "No SSO configuration for this organization."}

    if not sso_config.emergency_bypass_enabled:
        return 403, {"detail": "Emergency bypass is not enabled for this organization."}

    # Validate the bypass code from query params
    code = request.GET.get("code", "")
    if not code or code != sso_config.emergency_bypass_code:
        return 403, {"detail": "Invalid emergency bypass code."}

    # Authenticate the user with email/password
    email = body.email.strip().lower()
    try:
        user = User.objects.get_by_email(email)
    except User.DoesNotExist:
        return 400, {"detail": "Invalid credentials."}

    # Verify the user is a member of this org
    if not org.has_member(user):
        return 403, {"detail": "User is not a member of this organization."}

    # Check password
    if not user.check_password(body.password):
        return 400, {"detail": "Invalid credentials."}

    # Generate auth token
    token_model = get_token_model()
    token, _ = token_model.objects.get_or_create(user=user)

    client_ip = _get_client_ip(request)

    # Audit log
    AuditLog.log(
        action="sso_emergency_bypass",
        resource_type="sso_configuration",
        resource_id=str(sso_config.pk),
        actor_id=user.pk,
        actor_email=user.email,
        actor_ip=client_ip,
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "organization_slug": org.slug,
        },
    )

    return 200, {
        "key": token.key,
        "user_id": user.pk,
        "email": user.email,
    }


@authenticated_api.get(
    "/sso/org-selection",
    response={200: list[SSOOrgIdP]},
)
def sso_org_selection(request: WSGIRequest):
    """Return SSO-enabled orgs for the authenticated user for IdP selection.

    If the user has only one SSO org, the frontend can auto-redirect.
    """
    from apps.workspace.models import OrganizationMembership, SSOConfiguration

    user = request.auth
    memberships = OrganizationMembership.objects.filter(user=user).select_related(
        "organization"
    )

    results = []
    for m in memberships:
        try:
            sso_config = m.organization.sso_config
            if sso_config.is_active:
                results.append(
                    {
                        "organization_id": str(m.organization.pk),
                        "organization_name": m.organization.name,
                        "organization_slug": m.organization.slug,
                        "provider_type": sso_config.provider_type,
                        "metadata_url": sso_config.metadata_url,
                        "entity_id": sso_config.entity_id,
                    }
                )
        except SSOConfiguration.DoesNotExist:
            continue

    return 200, results


@api.post(
    "/auth/saml/verify-email",
    response={200: dict, 404: dict},
    auth=None,
)
def saml_verify_email(request: WSGIRequest):
    """Check if a SAML assertion email matches a Midsphere account.

    Used during SAML SSO flow to match the IdP assertion email to a local user.
    Matches by email_hash since email is encrypted.
    """
    import json

    from apps.users.models import User

    try:
        data = json.loads(request.body)
        saml_email = data.get("email", "").strip().lower()
    except (json.JSONDecodeError, AttributeError):
        return 404, {"detail": "SSO email does not match any account."}

    if not saml_email:
        return 404, {"detail": "SSO email does not match any account."}

    try:
        user = User.objects.get_by_email(saml_email)
        return 200, {"matched": True, "user_id": user.pk}
    except User.DoesNotExist:
        return 404, {"detail": "SSO email does not match any account."}


@authenticated_api.patch("/users/{user_id}", response=ActionResponse)
def modify_user(request: WSGIRequest, user_id: str, data: UserUpdateRequest):
    """
    Modify a user's profile.
    """
    workspace_service.modify_user(
        requesting_user=request.auth,
        user_id=user_id,
        data=data.dict(exclude_unset=True),
    )
    return {"message": "User updated successfully"}


@api.post("google-provider/verify", response=GoogleAuthResponseSchema, auth=None)
def google_auth(request, payload: GoogleAuthSchema):
    """
    Authenticate user with Google ID token from a mobile client.
    Compatible with dj-rest-auth flow.
    """
    try:
        # Get Google client ID from social app
        social_app = SocialApp.objects.get(provider="google")
        client_id = social_app.client_id

        # Verify the Google ID token
        idinfo = id_token.verify_oauth2_token(
            payload.id_token, requests.Request(), client_id
        )

        # Validate issuer1
        if idinfo["iss"] not in ["accounts.google.com", "https://accounts.google.com"]:
            raise ValueError("Wrong issuer.")

        google_user_id = idinfo["sub"]
        email = idinfo["email"]
        first_name = idinfo.get("given_name", "")
        last_name = idinfo.get("family_name", "")
        picture = idinfo.get("picture", "")

        # Check if social account exists
        try:
            social_account = SocialAccount.objects.get(
                provider="google", uid=google_user_id
            )
            user = social_account.user
            created = False

        except SocialAccount.DoesNotExist:
            # Check if user exists with this email
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"name": f"{first_name} {last_name}"},
            )

            # Create social account link
            social_account = SocialAccount.objects.create(
                user=user,
                provider="google",
                uid=google_user_id,
                extra_data={
                    "email": email,
                    "given_name": first_name,
                    "family_name": last_name,
                    "picture": picture,
                },
            )

            if created:
                try:
                    free_plan = SubscriptionPlan.objects.filter(tier="free").get()
                    UserSubscription.objects.create(
                        user=user, plan=free_plan, status="active"
                    )
                except SubscriptionPlan.DoesNotExist:
                    logger.error(
                        "Free subscription plan not found. Google OAuth user created without subscription."
                    )

        # Get or create auth token (dj-rest-auth compatible)
        token_model = get_token_model()
        token, _ = token_model.objects.get_or_create(user=user)

        # Return response in dj-rest-auth format
        return {
            "key": token.key,
            "user": {
                "pk": user.pk,
                "email": user.email,
                "name": user.name,
            },
        }

    except ValueError:
        raise
    except SocialApp.DoesNotExist:
        logger.error("[AUTH] Google social app not configured")
        raise
    except Exception:
        logger.error("[AUTH] Google auth failed", exc_info=True)
        raise


# Password Reset OTP Endpoints


@api.post("/password/request-otp", response=OTPResponseSchema, auth=None)
def request_password_reset_otp(request: WSGIRequest, data: RequestOTPSchema):
    """
    Request an OTP for password reset.

    Sends a 6-digit OTP to the user's email that expires in 15 minutes.
    Returns success even if email doesn't exist to prevent enumeration.
    """
    success, message = workspace_service.request_password_reset_otp(data.email)
    return {"success": success, "message": message}


@api.post("/password/verify-otp-only", response=OTPResponseSchema, auth=None)
def verify_otp_only(request: WSGIRequest, data: VerifyOTPOnlySchema):
    """
    Verify an OTP without resetting the password.

    Used to validate the OTP before allowing the user to set a new password.
    Does not consume the OTP.
    """
    success, message = workspace_service.verify_otp(email=data.email, otp_code=data.otp)
    return {"success": success, "message": message}


@api.post("/password/verify-otp", response=OTPResponseSchema, auth=None)
def verify_otp_and_reset_password(request: WSGIRequest, data: VerifyOTPSchema):
    """
    Verify OTP and reset the user's password.

    Requires: email, 6-digit OTP, and new password (min 8 characters).
    OTP must be used within 15 minutes of request.
    """
    success, message = workspace_service.verify_otp_and_reset_password(
        email=data.email, otp_code=data.otp, new_password=data.new_password
    )
    return {"success": success, "message": message}
