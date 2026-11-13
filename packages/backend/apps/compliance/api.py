"""GDPR compliance API endpoints — user data export, account deletion, consent management, and dashboard."""

import csv
import io
from typing import Optional
from uuid import UUID

from django.db.models import Q
from django.http import HttpResponse
from ninja import NinjaAPI, Schema

from apps.compliance.models import (
    AuditAction,
    AuditLog,
    ComplianceExportConfig,
    ConsentRecord,
    ConsentType,
    ConversationArchive,
    DestinationType,
    ExportFormat,
    ExportSchedule,
    ExportType,
    RetentionPolicy,
)
from apps.compliance.services import (
    OrgOwnerDeletionError,
    delete_user_account,
    export_user_data,
    get_consent_history,
    get_current_consents,
    grant_consent,
    revoke_consent,
)
from apps.users.adapters import NinjaAuthAdapter

compliance_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="compliance")


# ── Schemas ──────────────────────────────────────────────────────────────────


class DeleteAccountRequest(Schema):
    """Request body for account deletion — requires explicit confirmation."""

    confirm: bool
    reason: str = ""


class DeleteAccountResponse(Schema):
    """Response for account deletion."""

    success: bool
    message: str
    summary: dict | None = None


class ErrorResponse(Schema):
    """Standard error response."""

    detail: str


class OrgOwnerErrorResponse(Schema):
    """409 error when user owns organizations and cannot delete account."""

    detail: str
    owned_orgs: list[dict]


class ConsentRequest(Schema):
    """Request body for granting or revoking consent."""

    consent_type: str
    action: str  # "granted" or "revoked"
    version: str


class ConsentRecordOut(Schema):
    """A single consent record in API responses."""

    id: str | None = None
    consent_type: str
    action: str | None
    version: str | None
    recorded_at: str | None
    ip_address: str | None


# ── Endpoints ────────────────────────────────────────────────────────────────


@compliance_api.get(
    "/users/me/export",
    response={200: dict},
    summary="Export all user data (GDPR)",
)
def gdpr_export(request):
    """Export all data associated with the authenticated user.

    Returns a JSON object containing profile, settings, conversations,
    agent runs, files, billing, and audit records. Secrets and hashed
    values are excluded.
    """
    user = request.auth
    data = export_user_data(user)

    # Audit the export
    actor_ip = _get_client_ip(request)
    request_id = getattr(request, "request_id", "")
    AuditLog.log(
        action=AuditAction.EXPORT,
        resource_type="user",
        resource_id=str(user.id),
        actor_id=user.id,
        actor_email=user.email,
        actor_ip=actor_ip,
        request_id=request_id,
    )

    return data


@compliance_api.delete(
    "/users/me",
    response={
        200: DeleteAccountResponse,
        400: ErrorResponse,
        409: OrgOwnerErrorResponse,
    },
    summary="Delete user account (GDPR right to erasure)",
)
def gdpr_delete(request, body: DeleteAccountRequest):
    """Permanently delete the authenticated user's account and all associated data.

    Requires ``confirm: true`` in the request body. This action is irreversible.
    All conversations, files, projects, billing data, and agent configurations
    will be permanently deleted. SET_NULL foreign keys (billing history, usage
    records) will be anonymized.

    Returns 409 if the user owns any organizations — ownership must be
    transferred before the account can be deleted.
    """
    if not body.confirm:
        return 400, {"detail": "You must set confirm=true to delete your account."}

    user = request.auth
    actor_ip = _get_client_ip(request)
    request_id = getattr(request, "request_id", "")

    try:
        summary = delete_user_account(
            user,
            actor_ip=actor_ip,
            request_id=request_id,
            reason=body.reason,
        )
    except OrgOwnerDeletionError as exc:
        return 409, {
            "detail": "Transfer org ownership before deleting account.",
            "owned_orgs": exc.owned_orgs,
        }

    return 200, {
        "success": True,
        "message": "Your account and all associated data have been permanently deleted.",
        "summary": summary,
    }


# ── Consent Endpoints ────────────────────────────────────────────────────────


_VALID_CONSENT_TYPES = {c.value for c in ConsentType}
_VALID_CONSENT_ACTIONS = {"granted", "revoked"}


