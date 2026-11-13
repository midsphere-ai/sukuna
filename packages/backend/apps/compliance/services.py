"""GDPR compliance services — user data export, account deletion, and consent management."""

import logging

from django.db import transaction
from django.utils import timezone

from apps.compliance.models import AuditAction, AuditLog, ConsentRecord, ConsentType
from apps.users.models import User

logger = logging.getLogger(__name__)


class OrgOwnerDeletionError(Exception):
    """Raised when a user who owns organizations tries to delete their account.

    The user must transfer ownership of all orgs before deletion can proceed.
    """

    def __init__(self, owned_orgs: list[dict]):
        self.owned_orgs = owned_orgs
        names = ", ".join(o["name"] for o in owned_orgs)
        super().__init__(
            f"Transfer org ownership before deleting account. You own: {names}"
        )


def export_user_data(user: User) -> dict:
    """Export all user data as a GDPR-compliant JSON-serializable dict.

    Collects profile, settings, conversations, agent runs, files, projects,
    billing, and audit records associated with the user.

    Args:
        user: The User instance whose data to export.

    Returns:
        A dict containing all user data organized by category.
    """
    data: dict = {
        "exported_at": timezone.now().isoformat(),
        "user_id": str(user.id),
    }

    # ── Profile ──────────────────────────────────────────────────────
    data["profile"] = {
        "email": user.email,
        "name": user.name,
        "nickname": user.nickname,
        "occupation": user.occupation,
        "avatar": user.avatar,
        "date_joined": user.date_joined.isoformat(),
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "is_active": user.is_active,
    }

    # ── Settings ─────────────────────────────────────────────────────
    try:
        s = user.settings
        data["settings"] = {
            "theme": s.theme,
            "accent_color": s.accent_color,
            "custom_instructions": s.custom_instructions,
            "nickname": s.nickname,
            "occupation": s.occupation,
            "about_you": s.about_you,
            "web_search": s.web_search,
            "browser": s.browser,
            "shell_commands": s.shell_commands,
            "complex_reasoning": s.complex_reasoning,
            "computer_use": s.computer_use,
            "notification_email": s.notification_email,
            "notification_push": s.notification_push,
            "notification_marketing": s.notification_marketing,
            "data_share_analytics": s.data_share_analytics,
            "data_share_training": s.data_share_training,
            "local_mode": s.local_mode,
        }
    except User.settings.RelatedObjectDoesNotExist:  # type: ignore[attr-defined]
        data["settings"] = None

    # ── API Keys (metadata only — hashes are not exportable) ─────────
    data["api_keys"] = [
        {
            "name": k.name,
            "key_prefix": k.key_prefix,
            "scopes": k.scopes,
            "is_active": k.is_active,
            "created_at": k.date_created.isoformat(),
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        }
        for k in user.developer_api_keys.all()
    ]

    # ── Projects ─────────────────────────────────────────────────────
    data["projects"] = [
        {
            "id": str(p.id),
            "title": p.title,
            "description": p.description,
            "icon": p.icon,
            "custom_instructions": p.custom_instructions,
            "created_at": p.date_created.isoformat(),
            "updated_at": p.date_updated.isoformat(),
        }
        for p in user.projects.all()
    ]

    # ── Organization Memberships ────────────────────────────────────
    try:
        from apps.workspace.models import OrganizationMembership

        data["organization_memberships"] = [
            {
                "org_name": m.organization.name,
                "org_id": str(m.organization.id),
                "role": m.role,
                "joined_at": m.joined_at.isoformat(),
            }
            for m in OrganizationMembership.objects.filter(user=user).select_related(
                "organization"
            )
        ]
    except Exception:
        data["organization_memberships"] = []

    # ── Conversations ────────────────────────────────────────────────
    # Include owned conversations AND conversations user participates in.
    # For shared/participated conversations, export only the user's own
    # metadata (title, dates) — exclude summary for data minimization.

    from apps.storage.models import ConversationParticipant

    seen_conv_ids: set = set()
    conversations = []

    # Owned conversations
    for c in user.speaking_to.select_related("project").all():
        seen_conv_ids.add(c.id)
        conv_data: dict = {
            "id": str(c.id),
            "title": c.title,
            "icon": c.icon,
            "project_id": str(c.project_id) if c.project_id else None,
            "created_at": c.date_created.isoformat(),
            "updated_at": c.date_updated.isoformat(),
        }
        metadata = c.metadata or {}
        if metadata.get("shared"):
            conv_data["shared"] = True
        else:
            conv_data["summary"] = c.summary
        conversations.append(conv_data)

    # Participated conversations (not already included as owned)
    participated = (
        ConversationParticipant.objects.filter(user=user)
        .exclude(conversation_id__in=seen_conv_ids)
        .select_related("conversation", "conversation__project")
    )
    for p in participated:
        c = p.conversation
        conv_data = {
            "id": str(c.id),
            "title": c.title,
            "icon": c.icon,
            "project_id": str(c.project_id) if c.project_id else None,
            "created_at": c.date_created.isoformat(),
            "updated_at": c.date_updated.isoformat(),
            "shared": True,
            "participant_role": p.role,
            "joined_at": p.joined_at.isoformat(),
            # Summary excluded for data minimization in shared conversations.
        }
        conversations.append(conv_data)
    data["conversations"] = conversations

    # ── Agent Runs ───────────────────────────────────────────────────
    data["agent_runs"] = [
        {
            "id": str(r.id),
            "conversation_id": str(r.conversation_id),
            "task": r.task,
            "status": r.status,
            "model": r.model,
            "error": r.error,
            "created_at": r.created_at.isoformat(),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "rating": r.rating,
        }
        for r in user.agent_runs.all()
    ]

    # ── Files ────────────────────────────────────────────────────────
    data["files"] = [
        {
            "id": str(f.id),
            "name": f.name,
            "size": f.size,
            "mime_type": f.mime_type,
            "uploaded_at": f.uploaded_at.isoformat(),
        }
        for f in user.stored_files.all()
    ]

    # ── Marketplace Addons ───────────────────────────────────────────
    data["marketplace_addons"] = [
        {
            "id": str(a.id),
            "addon_name": a.enabled_addon.name if a.enabled_addon else None,
            "auth_complete": a.auth_complete,
            "created_at": a.date_created.isoformat(),
        }
        for a in user.addon_owner.select_related("enabled_addon").all()
    ]

    # ── Installed Skills ─────────────────────────────────────────────
    data["installed_skills"] = [
        {
            "skill_slug": s.skill.slug,
            "skill_name": s.skill.name,
            "installed_at": s.installed_at.isoformat(),
        }
        for s in user.installed_skills.select_related("skill").all()
    ]

    # ── System Memory ────────────────────────────────────────────────
    data["system_memory"] = [
        {
            "memory_summary": m.memory_summary,
            "created_at": m.date_created.isoformat(),
        }
        for m in user.mem_speaking_to.all()
    ]

    # ── MCP Configs (no secrets) ─────────────────────────────────────
    data["mcp_configs"] = [
        {
            "server_name": mc.server_name,
            "server_type": mc.server_type,
            "description": mc.description,
            "created_at": mc.date_created.isoformat(),
        }
        for mc in user.mcp_configs.all()
    ]

    # ── Provider Configs (no API keys) ───────────────────────────────
    data["provider_configs"] = [
        {
            "tool_slot": pc.tool_slot,
            "provider_name": pc.provider_name,
            "model_name": pc.model_name,
            "is_active": pc.is_active,
            "created_at": pc.date_created.isoformat(),
        }
        for pc in user.provider_configs.all()
    ]

    # ── Scheduled Tasks ──────────────────────────────────────────────
    # The ScheduledTask model was removed in the backend-purge (Step 4). The
    # feature no longer exists; GDPR export keeps an empty list so downstream
    # consumers that indexed on the key don't break.
    data["scheduled_tasks"] = []

    # ── Billing ──────────────────────────────────────────────────────
    billing: dict = {}
    try:
        sub = user.subscription
        billing["subscription"] = {
            "plan": sub.plan.name if sub.plan else None,
            "status": sub.status,
            "start_date": sub.start_date.isoformat() if sub.start_date else None,
            "end_date": sub.end_date.isoformat() if sub.end_date else None,
            "auto_renew": sub.auto_renew,
            "created_at": sub.created_at.isoformat(),
        }
    except Exception:
        billing["subscription"] = None

    from apps.billing.models import Payment

    billing["payments"] = [
        {
            "amount": str(p.amount),
            "currency": p.currency,
            "status": p.status,
            "payment_method": p.payment_method,
            "created_at": p.created_at.isoformat(),
        }
        for p in Payment.objects.filter(user=user)
    ]

    try:
        wallet = user.credit_wallet
        billing["credit_wallet"] = {
            "monthly_credits": wallet.monthly_credits,
            "monthly_credits_remaining": wallet.monthly_credits_remaining,
            "addon_credits": wallet.addon_credits,
            "free_credits": wallet.free_credits,
            "daily_credits": wallet.daily_credits,
            "daily_credits_remaining": wallet.daily_credits_remaining,
        }
        from apps.billing.models import CreditTransaction

        billing["credit_transactions"] = [
            {
                "amount": tx.amount,
                "balance_after": tx.balance_after,
                "category": tx.category,
                "description": tx.description,
                "created_at": tx.created_at.isoformat(),
            }
            for tx in CreditTransaction.objects.filter(wallet=wallet)
        ]
    except Exception:
        billing["credit_wallet"] = None
        billing["credit_transactions"] = []

    data["billing"] = billing

    # ── Consent Records ─────────────────────────────────────────────
    data["consent_records"] = [
        {
            "consent_type": r.consent_type,
            "action": r.action,
            "version": r.version,
            "recorded_at": r.recorded_at.isoformat(),
            "ip_address": r.ip_address,
        }
        for r in ConsentRecord.objects.filter(user=user).order_by("-recorded_at")
    ]

    # ── Audit Log ────────────────────────────────────────────────────
    data["audit_log"] = [
        {
            "timestamp": a.timestamp.isoformat(),
            "action": a.action,
            "resource_type": a.resource_type,
            "resource_id": a.resource_id,
            "actor_ip": a.actor_ip,
            "metadata": a.metadata,
        }
        for a in AuditLog.objects.filter(actor_id=user.id)
    ]

    return data


