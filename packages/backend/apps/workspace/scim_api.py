"""SCIM 2.0 user provisioning API (RFC 7644).

Endpoints are authenticated via SCIM bearer tokens (SCIMToken model), not
regular user tokens. The org is derived from the ``org_slug`` in the URL.
"""

import hashlib
import ipaddress
import logging
import time

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja import NinjaAPI
from ninja.security import HttpBearer

from apps.compliance.models import AuditLog
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    SCIMToken,
)
from apps.workspace.scim_schemas import (
    CreateSCIMUserRequest,
    PatchSCIMUserRequest,
    ReplaceSCIMUserRequest,
    SCIMError,
    SCIMListResponse,
    SCIMUserResource,
)
from apps.workspace.security import check_scim_404_rate

logger = logging.getLogger(__name__)

# Rate limit: 100 requests per 60 seconds per SCIM token
SCIM_RATE_LIMIT = 100
SCIM_RATE_WINDOW = 60  # seconds


def _ip_in_cidrs(ip_str: str | None, cidrs: list[str]) -> bool:
    """Check whether *ip_str* falls within any of the given CIDR ranges."""
    if not cidrs:
        return True  # empty allowlist = allow all
    if not ip_str:
        return False  # no IP and allowlist is set = deny
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


# ── SCIM Bearer Token Auth ────────────────────────────────────────────────


class SCIMBearerAuth(HttpBearer):
    """Validate SCIM bearer tokens and attach the org to the request."""

    def authenticate(self, request, token: str):
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        try:
            scim_token = SCIMToken.objects.select_related("organization").get(
                token_hash=token_hash, is_active=True
            )
        except SCIMToken.DoesNotExist:
            return None

        # IP allowlist check
        if scim_token.allowed_cidrs:
            client_ip = _get_client_ip(request)
            if not _ip_in_cidrs(client_ip, scim_token.allowed_cidrs):
                return None  # Auth fails — IP not in allowlist

        # Rate limit check
        cache_key = f"scim_rate:{token_hash}"
        now = time.time()
        window_start = now - SCIM_RATE_WINDOW

        # Get existing request timestamps
        timestamps = cache.get(cache_key, [])
        # Prune expired entries
        timestamps = [ts for ts in timestamps if ts > window_start]

        if len(timestamps) >= SCIM_RATE_LIMIT:
            request.scim_rate_limited = True
            return scim_token  # Auth succeeds but request will be rejected

        timestamps.append(now)
        cache.set(cache_key, timestamps, timeout=SCIM_RATE_WINDOW)

        # Update last_used_at and last_used_ip
        client_ip = _get_client_ip(request)
        SCIMToken.objects.filter(pk=scim_token.pk).update(
            last_used_at=timezone.now(),
            last_used_ip=client_ip,
        )

        # Attach org to request for downstream use
        request.scim_org = scim_token.organization
        request.scim_rate_limited = False
        return scim_token


scim_api = NinjaAPI(auth=SCIMBearerAuth(), urls_namespace="scim")


# ── Helpers ────────────────────────────────────────────────────────────────


def _get_org_from_slug(request, org_slug: str) -> Organization:
    """Resolve org from slug and verify it matches the token's org.

    Tracks failed lookups for rate limiting to prevent org enumeration.
    """
    try:
        org = Organization.objects.get(slug=org_slug)
    except Organization.DoesNotExist:
        # Track 404 for rate limiting (org enumeration prevention)
        check_scim_404_rate(request)  # increments counter
        return None

    # Ensure the SCIM token is scoped to this org
    if org.pk != request.scim_org.pk:
        return None
    return org


def _scim_org_error_or_429(request) -> tuple:
    """Return 429 if SCIM 404 rate limit exceeded, else standard 403."""
    if check_scim_404_rate(request):
        return _scim_error(429, "Too many requests. Please try again later.")
    return _scim_error(403, "Token not authorized for this organization.")


def _get_client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _serialize_scim_user(user, org_slug: str, base_url: str = "") -> dict:
    """Build a SCIM User resource dict."""
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": str(user.pk),
        "userName": user.email,
        "name": {
            "givenName": user.name or "",
            "familyName": "",
        },
        "active": user.is_active,
        "meta": {
            "resourceType": "User",
            "created": user.date_joined,
            "lastModified": user.date_joined,
            "location": f"{base_url}/api/v1/scim/v2/{org_slug}/Users/{user.pk}",
        },
    }