@compliance_api.get(
    "/consent",
    response={200: dict},
    summary="Get current consent status",
)
def consent_current(request):
    """Return the latest consent state for each consent type.

    Each key is a consent type; the value shows the most recent action
    (granted/revoked), policy version, and timestamp. Types with no
    record yet show null values.
    """
    user = request.auth
    return get_current_consents(user)


@compliance_api.post(
    "/consent",
    response={200: ConsentRecordOut, 400: ErrorResponse},
    summary="Grant or revoke consent",
)
def consent_update(request, body: ConsentRequest):
    """Create a new versioned consent record (grant or revoke).

    The ``consent_type`` must be one of: analytics, training, marketing,
    terms_of_service, privacy_policy.  The ``action`` must be "granted"
    or "revoked".  The ``version`` identifies which policy version the
    user is consenting to (or revoking).
    """
    if body.consent_type not in _VALID_CONSENT_TYPES:
        return 400, {
            "detail": f"Invalid consent_type. Must be one of: {', '.join(sorted(_VALID_CONSENT_TYPES))}"
        }
    if body.action not in _VALID_CONSENT_ACTIONS:
        return 400, {"detail": "Invalid action. Must be 'granted' or 'revoked'."}
    if not body.version.strip():
        return 400, {"detail": "version is required."}

    user = request.auth
    ip = _get_client_ip(request)
    request_id = getattr(request, "request_id", "")

    if body.action == "granted":
        record = grant_consent(
            user,
            consent_type=body.consent_type,
            version=body.version.strip(),
            ip_address=ip,
            request_id=request_id,
        )
    else:
        record = revoke_consent(
            user,
            consent_type=body.consent_type,
            version=body.version.strip(),
            ip_address=ip,
            request_id=request_id,
        )

    return 200, {
        "id": str(record.pk),
        "consent_type": record.consent_type,
        "action": record.action,
        "version": record.version,
        "recorded_at": record.recorded_at.isoformat(),
        "ip_address": record.ip_address,
    }


@compliance_api.get(
    "/consent/history",
    response={200: list[ConsentRecordOut]},
    summary="Get full consent history",
)
def consent_history(request):
    """Return the complete consent change history for the authenticated user,
    ordered newest-first.
    """
    user = request.auth
    return get_consent_history(user)


# ── Security Policy ─────────────────────────────────────────────────────────