def delete_user_account(
    user: User,
    *,
    actor_ip: str | None = None,
    request_id: str = "",
    reason: str = "",
) -> dict:
    """Delete a user account and anonymize/cascade all related data.

    Enterprise-aware: refuses deletion if the user is an org owner (must
    transfer ownership first). Removes non-owner org memberships, anonymizes
    shared conversations, and refunds credits for cancelled active runs.

    This is an atomic operation: either everything succeeds or nothing changes.
    An immutable audit record is created BEFORE the user is deleted so the
    actor info is preserved.

    Args:
        user: The User instance to delete.
        actor_ip: The IP address of the request.
        request_id: Correlation ID from request middleware.
        reason: Optional reason for deletion (stored in audit metadata).

    Returns:
        A dict summarizing what was deleted/anonymized.

    Raises:
        OrgOwnerDeletionError: If the user owns one or more organizations.
    """
    from apps.workspace.models import OrganizationMembership, OrganizationRole

    # ── 0. Block deletion if user owns any organizations ─────────
    owned_memberships = OrganizationMembership.objects.filter(
        user=user, role=OrganizationRole.OWNER
    ).select_related("organization")
    if owned_memberships.exists():
        owned_orgs = [
            {"id": str(m.organization.id), "name": m.organization.name}
            for m in owned_memberships
        ]
        raise OrgOwnerDeletionError(owned_orgs)

    user_id = user.id
    user_email = user.email
    summary: dict = {"user_id": str(user_id), "email": user_email}

    with transaction.atomic():
        # ── 1. Remove from all organizations (non-owner) ─────────────
        org_memberships = OrganizationMembership.objects.filter(user=user)
        summary["org_memberships_removed"] = org_memberships.count()
        org_memberships.delete()

        # ── 2. Cancel active agent runs + refund credits ─────────────
        from apps.storage.models import AgentRun

        active_runs = AgentRun.objects.filter(
            user=user,
            status__in=["queued", "provisioning", "pending", "running"],
        )
        cancelled_count = 0
        credits_refunded = 0
        for run in active_runs:
            try:
                run.transition_to("cancelled")
                cancelled_count += 1
                # Refund any active credit hold for this run
                credits_refunded += _refund_run_credits(run)
            except ValueError:
                pass
        summary["agent_runs_cancelled"] = cancelled_count
        summary["credits_refunded"] = credits_refunded

        # ── 3. Scheduled tasks + persistent (Claw) sandboxes removed as part of
        # the backend purge — nothing to unschedule/destroy at user-delete time.
        summary["scheduled_tasks_removed"] = 0
        summary["persistent_sandbox_destroyed"] = False

        # ── 4. Anonymize shared conversations ────────────────────────
        # Shared conversations survive deletion so other participants'
        # context remains coherent.  User's messages are anonymized to
        # '[Deleted User]'.
        from apps.storage.models import Conversation

        shared_convs = Conversation.objects.filter(user=user, metadata__shared=True)
        shared_count = shared_convs.count()
        shared_convs.update(
            title="[Deleted User]",
            summary="",
            user=None,
        )
        summary["shared_conversations_anonymized"] = shared_count

        # ── 5. Collect counts before deletion ────────────────────────
        # Only count non-shared conversations (shared ones were already
        # detached from the user above).
        summary["conversations_deleted"] = user.speaking_to.count()
        summary["projects_deleted"] = user.projects.count()
        summary["files_deleted"] = user.stored_files.count()
        summary["api_keys_deleted"] = user.developer_api_keys.count()

        # ── 6. Create audit record BEFORE deletion ───────────────────
        metadata = {"reason": reason} if reason else {}
        metadata["summary"] = summary.copy()
        AuditLog.log(
            action=AuditAction.DELETE,
            resource_type="user",
            resource_id=str(user_id),
            actor_id=user_id,
            actor_email=user_email,
            actor_ip=actor_ip,
            request_id=request_id,
            metadata=metadata,
        )

        # ── 7. Delete user (CASCADE handles related objects) ─────────
        # Django's CASCADE will delete: UserSettings, DeveloperAPIKey,
        # PasswordResetOTP, Project (→ ProjectFile), Conversation (→ AgentRun
        # via conversation FK, ConversationFile, ConversationComposioAddon,
        # ConversationPlan), StoredFile, UserMarketplaceAddons,
        # UserInstalledSkill, UserCustomMCPConfig, UserProviderConfig,
        # ScheduledTask, UserSubscription (→ CreditWallet → CreditGrant,
        # CreditHold, CreditTransaction), Payment, CustomerSupportTicket,
        # SystemWideMemory.
        #
        # SET_NULL FKs (SubscriptionHistory, FailedPayment, SubscriptionPause,
        # CouponUsage, UsageRecord, TrialPeriod, AgentRun.user) will have
        # their user field set to NULL automatically by Django.
        #
        # Shared conversations (user=None) are NOT affected by CASCADE
        # because they were already detached above.
        #
        # LIMITATION — Shared sandbox files:
        # For shared/team projects, all collaborators share the same E2B
        # sandbox filesystem. File attribution is NOT tracked within the
        # sandbox, so GDPR deletion cannot selectively remove one user's
        # files from the sandbox. On user deletion, shared sandbox files
        # contributed by the deleted user may persist. The sandbox's
        # Project.sandbox FK uses SET_NULL, so the sandbox record survives
        # but is unlinked from the deleted user's project.
        user.delete()

        summary["deleted"] = True

    logger.info(
        "[GDPR] User account deleted: user_id=%s email=%s",
        user_id,
        user_email,
    )
    return summary