def _scim_error(status: int, detail: str) -> tuple:
    """Return a SCIM-formatted error tuple."""
    return status, {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "detail": detail,
        "status": str(status),
    }


def _check_rate_limit(request) -> tuple | None:
    """Return a 429 SCIM error if the request is rate-limited, else None."""
    if getattr(request, "scim_rate_limited", False):
        return _scim_error(
            429, "Rate limit exceeded. Max 100 requests per minute per token."
        )
    return None


# ── SCIM User Endpoints ──────────────────────────────────────────────────


@scim_api.get(
    "/{org_slug}/Users",
    response={200: SCIMListResponse, 401: SCIMError, 403: SCIMError, 429: SCIMError},
)
def list_scim_users(
    request, org_slug: str, startIndex: int = 1, count: int = 100, filter: str = ""
):
    """List users in the organization (SCIM ListResponse).

    Supports ``filter=userName eq "x@y.com"`` for email lookup via email_hash.
    Uses cursor-based pagination (order by user id) for consistency under
    concurrent provisioning.
    """
    rate_err = _check_rate_limit(request)
    if rate_err:
        return rate_err

    org = _get_org_from_slug(request, org_slug)
    if org is None:
        return _scim_org_error_or_429(request)

    # Handle SCIM filter: userName eq "x@y.com"
    if filter:
        import re

        match = re.match(r'userName\s+eq\s+"([^"]+)"', filter)
        if match:
            from apps.users.managers import UserManager

            filter_email = match.group(1).strip().lower()
            email_hash = UserManager._hash_email(filter_email)
            memberships = org.memberships.select_related("user").filter(
                user__email_hash=email_hash
            )
            resources = [_serialize_scim_user(m.user, org_slug) for m in memberships]
            return 200, {
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
                "totalResults": len(resources),
                "startIndex": 1,
                "itemsPerPage": len(resources),
                "Resources": resources,
            }

    # Cursor-based pagination: order by user.id for stable ordering under
    # concurrent provisioning (avoids skips/duplicates from offset-based).
    memberships = org.memberships.select_related("user").order_by("user__id")
    total = memberships.count()

    # SCIM pagination is 1-indexed
    offset = max(startIndex - 1, 0)
    page = memberships[offset : offset + count]

    resources = [_serialize_scim_user(m.user, org_slug) for m in page]

    return 200, {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": count,
        "Resources": resources,
    }


@scim_api.get(
    "/{org_slug}/Users/{user_id}",
    response={200: SCIMUserResource, 403: SCIMError, 404: SCIMError, 429: SCIMError},
)
def get_scim_user(request, org_slug: str, user_id: int):
    """Get a single SCIM user resource."""
    rate_err = _check_rate_limit(request)
    if rate_err:
        return rate_err

    org = _get_org_from_slug(request, org_slug)
    if org is None:
        return _scim_org_error_or_429(request)

    membership = org.memberships.filter(user_id=user_id).select_related("user").first()
    if membership is None:
        return _scim_error(404, "User not found in this organization.")

    return 200, _serialize_scim_user(membership.user, org_slug)


@scim_api.post(
    "/{org_slug}/Users",
    response={
        201: SCIMUserResource,
        400: SCIMError,
        403: SCIMError,
        409: SCIMError,
        429: SCIMError,
    },
)
def create_scim_user(request, org_slug: str, body: CreateSCIMUserRequest):
    """Provision a new user via SCIM.

    If the user already exists (by email), adds them to the org.
    If already a member, returns 409 Conflict.
    Reactivates deactivated accounts.
    """
    from apps.users.models import User

    rate_err = _check_rate_limit(request)
    if rate_err:
        return rate_err

    org = _get_org_from_slug(request, org_slug)
    if org is None:
        return _scim_org_error_or_429(request)

    email = body.userName.strip().lower()
    if not email:
        return _scim_error(400, "userName (email) is required.")

    name = ""
    if body.name and body.name.givenName:
        name = body.name.givenName

    with transaction.atomic():
        # Find or create the user
        try:
            user = User.objects.get_by_email(email)
            created = False
            # Reactivate deactivated accounts (e.g. previously deprovisioned)
            if not user.is_active and body.active:
                user.is_active = True
                user.save(update_fields=["is_active"])
        except User.DoesNotExist:
            user = User.objects.create_user(email=email, password=None, name=name)
            created = True

        # Check if already a member
        if org.has_member(user):
            return _scim_error(
                409, f"User '{email}' is already a member of this organization."
            )

        # Handle race condition with manual invite targeting same user
        try:
            OrganizationMembership.objects.create(
                organization=org,
                user=user,
                role=OrganizationRole.MEMBER,
            )
        except IntegrityError:
            return _scim_error(
                409, f"User '{email}' is already a member of this organization."
            )

        # Set active status
        if not body.active:
            user.is_active = False
            user.save(update_fields=["is_active"])

    # Auto-enable enterprise mode for the provisioned user
    from apps.workspace.enterprise import auto_enable_enterprise

    auto_enable_enterprise(user)

    AuditLog.log(
        action="scim_user_provisioned",
        resource_type="user",
        resource_id=str(user.pk),
        actor_email=f"scim:{org.slug}",
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "email": email,
            "user_created": created,
        },
    )

    return 201, _serialize_scim_user(user, org_slug)