@compliance_api.get(
    "/security-policy",
    response={200: dict},
    summary="Get effective security policy for the current user",
)
def effective_security_policy(request):
    """Return the most restrictive security policy across all the user's organizations.

    This is what the SecurityPolicyMiddleware actually enforces. Users can check
    this endpoint to see whether MFA is required, what their session timeout is,
    and how many concurrent sessions are allowed.
    """
    user = request.auth
    from apps.compliance.security_middleware import get_effective_policy

    mfa_required, timeout_minutes, max_sessions, _sso_enforced = get_effective_policy(
        user
    )

    # Check if user actually has MFA enabled
    try:
        from allauth.mfa.utils import is_mfa_enabled

        mfa_enabled = is_mfa_enabled(user)
    except ImportError:
        mfa_enabled = False

    return {
        "mfa_required": mfa_required,
        "mfa_enabled": mfa_enabled,
        "session_timeout_minutes": timeout_minutes,
        "max_concurrent_sessions": max_sessions,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────


# ── Retention Policy Schemas ─────────────────────────────────────────────────


class RetentionPolicyOut(Schema):
    """Response schema for a retention policy."""

    id: str
    resource_type: str
    retention_days: int
    action: str
    is_active: bool
    last_run_at: str | None
    records_affected_last_run: int


class RetentionPolicyUpdate(Schema):
    """Request body for updating a retention policy."""

    retention_days: int | None = None
    action: str | None = None
    is_active: bool | None = None


# ── Retention Policy Endpoints ──────────────────────────────────────────────


@compliance_api.get(
    "/retention-policies",
    response={200: list[RetentionPolicyOut], 403: ErrorResponse},
    summary="List all retention policies (admin only)",
)
def list_retention_policies(request):
    """Return all retention policies. Superuser access required."""
    if not request.auth.is_superuser:
        return 403, {"detail": "Superuser access required."}

    policies = RetentionPolicy.objects.all()
    return 200, [
        {
            "id": str(p.pk),
            "resource_type": p.resource_type,
            "retention_days": p.retention_days,
            "action": p.action,
            "is_active": p.is_active,
            "last_run_at": p.last_run_at.isoformat() if p.last_run_at else None,
            "records_affected_last_run": p.records_affected_last_run,
        }
        for p in policies
    ]


@compliance_api.patch(
    "/retention-policies/{policy_id}",
    response={200: RetentionPolicyOut, 403: ErrorResponse, 404: ErrorResponse},
    summary="Update a retention policy (admin only)",
)
def update_retention_policy(request, policy_id: UUID, body: RetentionPolicyUpdate):
    """Update retention_days, action, or is_active on a policy. Superuser access required."""
    if not request.auth.is_superuser:
        return 403, {"detail": "Superuser access required."}

    try:
        policy = RetentionPolicy.objects.get(pk=policy_id)
    except RetentionPolicy.DoesNotExist:
        return 404, {"detail": "Retention policy not found."}

    update_fields = []
    if body.retention_days is not None:
        policy.retention_days = body.retention_days
        update_fields.append("retention_days")
    if body.action is not None:
        policy.action = body.action
        update_fields.append("action")
    if body.is_active is not None:
        policy.is_active = body.is_active
        update_fields.append("is_active")

    if update_fields:
        policy.save(update_fields=update_fields)

    return 200, {
        "id": str(policy.pk),
        "resource_type": policy.resource_type,
        "retention_days": policy.retention_days,
        "action": policy.action,
        "is_active": policy.is_active,
        "last_run_at": policy.last_run_at.isoformat() if policy.last_run_at else None,
        "records_affected_last_run": policy.records_affected_last_run,
    }


# ── Dashboard Endpoints ────────────────────────────────────────────────────


def _is_admin(user) -> bool:
    """Check if user is superuser or owner of any organization."""
    if user.is_superuser:
        return True
    from apps.workspace.models import OrganizationMembership, OrganizationRole

    return OrganizationMembership.objects.filter(
        user=user, role=OrganizationRole.OWNER
    ).exists()


def _get_active_org(user):
    """Return the user's active organization or None (personal space)."""
    from apps.users.models import UserSettings

    settings, _ = UserSettings.objects.get_or_create(user=user)
    org = settings.last_active_org
    if org is None:
        return None
    if not org.members.filter(pk=user.pk).exists():
        settings.last_active_org = None
        settings.save(update_fields=["last_active_org"])
        return None
    return org


def _admin_org_scope(user):
    """Return the list of org IDs a non-superuser admin may view compliance data for.

    Superusers get `None` (unrestricted). Org owners are restricted to the orgs they
    actually own. If the user has an active org set and it is one of their owned orgs,
    the scope narrows further to just that org — matching the rest of the app's
    "one active org at a time" model.
    """
    if user.is_superuser:
        return None

    from apps.workspace.models import OrganizationMembership, OrganizationRole

    owned_ids = list(
        OrganizationMembership.objects.filter(
            user=user, role=OrganizationRole.OWNER
        ).values_list("organization_id", flat=True)
    )

    active = _get_active_org(user)
    if active is not None and active.pk in owned_ids:
        return [active.pk]
    return owned_ids


def _scope_audit_log_qs(qs, org_ids):
    """Restrict an AuditLog queryset to entries related to the given org IDs.

    Matches rows where the resource is one of these orgs OR where the audit
    metadata records one of these orgs. Returns an empty queryset if the caller
    has no org scope at all (no orgs owned → nothing to show).
    """
    if org_ids is None:
        return qs
    if not org_ids:
        return qs.none()
    org_id_strs = [str(oid) for oid in org_ids]
    return qs.filter(
        Q(resource_type="organization", resource_id__in=org_id_strs)
        | Q(metadata__organization_id__in=org_id_strs)
    )


def _scoped_user_ids(org_ids):
    """Return the set of user IDs who are members of any of the given orgs.

    `None` means "no restriction" (superuser); an empty list means "no access".
    """
    if org_ids is None:
        return None
    if not org_ids:
        return []
    from apps.workspace.models import OrganizationMembership

    return list(
        OrganizationMembership.objects.filter(organization_id__in=org_ids)
        .values_list("user_id", flat=True)
        .distinct()
    )


@compliance_api.get(
    "/dashboard/summary",
    response={200: dict, 403: ErrorResponse},
    summary="Compliance dashboard summary",
)
def dashboard_summary(request):
    """High-level compliance metrics: audit log count, active retention policies,
    consent coverage, and MFA status."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    from apps.users.models import User

    org_ids = _admin_org_scope(request.auth)
    scoped_user_ids = _scoped_user_ids(org_ids)

    users_qs = User.objects.filter(is_active=True)
    if scoped_user_ids is not None:
        users_qs = users_qs.filter(pk__in=scoped_user_ids)
    total_users = users_qs.count()

    # Audit log — restricted to the caller's orgs
    total_audit_entries = _scope_audit_log_qs(AuditLog.objects.all(), org_ids).count()

    # Retention policies are global settings; non-superusers see nothing org-specific here
    if org_ids is None:
        active_retention_policies = RetentionPolicy.objects.filter(
            is_active=True
        ).count()
    else:
        active_retention_policies = 0

    # Consent coverage: % of in-scope active users who have granted at least one consent
    consent_qs = ConsentRecord.objects.filter(action="granted")
    if scoped_user_ids is not None:
        consent_qs = consent_qs.filter(user_id__in=scoped_user_ids)
    users_with_consent = consent_qs.values("user_id").distinct().count()
    consent_coverage_pct = (
        round(users_with_consent / total_users * 100, 1) if total_users else 0.0
    )

    # MFA — also scoped
    mfa_count = 0
    try:
        from allauth.mfa.models import Authenticator

        if scoped_user_ids is None:
            mfa_count = Authenticator.objects.values("user_id").distinct().count()
        else:
            mfa_count = (
                Authenticator.objects.filter(user_id__in=scoped_user_ids)
                .values("user_id")
                .distinct()
                .count()
            )
    except (ImportError, Exception):
        pass

    mfa_pct = round(mfa_count / total_users * 100, 1) if total_users else 0.0

    return 200, {
        "total_audit_entries": total_audit_entries,
        "active_retention_policies": active_retention_policies,
        "consent_coverage_percentage": consent_coverage_pct,
        "total_users": total_users,
        "mfa_enabled_count": mfa_count,
        "mfa_enabled_percentage": mfa_pct,
    }


@compliance_api.get(
    "/audit-log",
    response={200: dict, 403: ErrorResponse},
    summary="Paginated audit log with filters",
)
def audit_log_list(
    request,
    page: int = 1,
    page_size: int = 50,
    actor_email: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
):
    """Paginated audit log with filtering by actor, action, resource, dates, and keyword search."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    qs = _scope_audit_log_qs(AuditLog.objects.all(), _admin_org_scope(request.auth))

    if actor_email:
        qs = qs.filter(actor_email__icontains=actor_email)
    if action:
        qs = qs.filter(action=action)
    if resource_type:
        qs = qs.filter(resource_type=resource_type)
    if date_from:
        qs = qs.filter(timestamp__gte=date_from)
    if date_to:
        qs = qs.filter(timestamp__lte=date_to)
    if q:
        qs = qs.filter(
            Q(changes__icontains=q)
            | Q(metadata__icontains=q)
            | Q(actor_email__icontains=q)
            | Q(resource_id__icontains=q)
        )

    total = qs.count()
    page_size = min(max(page_size, 1), 200)
    page = max(page, 1)
    offset = (page - 1) * page_size
    entries = qs[offset : offset + page_size]

    results = [
        {
            "id": str(e.pk),
            "timestamp": e.timestamp.isoformat(),
            "actor_email": e.actor_email,
            "actor_ip": e.actor_ip,
            "action": e.action,
            "resource_type": e.resource_type,
            "resource_id": e.resource_id,
            "request_id": e.request_id,
            "changes": e.changes,
            "metadata": e.metadata,
        }
        for e in entries
    ]

    return 200, {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "results": results,
    }


@compliance_api.get(
    "/retention-status",
    response={200: list, 403: ErrorResponse},
    summary="Retention policy status with next run",
)
def retention_status(request):
    """Per-policy status including last_run_at, records_affected, and computed next_run."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    policies = RetentionPolicy.objects.all()

    # Compute next_run from Celery Beat schedule (daily at 3 AM UTC)
    from django.utils import timezone as tz

    now = tz.now()
    next_3am = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if next_3am <= now:
        next_3am += tz.timedelta(days=1)

    result = []
    for p in policies:
        result.append(
            {
                "id": str(p.pk),
                "resource_type": p.resource_type,
                "retention_days": p.retention_days,
                "action": p.action,
                "is_active": p.is_active,
                "last_run_at": p.last_run_at.isoformat() if p.last_run_at else None,
                "records_affected_last_run": p.records_affected_last_run,
                "next_scheduled_run": next_3am.isoformat() if p.is_active else None,
            }
        )

    return 200, result


@compliance_api.get(
    "/consent-overview",
    response={200: dict, 403: ErrorResponse},
    summary="Consent overview per type",
)
def consent_overview(request):
    """Per consent_type: granted/revoked counts and coverage percentage."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    from apps.users.models import User

    org_ids = _admin_org_scope(request.auth)
    scoped_user_ids = _scoped_user_ids(org_ids)

    users_qs = User.objects.filter(is_active=True)
    if scoped_user_ids is not None:
        users_qs = users_qs.filter(pk__in=scoped_user_ids)
    total_users = users_qs.count()

    def _scope_consent(qs):
        if scoped_user_ids is None:
            return qs
        return qs.filter(user_id__in=scoped_user_ids)

    overview = {}
    for ct_value, ct_label in ConsentType.choices:
        granted_users = (
            _scope_consent(
                ConsentRecord.objects.filter(consent_type=ct_value, action="granted")
            )
            .values("user_id")
            .distinct()
            .count()
        )
        revoked_users = (
            _scope_consent(
                ConsentRecord.objects.filter(consent_type=ct_value, action="revoked")
            )
            .values("user_id")
            .distinct()
            .count()
        )
        coverage_pct = (
            round(granted_users / total_users * 100, 1) if total_users else 0.0
        )

        overview[ct_value] = {
            "label": str(ct_label),
            "granted_count": granted_users,
            "revoked_count": revoked_users,
            "coverage_percentage": coverage_pct,
        }

    return 200, {"total_users": total_users, "consent_types": overview}


@compliance_api.get(
    "/mfa-status",
    response={200: dict, 403: ErrorResponse},
    summary="MFA enrollment status",
)
def mfa_status(request):
    """Total users, MFA-enabled count, and per-org enforcement status."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    from apps.users.models import User
    from apps.workspace.models import Organization

    org_ids = _admin_org_scope(request.auth)
    scoped_user_ids = _scoped_user_ids(org_ids)

    users_qs = User.objects.filter(is_active=True)
    if scoped_user_ids is not None:
        users_qs = users_qs.filter(pk__in=scoped_user_ids)
    total_users = users_qs.count()

    mfa_count = 0
    try:
        from allauth.mfa.models import Authenticator

        if scoped_user_ids is None:
            mfa_count = Authenticator.objects.values("user_id").distinct().count()
        else:
            mfa_count = (
                Authenticator.objects.filter(user_id__in=scoped_user_ids)
                .values("user_id")
                .distinct()
                .count()
            )
    except (ImportError, Exception):
        pass

    mfa_pct = round(mfa_count / total_users * 100, 1) if total_users else 0.0

    # Per-org enforcement — only orgs the caller owns (or all, for superuser)
    if org_ids is None:
        orgs = Organization.objects.all()
    else:
        orgs = Organization.objects.filter(pk__in=org_ids)
    org_enforcement = [
        {
            "id": str(org.pk),
            "name": org.name,
            "slug": org.slug,
            "mfa_required": org.mfa_required,
            "member_count": org.member_count(),
        }
        for org in orgs
    ]

    return 200, {
        "total_users": total_users,
        "mfa_enabled_count": mfa_count,
        "mfa_enabled_percentage": mfa_pct,
        "organizations": org_enforcement,
    }


@compliance_api.get(
    "/audit-log/export",
    response={403: ErrorResponse},
    summary="Export audit log as CSV",
)
def audit_log_export(
    request,
    actor_email: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
):
    """Export audit log entries as a CSV file, using the same filters as the list endpoint."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    qs = _scope_audit_log_qs(AuditLog.objects.all(), _admin_org_scope(request.auth))

    if actor_email:
        qs = qs.filter(actor_email__icontains=actor_email)
    if action:
        qs = qs.filter(action=action)
    if resource_type:
        qs = qs.filter(resource_type=resource_type)
    if date_from:
        qs = qs.filter(timestamp__gte=date_from)
    if date_to:
        qs = qs.filter(timestamp__lte=date_to)
    if q:
        qs = qs.filter(
            Q(changes__icontains=q)
            | Q(metadata__icontains=q)
            | Q(actor_email__icontains=q)
            | Q(resource_id__icontains=q)
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "timestamp",
            "actor_email",
            "actor_ip",
            "action",
            "resource_type",
            "resource_id",
            "request_id",
            "changes",
            "metadata",
        ]
    )
    for e in qs.iterator():
        writer.writerow(
            [
                str(e.pk),
                e.timestamp.isoformat(),
                e.actor_email,
                e.actor_ip or "",
                e.action,
                e.resource_type,
                e.resource_id,
                e.request_id,
                str(e.changes),
                str(e.metadata),
            ]
        )

    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="audit_log_export.csv"'
    return response


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_client_ip(request) -> str | None:
    """Extract client IP from X-Forwarded-For or REMOTE_ADDR."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ── Export Config Schemas ──────────────────────────────────────────────────


_VALID_EXPORT_TYPES = {c.value for c in ExportType}
_VALID_EXPORT_FORMATS = {c.value for c in ExportFormat}
_VALID_EXPORT_SCHEDULES = {c.value for c in ExportSchedule}
_VALID_DESTINATION_TYPES = {c.value for c in DestinationType}


class ExportConfigOut(Schema):
    """Response schema for a compliance export config."""

    id: str
    organization_id: str | None
    export_type: str
    format: str
    schedule: str
    destination_type: str
    destination_config: dict
    is_active: bool
    last_export_at: str | None
    last_export_record_count: int
    created_at: str


class ExportConfigCreate(Schema):
    """Request body for creating an export config."""

    organization_id: str | None = None
    export_type: str
    format: str = "csv"
    schedule: str = "daily"
    destination_type: str
    destination_config: dict = {}
    is_active: bool = True


class ExportConfigUpdate(Schema):
    """Request body for updating an export config."""

    export_type: str | None = None
    format: str | None = None
    schedule: str | None = None
    destination_type: str | None = None
    destination_config: dict | None = None
    is_active: bool | None = None


def _caller_can_access_org(user, organization_id) -> bool:
    """True iff the caller may view/modify resources scoped to `organization_id`.

    Superusers always pass. Org owners pass only for orgs they own. `None` means
    a platform-level (un-scoped) resource, only accessible to superusers.
    """
    if user.is_superuser:
        return True
    if organization_id is None:
        return False
    org_ids = _admin_org_scope(user) or []
    target = str(organization_id)
    return any(str(oid) == target for oid in org_ids)


def _serialize_export_config(c) -> dict:
    """Serialize a ComplianceExportConfig to a dict."""
    return {
        "id": str(c.pk),
        "organization_id": str(c.organization_id) if c.organization_id else None,
        "export_type": c.export_type,
        "format": c.format,
        "schedule": c.schedule,
        "destination_type": c.destination_type,
        "destination_config": c.destination_config,
        "is_active": c.is_active,
        "last_export_at": c.last_export_at.isoformat() if c.last_export_at else None,
        "last_export_record_count": c.last_export_record_count,
        "created_at": c.created_at.isoformat(),
    }


# ── Export Config Endpoints ───────────────────────────────────────────────


@compliance_api.get(
    "/export-configs",
    response={200: list[ExportConfigOut], 403: ErrorResponse},
    summary="List all compliance export configs (admin only)",
)
def list_export_configs(request):
    """Return compliance export configurations visible to the caller.

    Superusers see all. Org owners see only configs belonging to orgs they own.
    """
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    org_ids = _admin_org_scope(request.auth)
    configs = ComplianceExportConfig.objects.all()
    if org_ids is not None:
        configs = configs.filter(organization_id__in=org_ids)
    return 200, [_serialize_export_config(c) for c in configs]


@compliance_api.post(
    "/export-configs",
    response={201: ExportConfigOut, 400: ErrorResponse, 403: ErrorResponse},
    summary="Create a compliance export config (admin only)",
)
def create_export_config(request, body: ExportConfigCreate):
    """Create a new compliance export configuration."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    parsed_org_id = None
    if body.organization_id:
        try:
            parsed_org_id = UUID(body.organization_id)
        except (ValueError, TypeError):
            return 400, {"detail": "Invalid organization_id."}
    if not _caller_can_access_org(request.auth, parsed_org_id):
        return 403, {"detail": "Cannot create export config for this organization."}

    if body.export_type not in _VALID_EXPORT_TYPES:
        return 400, {
            "detail": f"Invalid export_type. Must be one of: {', '.join(sorted(_VALID_EXPORT_TYPES))}"
        }
    if body.format not in _VALID_EXPORT_FORMATS:
        return 400, {
            "detail": f"Invalid format. Must be one of: {', '.join(sorted(_VALID_EXPORT_FORMATS))}"
        }
    if body.schedule not in _VALID_EXPORT_SCHEDULES:
        return 400, {
            "detail": f"Invalid schedule. Must be one of: {', '.join(sorted(_VALID_EXPORT_SCHEDULES))}"
        }
    if body.destination_type not in _VALID_DESTINATION_TYPES:
        return 400, {
            "detail": f"Invalid destination_type. Must be one of: {', '.join(sorted(_VALID_DESTINATION_TYPES))}"
        }

    org = None
    if body.organization_id:
        from apps.workspace.models import Organization

        try:
            org = Organization.objects.get(pk=body.organization_id)
        except Organization.DoesNotExist:
            return 400, {"detail": "Organization not found."}

    config = ComplianceExportConfig.objects.create(
        organization=org,
        export_type=body.export_type,
        format=body.format,
        schedule=body.schedule,
        destination_type=body.destination_type,
        destination_config=body.destination_config,
        is_active=body.is_active,
    )

    return 201, _serialize_export_config(config)