def _refund_run_credits(run) -> int:
    """Refund active credit holds for a cancelled agent run.

    Returns the number of credits refunded (0 if no active hold).
    """
    try:
        from apps.billing.credit_service import CreditService
        from apps.billing.models import CreditHold

        hold = CreditHold.objects.filter(run=run, status="active").first()
        if hold is not None:
            CreditService.refund(hold, reason="GDPR account deletion")
            return hold.amount_consumed
    except Exception:
        logger.warning("Failed to refund credits for run %s", run.id, exc_info=True)
    return 0


# ---------------------------------------------------------------------------
# Consent management
# ---------------------------------------------------------------------------

# Map ConsentType values to UserSettings boolean field names.
_CONSENT_SETTINGS_MAP: dict[str, str] = {
    ConsentType.ANALYTICS: "data_share_analytics",
    ConsentType.TRAINING: "data_share_training",
    ConsentType.MARKETING: "notification_marketing",
}


def grant_consent(
    user: User,
    *,
    consent_type: str,
    version: str,
    ip_address: str | None = None,
    request_id: str = "",
) -> ConsentRecord:
    """Record that a user has granted a specific type of consent.

    Creates an immutable ConsentRecord and an audit log entry.
    If the consent type maps to a UserSettings boolean, that field is
    set to True for quick operational checks.

    Args:
        user: The user granting consent.
        consent_type: One of ConsentType values.
        version: Policy version being consented to.
        ip_address: Client IP address.
        request_id: Correlation request ID.

    Returns:
        The created ConsentRecord.
    """
    with transaction.atomic():
        record = ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=consent_type,
            version=version,
            action="granted",
            ip_address=ip_address,
        )

        _sync_settings(user, consent_type, granted=True)

        AuditLog.log(
            action=AuditAction.CONSENT_GRANTED,
            resource_type="consent",
            resource_id=str(record.pk),
            actor_id=user.pk,
            actor_email=user.email,
            actor_ip=ip_address,
            request_id=request_id,
            metadata={"consent_type": consent_type, "version": version},
        )

    return record


