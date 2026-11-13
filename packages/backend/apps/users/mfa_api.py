"""Multi-factor authentication API endpoints.

JSON wrappers around `allauth.mfa` primitives so the SPA can enroll users in
TOTP, manage recovery codes, and pass post-login MFA challenges. Token-based
auth via :class:`NinjaAuthAdapter`.

Login enforcement is achieved by tracking a per-token "mfa_verified" flag in
the cache. When an authenticated user has any MFA authenticator and the token
has not been verified for this session, mutating endpoints elsewhere can call
:func:`is_token_mfa_verified` to gate access. The /users/me endpoint also
exposes the ``mfa_pending`` flag so the frontend can route to the challenge
screen.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from allauth.mfa.models import Authenticator
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.totp.internal.auth import (
    TOTP,
    generate_totp_secret,
    validate_totp_code,
)
from django.conf import settings
from django.core.cache import cache
from ninja import NinjaAPI, Schema

from apps.compliance.models import AuditAction, AuditLog
from apps.users.adapters import NinjaAuthAdapter, _get_client_ip

mfa_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="mfa")

MFA_VERIFIED_TTL = 60 * 60 * 12  # 12 hours
MFA_VERIFIED_CACHE_PREFIX = "mfa_token_verified"


# ── Cache helpers ────────────────────────────────────────────────────────────


def _verified_cache_key(token_key: str) -> str:
    return f"{MFA_VERIFIED_CACHE_PREFIX}:{token_key}"


def is_token_mfa_verified(token_key: str) -> bool:
    """Return True if the bearer token has passed an MFA challenge."""
    return bool(cache.get(_verified_cache_key(token_key)))


def mark_token_mfa_verified(token_key: str) -> None:
    cache.set(_verified_cache_key(token_key), True, timeout=MFA_VERIFIED_TTL)


def clear_token_mfa_verified(token_key: str) -> None:
    cache.delete(_verified_cache_key(token_key))


def user_has_mfa(user) -> bool:
    return Authenticator.objects.filter(user=user).exists()


def _bearer_token(request) -> str | None:
    auth_header = request.META.get("HTTP_AUTHORIZATION", "") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


# ── Schemas ──────────────────────────────────────────────────────────────────


class AuthenticatorOut(Schema):
    id: int
    type: str
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class MFAStateOut(Schema):
    enrolled: bool
    has_totp: bool
    has_recovery_codes: bool
    pending_challenge: bool
    authenticators: list[AuthenticatorOut]


class TOTPBeginOut(Schema):
    secret: str
    otpauth_uri: str
    issuer: str
    label: str


class TOTPConfirmIn(Schema):
    secret: str
    code: str


class RecoveryCodesOut(Schema):
    codes: list[str]
    unused_count: int


class VerifyIn(Schema):
    code: str


class VerifyOut(Schema):
    success: bool
    method: str  # "totp" or "recovery_code"


class ErrorOut(Schema):
    detail: str


# ── Helpers ──────────────────────────────────────────────────────────────────


def _serialize_authenticator(a: Authenticator) -> dict:
    return {
        "id": a.id,
        "type": a.type,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "last_used_at": a.last_used_at.isoformat() if a.last_used_at else None,
    }


def _audit(request, user, action: str, **metadata) -> None:
    AuditLog.log(
        action=action,
        resource_type="user_mfa",
        resource_id=str(user.id),
        actor_id=user.id,
        actor_email=user.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata=metadata,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@mfa_api.get("/users/me/mfa", response={200: MFAStateOut}, summary="Get MFA state")
def mfa_state(request):
    """Return the authenticated user's MFA enrollment state."""
    user = request.auth
    auths = list(Authenticator.objects.filter(user=user).order_by("created_at"))
    types = {a.type for a in auths}
    token = _bearer_token(request)
    pending = bool(auths) and not (token and is_token_mfa_verified(token))
    return 200, {
        "enrolled": bool(auths),
        "has_totp": Authenticator.Type.TOTP in types,
        "has_recovery_codes": Authenticator.Type.RECOVERY_CODES in types,
        "pending_challenge": pending,
        "authenticators": [_serialize_authenticator(a) for a in auths],
    }