@compliance_api.get(
    "/export-configs/{config_id}",
    response={200: ExportConfigOut, 403: ErrorResponse, 404: ErrorResponse},
    summary="Get a specific compliance export config (admin only)",
)
def get_export_config(request, config_id: UUID):
    """Return a single compliance export configuration."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    try:
        config = ComplianceExportConfig.objects.get(pk=config_id)
    except ComplianceExportConfig.DoesNotExist:
        return 404, {"detail": "Export config not found."}

    if not _caller_can_access_org(request.auth, config.organization_id):
        return 404, {"detail": "Export config not found."}

    return 200, _serialize_export_config(config)


@compliance_api.patch(
    "/export-configs/{config_id}",
    response={
        200: ExportConfigOut,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
    summary="Update a compliance export config (admin only)",
)
def update_export_config(request, config_id: UUID, body: ExportConfigUpdate):
    """Update fields on a compliance export configuration."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    try:
        config = ComplianceExportConfig.objects.get(pk=config_id)
    except ComplianceExportConfig.DoesNotExist:
        return 404, {"detail": "Export config not found."}

    if not _caller_can_access_org(request.auth, config.organization_id):
        return 404, {"detail": "Export config not found."}

    update_fields = []

    if body.export_type is not None:
        if body.export_type not in _VALID_EXPORT_TYPES:
            return 400, {
                "detail": f"Invalid export_type. Must be one of: {', '.join(sorted(_VALID_EXPORT_TYPES))}"
            }
        config.export_type = body.export_type
        update_fields.append("export_type")

    if body.format is not None:
        if body.format not in _VALID_EXPORT_FORMATS:
            return 400, {
                "detail": f"Invalid format. Must be one of: {', '.join(sorted(_VALID_EXPORT_FORMATS))}"
            }
        config.format = body.format
        update_fields.append("format")

    if body.schedule is not None:
        if body.schedule not in _VALID_EXPORT_SCHEDULES:
            return 400, {
                "detail": f"Invalid schedule. Must be one of: {', '.join(sorted(_VALID_EXPORT_SCHEDULES))}"
            }
        config.schedule = body.schedule
        update_fields.append("schedule")

    if body.destination_type is not None:
        if body.destination_type not in _VALID_DESTINATION_TYPES:
            return 400, {
                "detail": f"Invalid destination_type. Must be one of: {', '.join(sorted(_VALID_DESTINATION_TYPES))}"
            }
        config.destination_type = body.destination_type
        update_fields.append("destination_type")

    if body.destination_config is not None:
        config.destination_config = body.destination_config
        update_fields.append("destination_config")

    if body.is_active is not None:
        config.is_active = body.is_active
        update_fields.append("is_active")

    if update_fields:
        config.save(update_fields=update_fields)

    return 200, _serialize_export_config(config)