def revoke_consent(
    user: User,
    *,
    consent_type: str,
    version: str,
    ip_address: str | None = None,
    request_id: str = "",
) -> ConsentRecord:
    """Record that a user has revoked a specific type of consent.

    Creates an immutable ConsentRecord and an audit log entry.
    If the consent type maps to a UserSettings boolean, that field is
    set to False.

    Args:
        user: The user revoking consent.
        consent_type: One of ConsentType values.
        version: Policy version being revoked.
        ip_address: Client IP address.
        request_id: Correlation request ID.

    Returns:
        The created ConsentRecord.
    """
    with transaction.atomic():
        record = ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=consent_type,
            version=version,
            action="revoked",
            ip_address=ip_address,
        )

        _sync_settings(user, consent_type, granted=False)

        AuditLog.log(
            action=AuditAction.CONSENT_REVOKED,
            resource_type="consent",
            resource_id=str(record.pk),
            actor_id=user.pk,
            actor_email=user.email,
            actor_ip=ip_address,
            request_id=request_id,
            metadata={"consent_type": consent_type, "version": version},
        )

    return record


def get_current_consents(user: User) -> dict[str, dict]:
    """Return the latest consent state for each consent type.

    For each ConsentType, returns the most recent record (if any),
    giving a snapshot of what the user has currently consented to.

    Returns:
        Dict keyed by consent_type with latest record details, e.g.:
        ``{"analytics": {"action": "granted", "version": "1.0", ...}}``
    """
    result: dict[str, dict] = {}
    for ct_value, ct_label in ConsentType.choices:
        latest = (
            ConsentRecord.objects.filter(user=user, consent_type=ct_value)
            .order_by("-recorded_at")
            .first()
        )
        if latest:
            result[ct_value] = {
                "consent_type": ct_value,
                "action": latest.action,
                "version": latest.version,
                "recorded_at": latest.recorded_at.isoformat(),
                "ip_address": latest.ip_address,
            }
        else:
            result[ct_value] = {
                "consent_type": ct_value,
                "action": None,
                "version": None,
                "recorded_at": None,
                "ip_address": None,
            }
    return result


def get_consent_history(user: User) -> list[dict]:
    """Return the full consent history for a user, newest first.

    Returns:
        List of dicts, each representing one ConsentRecord.
    """
    records = ConsentRecord.objects.filter(user=user).order_by("-recorded_at")
    return [
        {
            "id": str(r.pk),
            "consent_type": r.consent_type,
            "action": r.action,
            "version": r.version,
            "recorded_at": r.recorded_at.isoformat(),
            "ip_address": r.ip_address,
        }
        for r in records
    ]


def _sync_settings(user: User, consent_type: str, *, granted: bool) -> None:
    """Sync a consent change to the corresponding UserSettings boolean field.

    Only applies for consent types that map to UserSettings fields
    (analytics, training, marketing). No-ops for others (terms_of_service,
    privacy_policy).
    """
    field_name = _CONSENT_SETTINGS_MAP.get(consent_type)
    if not field_name:
        return
    from apps.users.models import UserSettings

    settings_obj, _ = UserSettings.objects.get_or_create(user=user)
    setattr(settings_obj, field_name, granted)
    settings_obj.save(update_fields=[field_name])