@scim_api.put(
    "/{org_slug}/Users/{user_id}",
    response={
        200: SCIMUserResource,
        400: SCIMError,
        403: SCIMError,
        404: SCIMError,
        429: SCIMError,
    },
)
def replace_scim_user(
    request, org_slug: str, user_id: int, body: ReplaceSCIMUserRequest
):
    """Replace (full update) a SCIM user resource."""
    rate_err = _check_rate_limit(request)
    if rate_err:
        return rate_err

    org = _get_org_from_slug(request, org_slug)
    if org is None:
        return _scim_org_error_or_429(request)

    membership = org.memberships.filter(user_id=user_id).select_related("user").first()
    if membership is None:
        return _scim_error(404, "User not found in this organization.")

    user = membership.user
    changes = {}

    # Update name
    if body.name and body.name.givenName is not None:
        if user.name != body.name.givenName:
            changes["name"] = {"old": user.name, "new": body.name.givenName}
            user.name = body.name.givenName

    # Update active status
    if user.is_active != body.active:
        changes["active"] = {"old": user.is_active, "new": body.active}
        user.is_active = body.active

    user.save()

    AuditLog.log(
        action="scim_user_updated",
        resource_type="user",
        resource_id=str(user.pk),
        actor_email=f"scim:{org.slug}",
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        changes=changes,
        metadata={"organization_id": str(org.pk)},
    )

    return 200, _serialize_scim_user(user, org_slug)


@scim_api.patch(
    "/{org_slug}/Users/{user_id}",
    response={
        200: SCIMUserResource,
        400: SCIMError,
        403: SCIMError,
        404: SCIMError,
        429: SCIMError,
    },
)
def patch_scim_user(request, org_slug: str, user_id: int, body: PatchSCIMUserRequest):
    """Partial update a SCIM user via PATCH operations (RFC 7644 Section 3.5.2)."""
    rate_err = _check_rate_limit(request)
    if rate_err:
        return rate_err

    org = _get_org_from_slug(request, org_slug)
    if org is None:
        return _scim_org_error_or_429(request)

    membership = org.memberships.filter(user_id=user_id).select_related("user").first()
    if membership is None:
        return _scim_error(404, "User not found in this organization.")

    user = membership.user
    changes = {}

    for op in body.Operations:
        if op.op not in ("add", "replace", "remove"):
            return _scim_error(400, f"Unsupported operation: {op.op}")

        if op.path == "active" or (
            op.path is None and isinstance(op.value, dict) and "active" in op.value
        ):
            new_active = op.value if op.path == "active" else op.value.get("active")
            if isinstance(new_active, bool) and user.is_active != new_active:
                changes["active"] = {"old": user.is_active, "new": new_active}
                user.is_active = new_active

        elif op.path == "name.givenName":
            new_name = op.value if isinstance(op.value, str) else ""
            if user.name != new_name:
                changes["name"] = {"old": user.name, "new": new_name}
                user.name = new_name

        elif op.path == "userName":
            pass  # userName (email) is immutable in our system

    user.save()

    AuditLog.log(
        action="scim_user_updated",
        resource_type="user",
        resource_id=str(user.pk),
        actor_email=f"scim:{org.slug}",
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        changes=changes,
        metadata={"organization_id": str(org.pk)},
    )

    return 200, _serialize_scim_user(user, org_slug)