@compliance_api.delete(
    "/export-configs/{config_id}",
    response={200: dict, 403: ErrorResponse, 404: ErrorResponse},
    summary="Delete a compliance export config (admin only)",
)
def delete_export_config(request, config_id: UUID):
    """Delete a compliance export configuration."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    try:
        config = ComplianceExportConfig.objects.get(pk=config_id)
    except ComplianceExportConfig.DoesNotExist:
        return 404, {"detail": "Export config not found."}

    if not _caller_can_access_org(request.auth, config.organization_id):
        return 404, {"detail": "Export config not found."}

    config.delete()
    return 200, {"detail": "Export config deleted."}


@compliance_api.post(
    "/export-configs/{config_id}/run-now",
    response={200: dict, 403: ErrorResponse, 404: ErrorResponse},
    summary="Trigger an immediate compliance export (admin only)",
)
def run_export_now(request, config_id: UUID):
    """Trigger an immediate export run for the given configuration.

    The export runs synchronously and returns the result.
    """
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    try:
        config = ComplianceExportConfig.objects.get(pk=config_id)
    except ComplianceExportConfig.DoesNotExist:
        return 404, {"detail": "Export config not found."}

    if not _caller_can_access_org(request.auth, config.organization_id):
        return 404, {"detail": "Export config not found."}

    from apps.compliance.tasks import run_single_compliance_export

    result = run_single_compliance_export(str(config.pk))
    return 200, result


# ── Conversation Archive Endpoints ─────────────────────────────────────────


def _serialize_archive(a) -> dict:
    """Serialize a ConversationArchive to a dict."""
    return {
        "id": str(a.pk),
        "conversation_id": str(a.conversation_id) if a.conversation_id else None,
        "organization_id": str(a.organization_id),
        "archived_by": a.archived_by,
        "archived_at": a.archived_at.isoformat(),
        "content_hash": a.content_hash,
        "version": a.version,
    }


@compliance_api.get(
    "/archives",
    response={200: dict, 403: ErrorResponse},
    summary="List conversation archives (admin only, paginated)",
)
def list_archives(
    request,
    page: int = 1,
    page_size: int = 50,
    organization_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Paginated list of conversation archives, filterable by org, date range, conversation."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    qs = ConversationArchive.objects.all()

    # Restrict to orgs the caller owns (superusers unrestricted)
    scope_ids = _admin_org_scope(request.auth)
    if scope_ids is not None:
        if not scope_ids:
            qs = qs.none()
        else:
            qs = qs.filter(organization_id__in=scope_ids)

    if organization_id:
        # Only allow filter-narrowing within the caller's scope
        if scope_ids is not None and not any(
            str(oid) == organization_id for oid in scope_ids
        ):
            return 403, {"detail": "Cannot view archives for this organization."}
        qs = qs.filter(organization_id=organization_id)
    if conversation_id:
        qs = qs.filter(conversation_id=conversation_id)
    if date_from:
        qs = qs.filter(archived_at__gte=date_from)
    if date_to:
        qs = qs.filter(archived_at__lte=date_to)

    total = qs.count()
    page_size = min(max(page_size, 1), 200)
    page = max(page, 1)
    offset = (page - 1) * page_size
    entries = qs[offset : offset + page_size]

    results = [_serialize_archive(a) for a in entries]

    return 200, {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "results": results,
    }


@compliance_api.get(
    "/archives/{archive_id}/verify",
    response={200: dict, 403: ErrorResponse, 404: ErrorResponse},
    summary="Verify archive integrity (tamper check)",
)
def verify_archive(request, archive_id: UUID):
    """Recompute content hash and compare to stored hash for tamper evidence."""
    if not _is_admin(request.auth):
        return 403, {"detail": "Admin access required."}

    try:
        archive = ConversationArchive.objects.get(pk=archive_id)
    except ConversationArchive.DoesNotExist:
        return 404, {"detail": "Archive not found."}

    if not _caller_can_access_org(request.auth, archive.organization_id):
        return 404, {"detail": "Archive not found."}

    is_valid = archive.verify()

    AuditLog.log(
        action=AuditAction.ARCHIVE_VERIFIED,
        resource_type="conversation_archive",
        resource_id=str(archive.pk),
        actor_id=getattr(request.auth, "pk", None),
        actor_email=getattr(request.auth, "email", ""),
        metadata={
            "verified": is_valid,
            "stored_hash": archive.content_hash,
            "computed_hash": ConversationArchive.compute_hash(archive.content),
        },
    )

    return 200, {
        "id": str(archive.pk),
        "verified": is_valid,
        "stored_hash": archive.content_hash,
        "computed_hash": ConversationArchive.compute_hash(archive.content),
    }