@mfa_api.post(
    "/users/me/mfa/totp/begin",
    response={200: TOTPBeginOut, 409: ErrorOut},
    summary="Begin TOTP enrollment (returns secret + QR URI)",
)
def totp_begin(request):
    """Generate a new TOTP secret for the user and return the otpauth URI."""
    user = request.auth
    if Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).exists():
        return 409, {"detail": "TOTP authenticator already enrolled. Remove it first."}

    secret = generate_totp_secret()
    issuer = getattr(settings, "MFA_TOTP_ISSUER", "Jatayu AI")
    label = user.email or str(user.id)
    otpauth_uri = (
        f"otpauth://totp/{quote(issuer)}:{quote(label)}"
        f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )
    return 200, {
        "secret": secret,
        "otpauth_uri": otpauth_uri,
        "issuer": issuer,
        "label": label,
    }


@mfa_api.post(
    "/users/me/mfa/totp/confirm",
    response={200: AuthenticatorOut, 400: ErrorOut, 409: ErrorOut},
    summary="Confirm TOTP enrollment by validating a code",
)
def totp_confirm(request, body: TOTPConfirmIn):
    """Validate the user-entered TOTP code and persist the authenticator."""
    user = request.auth
    if Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).exists():
        return 409, {"detail": "TOTP authenticator already enrolled."}

    if not validate_totp_code(body.secret, body.code):
        _audit(request, user, AuditAction.MFA_CHALLENGE_FAILED, stage="enrollment")
        return 400, {"detail": "Invalid verification code."}

    totp = TOTP.activate(user, body.secret)
    _audit(request, user, AuditAction.MFA_ENROLLED, type="totp")
    token = _bearer_token(request)
    if token:
        mark_token_mfa_verified(token)
    return 200, _serialize_authenticator(totp.instance)


@mfa_api.post(
    "/users/me/mfa/recovery-codes/generate",
    response={200: RecoveryCodesOut, 409: ErrorOut},
    summary="Generate recovery codes (only if none exist)",
)
def recovery_generate(request):
    user = request.auth
    if Authenticator.objects.filter(
        user=user, type=Authenticator.Type.RECOVERY_CODES
    ).exists():
        return 409, {
            "detail": "Recovery codes already exist. Use regenerate to replace them."
        }
    rc = RecoveryCodes.activate(user)
    codes = rc.generate_codes()
    _audit(request, user, AuditAction.MFA_RECOVERY_CODES_GENERATED, mode="generate")
    return 200, {"codes": codes, "unused_count": len(codes)}


@mfa_api.post(
    "/users/me/mfa/recovery-codes/regenerate",
    response={200: RecoveryCodesOut},
    summary="Regenerate recovery codes (replaces existing)",
)
def recovery_regenerate(request):
    user = request.auth
    Authenticator.objects.filter(
        user=user, type=Authenticator.Type.RECOVERY_CODES
    ).delete()
    rc = RecoveryCodes.activate(user)
    codes = rc.generate_codes()
    _audit(request, user, AuditAction.MFA_RECOVERY_CODES_GENERATED, mode="regenerate")
    return 200, {"codes": codes, "unused_count": len(codes)}


@mfa_api.delete(
    "/users/me/mfa/{authenticator_id}",
    response={200: dict, 404: ErrorOut},
    summary="Remove an authenticator",
)
def mfa_remove(request, authenticator_id: int):
    user = request.auth
    try:
        a = Authenticator.objects.get(id=authenticator_id, user=user)
    except Authenticator.DoesNotExist:
        return 404, {"detail": "Authenticator not found."}
    type_ = a.type
    a.delete()
    _audit(request, user, AuditAction.MFA_REMOVED, type=type_)
    if not user_has_mfa(user):
        token = _bearer_token(request)
        if token:
            clear_token_mfa_verified(token)
    return 200, {"success": True}


@mfa_api.post(
    "/users/me/mfa/verify",
    response={200: VerifyOut, 400: ErrorOut, 404: ErrorOut},
    summary="Verify an MFA code (TOTP or recovery code) for the current session",
)
def mfa_verify(request, body: VerifyIn):
    """Validate a TOTP or recovery code against the user's authenticators.

    On success, marks the current bearer token as MFA-verified.
    """
    user = request.auth
    auths = list(Authenticator.objects.filter(user=user))
    if not auths:
        return 404, {"detail": "No MFA authenticators enrolled."}

    code = (body.code or "").strip().replace(" ", "")
    method = None
    for a in auths:
        wrapper = a.wrap()
        if wrapper.validate_code(code):
            a.record_usage()
            method = a.type
            break

    if not method:
        _audit(request, user, AuditAction.MFA_CHALLENGE_FAILED, stage="login")
        return 400, {"detail": "Invalid verification code."}

    token = _bearer_token(request)
    if token:
        mark_token_mfa_verified(token)
    _audit(request, user, AuditAction.MFA_CHALLENGE_PASSED, method=method)
    return 200, {"success": True, "method": method}