@scim_api.delete(
    "/{org_slug}/Users/{user_id}",
    response={200: SCIMUserResource, 403: SCIMError, 404: SCIMError, 409: SCIMError},
)
def delete_scim_user(request, org_slug: str, user_id: int):
    """Deprovision a user: set is_active=False and remove from org."""
    rate_err = _check_rate_limit(request)
    if rate_err:
        return rate_err

    org = _get_org_from_slug(request, org_slug)
    if org is None:
        return _scim_org_error_or_429(request)

    membership = org.memberships.filter(user_id=user_id).select_related("user").first()
    if membership is None:
        return _scim_error(404, "User not found in this organization.")

    # Refuse to deprovision the org owner
    if membership.role == OrganizationRole.OWNER:
        owner_count = org.memberships.filter(role=OrganizationRole.OWNER).count()
        if owner_count <= 1:
            return _scim_error(
                409, "Cannot deprovision the last owner of the organization."
            )

    user = membership.user

    with transaction.atomic():
        user.is_active = False
        user.save(update_fields=["is_active"])
        membership.delete()

    AuditLog.log(
        action="scim_user_deprovisioned",
        resource_type="user",
        resource_id=str(user.pk),
        actor_email=f"scim:{org.slug}",
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "email": user.email,
        },
    )

    return 200, _serialize_scim_user(user, org_slug)


# ── SCIM Discovery Endpoints ─────────────────────────────────────────────


@scim_api.get(
    "/{org_slug}/ServiceProviderConfig",
    response={200: dict, 403: SCIMError, 429: SCIMError},
)
def get_service_provider_config(request, org_slug: str):
    """SCIM ServiceProviderConfig (RFC 7643 Section 5)."""
    rate_err = _check_rate_limit(request)
    if rate_err:
        return rate_err

    org = _get_org_from_slug(request, org_slug)
    if org is None:
        return _scim_org_error_or_429(request)

    return 200, {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "https://docs.midsphere.com/scim",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Authentication scheme using SCIM bearer tokens.",
            }
        ],
    }


@scim_api.get(
    "/{org_slug}/Schemas",
    response={200: dict, 403: SCIMError, 429: SCIMError},
)
def get_schemas(request, org_slug: str):
    """SCIM Schemas endpoint (RFC 7643 Section 8.7.1)."""
    rate_err = _check_rate_limit(request)
    if rate_err:
        return rate_err

    org = _get_org_from_slug(request, org_slug)
    if org is None:
        return _scim_org_error_or_429(request)

    user_schema = {
        "id": "urn:ietf:params:scim:schemas:core:2.0:User",
        "name": "User",
        "description": "User Account",
        "attributes": [
            {
                "name": "userName",
                "type": "string",
                "multiValued": False,
                "required": True,
                "caseExact": False,
                "mutability": "readWrite",
                "returned": "default",
                "uniqueness": "server",
            },
            {
                "name": "name",
                "type": "complex",
                "multiValued": False,
                "required": False,
                "subAttributes": [
                    {
                        "name": "givenName",
                        "type": "string",
                        "multiValued": False,
                        "required": False,
                        "mutability": "readWrite",
                        "returned": "default",
                    },
                    {
                        "name": "familyName",
                        "type": "string",
                        "multiValued": False,
                        "required": False,
                        "mutability": "readWrite",
                        "returned": "default",
                    },
                ],
            },
            {
                "name": "active",
                "type": "boolean",
                "multiValued": False,
                "required": False,
                "mutability": "readWrite",
                "returned": "default",
            },
        ],
        "meta": {
            "resourceType": "Schema",
            "location": f"/api/v1/scim/v2/{org_slug}/Schemas/urn:ietf:params:scim:schemas:core:2.0:User",
        },
    }

    return 200, {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 1,
        "Resources": [user_schema],
    }


@scim_api.get(
    "/{org_slug}/ResourceTypes",
    response={200: dict, 403: SCIMError, 429: SCIMError},
)
def get_resource_types(request, org_slug: str):
    """SCIM ResourceTypes endpoint (RFC 7643 Section 8.7.2)."""
    rate_err = _check_rate_limit(request)
    if rate_err:
        return rate_err

    org = _get_org_from_slug(request, org_slug)
    if org is None:
        return _scim_org_error_or_429(request)

    return 200, {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 1,
        "Resources": [
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                "id": "User",
                "name": "User",
                "endpoint": f"/api/v1/scim/v2/{org_slug}/Users",
                "schema": "urn:ietf:params:scim:schemas:core:2.0:User",
                "meta": {
                    "resourceType": "ResourceType",
                    "location": f"/api/v1/scim/v2/{org_slug}/ResourceTypes/User",
                },
            }
        ],
    }
