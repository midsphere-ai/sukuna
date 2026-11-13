"""Tests for the MFA enrollment & verification API."""

import json
import time

import pytest
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import (
    format_hotp_value,
    generate_totp_secret,
    hotp_value,
)
from django.core.cache import cache
from django.test import RequestFactory

from apps.users.mfa_api import (
    is_token_mfa_verified,
    mark_token_mfa_verified,
    mfa_remove,
    mfa_state,
    mfa_verify,
    recovery_generate,
    recovery_regenerate,
    totp_begin,
    totp_confirm,
)
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def rf():
    return RequestFactory()


def _authed(rf, method, path, user, body=None, token: str | None = None):
    factory = getattr(rf, method)
    if body is not None:
        req = factory(path, data=json.dumps(body), content_type="application/json")
    else:
        req = factory(path)
    req.auth = user
    req.request_id = "test-req"
    if token:
        req.META["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return req


def _current_totp_code(secret: str) -> str:
    counter = int(time.time()) // 30
    return format_hotp_value(hotp_value(secret, counter))


def test_initial_state_empty(rf):
    user = UserFactory()
    request = _authed(rf, "get", "/users/me/mfa", user)
    status, body = mfa_state(request)
    assert status == 200
    assert body["enrolled"] is False
    assert body["has_totp"] is False
    assert body["pending_challenge"] is False
    assert body["authenticators"] == []


def test_totp_enrollment_full_flow(rf):
    user = UserFactory()
    token = "tok-abc"

    # Begin
    req = _authed(rf, "post", "/users/me/mfa/totp/begin", user, body={}, token=token)
    status, begin = totp_begin(req)
    assert status == 200
    assert "secret" in begin
    assert begin["otpauth_uri"].startswith("otpauth://totp/")

    # Confirm with valid code
    code = _current_totp_code(begin["secret"])
    req = _authed(
        rf,
        "post",
        "/users/me/mfa/totp/confirm",
        user,
        body={"secret": begin["secret"], "code": code},
        token=token,
    )
    status, _auth = totp_confirm(req, _SchemaShim(secret=begin["secret"], code=code))
    assert status == 200
    assert Authenticator.objects.filter(user=user, type="totp").exists()
    # Token should be marked MFA-verified after enrollment
    assert is_token_mfa_verified(token)


def test_totp_confirm_invalid_code(rf):
    user = UserFactory()
    secret = generate_totp_secret()
    req = _authed(
        rf,
        "post",
        "/users/me/mfa/totp/confirm",
        user,
        body={"secret": secret, "code": "000000"},
    )
    status, body = totp_confirm(req, _SchemaShim(secret=secret, code="000000"))
    assert status == 400
    assert "Invalid" in body["detail"]
    assert not Authenticator.objects.filter(user=user).exists()


def test_recovery_codes_generate_then_regenerate(rf):
    user = UserFactory()
    req = _authed(rf, "post", "/users/me/mfa/recovery-codes/generate", user, body={})
    status, body = recovery_generate(req)
    assert status == 200
    assert len(body["codes"]) > 0
    first_codes = list(body["codes"])

    # Second generate should 409
    req = _authed(rf, "post", "/users/me/mfa/recovery-codes/generate", user, body={})
    status, _ = recovery_generate(req)
    assert status == 409

    # Regenerate replaces them
    req = _authed(rf, "post", "/users/me/mfa/recovery-codes/regenerate", user, body={})
    status, body = recovery_regenerate(req)
    assert status == 200
    assert body["codes"] != first_codes


def test_remove_authenticator_clears_token_verification(rf):
    user = UserFactory()
    token = "tok-xyz"
    secret = generate_totp_secret()
    from allauth.mfa.totp.internal.auth import TOTP

    totp = TOTP.activate(user, secret)
    mark_token_mfa_verified(token)
    assert is_token_mfa_verified(token)

    req = _authed(rf, "delete", f"/users/me/mfa/{totp.instance.id}", user, token=token)
    status, _ = mfa_remove(req, totp.instance.id)
    assert status == 200
    assert not Authenticator.objects.filter(user=user).exists()
    # Token verification cleared
    assert not is_token_mfa_verified(token)


def test_verify_with_totp_promotes_token(rf):
    user = UserFactory()
    secret = generate_totp_secret()
    from allauth.mfa.totp.internal.auth import TOTP

    TOTP.activate(user, secret)
    token = "tok-verify"
    code = _current_totp_code(secret)

    req = _authed(
        rf, "post", "/users/me/mfa/verify", user, body={"code": code}, token=token
    )
    status, body = mfa_verify(req, _SchemaShim(code=code))
    assert status == 200
    assert body["success"]
    assert body["method"] == "totp"
    assert is_token_mfa_verified(token)


def test_verify_invalid_code(rf):
    user = UserFactory()
    secret = generate_totp_secret()
    from allauth.mfa.totp.internal.auth import TOTP

    TOTP.activate(user, secret)
    req = _authed(rf, "post", "/users/me/mfa/verify", user, body={"code": "000000"})
    status, body = mfa_verify(req, _SchemaShim(code="000000"))
    assert status == 400
    assert "Invalid" in body["detail"]


def test_state_pending_when_token_not_verified(rf):
    user = UserFactory()
    secret = generate_totp_secret()
    from allauth.mfa.totp.internal.auth import TOTP

    TOTP.activate(user, secret)
    token = "tok-pending"
    req = _authed(rf, "get", "/users/me/mfa", user, token=token)
    status, body = mfa_state(req)
    assert status == 200
    assert body["enrolled"] is True
    assert body["pending_challenge"] is True

    mark_token_mfa_verified(token)
    req = _authed(rf, "get", "/users/me/mfa", user, token=token)
    status, body = mfa_state(req)
    assert body["pending_challenge"] is False


class _SchemaShim:
    """Mimics a pydantic schema instance for endpoint functions called directly."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
