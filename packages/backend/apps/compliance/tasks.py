"""Celery tasks for compliance data retention enforcement and scheduled exports."""

import csv
import io
import json
import logging
import time
from datetime import timedelta

import boto3
from celery import shared_task
from django.conf import settings as django_settings
from django.core.mail import EmailMessage
from django.utils import timezone

logger = logging.getLogger(__name__)

# Maps resource_type to (app_label, model_name, date_field)
RESOURCE_TYPE_MAP = {
    "audit_logs": ("compliance", "AuditLog", "timestamp"),
    "conversations": ("storage", "Conversation", "date_created"),
    "agent_runs": ("storage", "AgentRun", "created_at"),
    "webhook_events": ("billing", "WebhookEvent", "created_at"),
    "failed_payments": ("billing", "FailedPayment", "created_at"),
}


def _anonymize_conversations(queryset):
    """Anonymize conversations: set title to 'Deleted', clear summary."""
    return queryset.update(title="Deleted", summary="")


def _apply_policy(policy, dry_run=False):
    """Apply a single retention policy. Returns count of records affected."""
    from django.apps import apps

    mapping = RESOURCE_TYPE_MAP.get(policy.resource_type)
    if not mapping:
        logger.warning("No model mapping for resource_type=%s", policy.resource_type)
        return 0

    app_label, model_name, date_field = mapping
    model = apps.get_model(app_label, model_name)
    cutoff = timezone.now() - timedelta(days=policy.retention_days)
    expired_qs = model.objects.filter(**{f"{date_field}__lt": cutoff})
    count = expired_qs.count()

    if count == 0 or dry_run:
        return count

    if policy.action == "anonymize":
        if policy.resource_type == "conversations":
            _anonymize_conversations(expired_qs)
        else:
            logger.warning(
                "Anonymize action not implemented for resource_type=%s, skipping",
                policy.resource_type,
            )
            return 0
    elif policy.action == "delete":
        expired_qs.delete()
    # action == "keep" does nothing

    return count


@shared_task
def apply_retention_policies(dry_run=False):
    """Execute all active retention policies.

    Queries each active RetentionPolicy, finds expired records per resource_type,
    and applies the configured action (delete, anonymize, or keep).

    Args:
        dry_run: If True, log counts without taking any action.

    Returns:
        Dict with per-policy counts and summary.
    """
    from apps.compliance.models import AuditAction, AuditLog, RetentionPolicy

    policies = RetentionPolicy.objects.filter(is_active=True)
    results = {}

    for policy in policies:
        count = _apply_policy(policy, dry_run=dry_run)
        results[policy.resource_type] = count

        # Update policy run metadata
        if not dry_run:
            policy.last_run_at = timezone.now()
            policy.records_affected_last_run = count
            policy.save(update_fields=["last_run_at", "records_affected_last_run"])

        logger.info(
            "Retention policy %s: %d records %s (dry_run=%s)",
            policy.resource_type,
            count,
            "would be affected" if dry_run else "affected",
            dry_run,
        )

    # Create audit log entry
    AuditLog.log(
        action=AuditAction.DELETE if not dry_run else AuditAction.EXPORT,
        resource_type="retention_policy",
        metadata={
            "dry_run": dry_run,
            "results": results,
        },
    )

    return {"dry_run": dry_run, "results": results}


@shared_task
def check_sso_certificate_expiry():
    """Check all active SSO certificates for upcoming or past expiry.

    - Expiring within 30 days: create warning audit log entry.
    - Already expired: create critical audit log entry.

    Returns dict with per-org results.
    """
    from apps.compliance.models import AuditLog
    from apps.workspace.models import SSOConfiguration

    results = {}
    configs = SSOConfiguration.objects.filter(is_active=True).select_related(
        "organization"
    )

    for config in configs:
        if not config.certificate:
            continue

        expiry_date = _parse_certificate_expiry(config.certificate)
        if expiry_date is None:
            logger.warning(
                "Could not parse certificate expiry for SSO config %s (org: %s)",
                config.pk,
                config.organization.name,
            )
            continue

        now = timezone.now()
        days_until_expiry = (expiry_date - now).days
        org_name = config.organization.name
        org_id = str(config.organization.pk)

        if days_until_expiry < 0:
            # Certificate already expired
            AuditLog.log(
                action="sso_config_updated",
                resource_type="sso_certificate",
                resource_id=str(config.pk),
                metadata={
                    "organization_id": org_id,
                    "organization_name": org_name,
                    "severity": "critical",
                    "message": f"SSO certificate expired {abs(days_until_expiry)} day(s) ago",
                    "expiry_date": expiry_date.isoformat(),
                },
            )
            results[org_name] = {"status": "expired", "days": days_until_expiry}
            logger.warning(
                "SSO certificate EXPIRED for org '%s' (%d days ago)",
                org_name,
                abs(days_until_expiry),
            )

        elif days_until_expiry <= 30:
            # Certificate expiring soon
            AuditLog.log(
                action="sso_config_updated",
                resource_type="sso_certificate",
                resource_id=str(config.pk),
                metadata={
                    "organization_id": org_id,
                    "organization_name": org_name,
                    "severity": "warning",
                    "message": f"SSO certificate expires in {days_until_expiry} day(s)",
                    "expiry_date": expiry_date.isoformat(),
                },
            )
            results[org_name] = {"status": "expiring_soon", "days": days_until_expiry}
            logger.info(
                "SSO certificate expiring soon for org '%s' (%d days)",
                org_name,
                days_until_expiry,
            )
        else:
            results[org_name] = {"status": "ok", "days": days_until_expiry}

    return results


def _parse_certificate_expiry(cert_pem: str):
    """Parse a PEM certificate and return the expiry datetime, or None on failure."""
    try:
        from cryptography import x509

        # Handle certificates that may or may not have PEM headers
        if "-----BEGIN CERTIFICATE-----" not in cert_pem:
            cert_pem = (
                f"-----BEGIN CERTIFICATE-----\n{cert_pem}\n-----END CERTIFICATE-----"
            )

        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        expiry = cert.not_valid_after_utc
        # Return as timezone-aware datetime
        return (
            timezone.make_aware(expiry.replace(tzinfo=None))
            if timezone.is_naive(expiry)
            else expiry
        )
    except Exception:
        logger.exception("Failed to parse SSO certificate")
        return None


# ── Compliance Export Tasks ──────────────────────────────────────────────────


def _generate_audit_log_export(fmt, since=None):
    """Generate audit log export data in the given format.

    Returns (content_bytes, record_count).
    """
    from apps.compliance.models import AuditLog

    qs = AuditLog.objects.all().order_by("timestamp")
    if since:
        qs = qs.filter(timestamp__gt=since)

    records = list(
        qs.values(
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
        )
    )
    count = len(records)

    if fmt == "json":
        # Serialize UUIDs and datetimes
        for r in records:
            r["id"] = str(r["id"])
            r["timestamp"] = r["timestamp"].isoformat()
        content = json.dumps(records, indent=2, default=str).encode("utf-8")
    else:
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
        for r in records:
            writer.writerow(
                [
                    str(r["id"]),
                    r["timestamp"].isoformat(),
                    r["actor_email"],
                    r["actor_ip"] or "",
                    r["action"],
                    r["resource_type"],
                    r["resource_id"],
                    r["request_id"],
                    str(r["changes"]),
                    str(r["metadata"]),
                ]
            )
        content = buf.getvalue().encode("utf-8")

    return content, count


def _generate_consent_export(fmt, since=None):
    """Generate consent records export data.

    Returns (content_bytes, record_count).
    """
    from apps.compliance.models import ConsentRecord

    qs = ConsentRecord.objects.all().order_by("recorded_at")
    if since:
        qs = qs.filter(recorded_at__gt=since)

    records = list(
        qs.values(
            "id",
            "user_email",
            "consent_type",
            "version",
            "action",
            "recorded_at",
            "ip_address",
        )
    )
    count = len(records)

    if fmt == "json":
        for r in records:
            r["id"] = str(r["id"])
            r["recorded_at"] = r["recorded_at"].isoformat()
        content = json.dumps(records, indent=2, default=str).encode("utf-8")
    else:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "user_email",
                "consent_type",
                "version",
                "action",
                "recorded_at",
                "ip_address",
            ]
        )
        for r in records:
            writer.writerow(
                [
                    str(r["id"]),
                    r["user_email"],
                    r["consent_type"],
                    r["version"],
                    r["action"],
                    r["recorded_at"].isoformat(),
                    r["ip_address"] or "",
                ]
            )
        content = buf.getvalue().encode("utf-8")

    return content, count


def _generate_retention_export(fmt, since=None):
    """Generate retention policy status export data.

    Returns (content_bytes, record_count).
    """
    from apps.compliance.models import RetentionPolicy

    qs = RetentionPolicy.objects.all().order_by("resource_type")
    records = list(
        qs.values(
            "id",
            "resource_type",
            "retention_days",
            "action",
            "is_active",
            "last_run_at",
            "records_affected_last_run",
        )
    )
    count = len(records)

    if fmt == "json":
        for r in records:
            r["id"] = str(r["id"])
            if r["last_run_at"]:
                r["last_run_at"] = r["last_run_at"].isoformat()
        content = json.dumps(records, indent=2, default=str).encode("utf-8")
    else:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "resource_type",
                "retention_days",
                "action",
                "is_active",
                "last_run_at",
                "records_affected_last_run",
            ]
        )
        for r in records:
            writer.writerow(
                [
                    str(r["id"]),
                    r["resource_type"],
                    r["retention_days"],
                    r["action"],
                    r["is_active"],
                    r["last_run_at"].isoformat() if r["last_run_at"] else "",
                    r["records_affected_last_run"],
                ]
            )
        content = buf.getvalue().encode("utf-8")

    return content, count


_EXPORT_GENERATORS = {
    "audit_log": _generate_audit_log_export,
    "consent": _generate_consent_export,
    "retention": _generate_retention_export,
}


def _upload_to_s3(content, filename, config):
    """Upload export content to S3 bucket.

    config should have: {bucket: str, prefix: str (optional)}
    Credentials from Vault/env: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_REGION_NAME
    """
    bucket = config.get("bucket", "")
    prefix = config.get("prefix", "compliance-exports")
    key = f"{prefix}/{filename}" if prefix else filename

    client = boto3.client(
        "s3",
        aws_access_key_id=getattr(django_settings, "AWS_ACCESS_KEY_ID", None),
        aws_secret_access_key=getattr(django_settings, "AWS_SECRET_ACCESS_KEY", None),
        region_name=getattr(django_settings, "AWS_S3_REGION_NAME", "us-east-1"),
    )
    client.put_object(Bucket=bucket, Key=key, Body=content)
    logger.info("Uploaded compliance export to s3://%s/%s", bucket, key)
    return f"s3://{bucket}/{key}"


def _send_email_export(content, filename, config):
    """Send export as email attachment or download link.

    config should have: {emails: [str, ...]}
    Attaches file directly if <10MB.
    """
    emails = config.get("emails", [])
    if not emails:
        logger.warning("No email recipients configured for export")
        return

    size_mb = len(content) / (1024 * 1024)
    subject = f"Compliance Export: {filename}"

    msg = EmailMessage(
        subject=subject,
        body=f"Automated compliance export generated at {timezone.now().isoformat()}.\n\nRecords included in: {filename}",
        to=emails,
    )

    if size_mb < 10:
        msg.attach(filename, content, "application/octet-stream")
    else:
        msg.body += f"\n\nNote: Export file is {size_mb:.1f}MB (exceeds 10MB limit for attachments). Please use S3 destination for large exports."

    msg.send()
    logger.info("Sent compliance export email to %s", emails)


def _should_run_now(config):
    """Check if config's schedule means it should run in this invocation.

    The task runs hourly. We check whether the schedule period has elapsed
    since last_export_at.
    """
    if not config.last_export_at:
        return True  # Never run before

    now = timezone.now()
    elapsed = now - config.last_export_at

    if config.schedule == "daily":
        return elapsed >= timedelta(hours=23)
    elif config.schedule == "weekly":
        return elapsed >= timedelta(days=6, hours=23)
    elif config.schedule == "monthly":
        return elapsed >= timedelta(days=29)
    return False


@shared_task
def run_compliance_exports():
    """Execute all active compliance export configurations.

    Checks each active ComplianceExportConfig, generates the export if
    the schedule dictates, and delivers to the configured destination.

    Returns dict with results per config ID.
    """
    from apps.compliance.models import AuditAction, AuditLog, ComplianceExportConfig

    configs = ComplianceExportConfig.objects.filter(is_active=True)
    results = {}

    for config in configs:
        config_id = str(config.pk)

        if not _should_run_now(config):
            results[config_id] = {"status": "skipped", "reason": "not_due"}
            continue

        generator = _EXPORT_GENERATORS.get(config.export_type)
        if not generator:
            logger.warning("No export generator for type=%s", config.export_type)
            results[config_id] = {"status": "error", "reason": "unknown_export_type"}
            continue

        start_time = time.time()
        try:
            content, record_count = generator(
                config.format, since=config.last_export_at
            )
        except Exception:
            logger.exception("Failed to generate export for config %s", config_id)
            results[config_id] = {"status": "error", "reason": "generation_failed"}
            continue

        # Build filename
        now = timezone.now()
        ext = "json" if config.format == "json" else "csv"
        filename = f"{config.export_type}_{now.strftime('%Y%m%d_%H%M%S')}.{ext}"

        # Deliver
        destination = ""
        try:
            if config.destination_type == "s3":
                destination = _upload_to_s3(
                    content, filename, config.destination_config
                )
            elif config.destination_type == "email":
                _send_email_export(content, filename, config.destination_config)
                destination = (
                    f"email:{','.join(config.destination_config.get('emails', []))}"
                )
        except Exception:
            logger.exception("Failed to deliver export for config %s", config_id)
            results[config_id] = {"status": "error", "reason": "delivery_failed"}
            continue

        duration_s = round(time.time() - start_time, 2)

        # Update config metadata
        config.last_export_at = now
        config.last_export_record_count = record_count
        config.save(update_fields=["last_export_at", "last_export_record_count"])

        # Audit log entry
        AuditLog.log(
            action=AuditAction.COMPLIANCE_EXPORT_RUN,
            resource_type="compliance_export_config",
            resource_id=config_id,
            metadata={
                "export_type": config.export_type,
                "format": config.format,
                "destination_type": config.destination_type,
                "destination": destination,
                "record_count": record_count,
                "duration_seconds": duration_s,
            },
        )

        results[config_id] = {
            "status": "success",
            "record_count": record_count,
            "destination": destination,
            "duration_seconds": duration_s,
        }
        logger.info(
            "Compliance export %s: %d records → %s (%.2fs)",
            config_id,
            record_count,
            destination,
            duration_s,
        )

    return results


@shared_task
def run_single_compliance_export(config_id):
    """Run a single compliance export immediately (triggered via API).

    Args:
        config_id: UUID string of the ComplianceExportConfig to run.

    Returns:
        Dict with export result.
    """
    from apps.compliance.models import AuditAction, AuditLog, ComplianceExportConfig

    try:
        config = ComplianceExportConfig.objects.get(pk=config_id)
    except ComplianceExportConfig.DoesNotExist:
        return {"status": "error", "reason": "config_not_found"}

    generator = _EXPORT_GENERATORS.get(config.export_type)
    if not generator:
        return {"status": "error", "reason": "unknown_export_type"}

    start_time = time.time()
    content, record_count = generator(config.format, since=config.last_export_at)

    now = timezone.now()
    ext = "json" if config.format == "json" else "csv"
    filename = f"{config.export_type}_{now.strftime('%Y%m%d_%H%M%S')}.{ext}"

    destination = ""
    if config.destination_type == "s3":
        destination = _upload_to_s3(content, filename, config.destination_config)
    elif config.destination_type == "email":
        _send_email_export(content, filename, config.destination_config)
        destination = f"email:{','.join(config.destination_config.get('emails', []))}"

    duration_s = round(time.time() - start_time, 2)

    config.last_export_at = now
    config.last_export_record_count = record_count
    config.save(update_fields=["last_export_at", "last_export_record_count"])

    AuditLog.log(
        action=AuditAction.COMPLIANCE_EXPORT_RUN,
        resource_type="compliance_export_config",
        resource_id=str(config.pk),
        metadata={
            "export_type": config.export_type,
            "format": config.format,
            "destination_type": config.destination_type,
            "destination": destination,
            "record_count": record_count,
            "duration_seconds": duration_s,
            "triggered": "manual",
        },
    )

    return {
        "status": "success",
        "record_count": record_count,
        "destination": destination,
        "duration_seconds": duration_s,
    }


# ── Conversation Archival Tasks ────────────────────────────────────────────


def _build_conversation_snapshot(conversation):
    """Build a JSON-serializable snapshot of a conversation for archival.

    Captures: conversation metadata, participants, agent runs (with events).
    """
    from apps.storage.models import AgentRun, ConversationParticipant

    snapshot = {
        "conversation_id": str(conversation.pk),
        "title": conversation.title or "",
        "summary": conversation.summary or "",
        "user_email": "",
        "date_created": conversation.date_created.isoformat()
        if conversation.date_created
        else None,
        "is_deleted": conversation.is_deleted,
        "metadata": conversation.metadata or {},
        "participants": [],
        "agent_runs": [],
    }

    # User email (conversation owner)
    if conversation.user:
        try:
            snapshot["user_email"] = conversation.user.email or ""
        except Exception:
            snapshot["user_email"] = ""

    # Participants
    participants = ConversationParticipant.objects.filter(
        conversation=conversation,
    ).select_related("user")
    for p in participants:
        snapshot["participants"].append(
            {
                "email": p.user.email if p.user else "",
                "username": str(p.user) if p.user else "",
                "role": p.role,
                "joined_at": p.joined_at.isoformat() if p.joined_at else None,
            }
        )

    # Agent runs
    runs = AgentRun.objects.filter(conversation=conversation).order_by("created_at")
    for run in runs:
        run_data = {
            "id": str(run.pk),
            "run_id": run.run_id,
            "status": run.status,
            "task": run.task,
            "model": run.model,
            "error": run.error,
            "user_email": "",
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "metadata": run.metadata or {},
        }
        if run.user:
            try:
                run_data["user_email"] = run.user.email or ""
            except Exception:
                run_data["user_email"] = ""
        snapshot["agent_runs"].append(run_data)

    return snapshot


@shared_task
def archive_idle_conversations():
    """Archive conversations that have reached terminal state (all runs terminal + 1h idle).

    Runs hourly. Only archives conversations belonging to orgs with active archival policies.

    Returns dict with archival counts per organization.
    """
    from apps.compliance.models import AuditAction, AuditLog, ConversationArchive
    from apps.storage.models import AgentRun, Conversation
    from apps.workspace.models import OrgArchivalPolicy

    active_policies = OrgArchivalPolicy.objects.filter(
        is_active=True,
        archive_all_conversations=True,
    ).select_related("organization")

    if not active_policies.exists():
        return {"status": "no_active_policies", "archived": 0}

    results = {}
    total_archived = 0
    one_hour_ago = timezone.now() - timedelta(hours=1)

    for policy in active_policies:
        org = policy.organization
        org_id = str(org.pk)

        # Find org conversations via project.organization
        conversations = Conversation.objects.filter(
            project__organization=org,
            is_deleted=False,
        ).select_related("user", "project")

        archived_count = 0

        for conv in conversations:
            # Check if all runs are terminal
            active_runs = AgentRun.objects.filter(
                conversation=conv,
            ).exclude(status__in=AgentRun.TERMINAL_STATUSES)

            if active_runs.exists():
                continue

            # Check idle for 1 hour: last run finished > 1 hour ago
            last_run = (
                AgentRun.objects.filter(
                    conversation=conv,
                )
                .order_by("-finished_at")
                .first()
            )

            if (
                last_run
                and last_run.finished_at
                and last_run.finished_at > one_hour_ago
            ):
                continue

            # If no runs at all, check date_created
            if not last_run and conv.date_created > one_hour_ago:
                continue

            # Check if we already have an archive for this version
            existing = (
                ConversationArchive.objects.filter(
                    conversation=conv,
                )
                .order_by("-version")
                .first()
            )

            # Build snapshot
            snapshot = _build_conversation_snapshot(conv)
            content_hash = ConversationArchive.compute_hash(snapshot)

            # Skip if latest archive has same hash (no changes)
            if existing and existing.content_hash == content_hash:
                continue

            # Determine version
            next_version = (existing.version + 1) if existing else 1

            ConversationArchive.objects.create(
                conversation=conv,
                organization=org,
                archived_by="auto",
                content_hash=content_hash,
                content=snapshot,
                version=next_version,
            )
            archived_count += 1
            total_archived += 1

        results[org_id] = {"organization_name": org.name, "archived": archived_count}

        logger.info(
            "Archival for org '%s': %d conversations archived",
            org.name,
            archived_count,
        )

    # Audit log
    if total_archived > 0:
        AuditLog.log(
            action=AuditAction.CONVERSATION_ARCHIVED,
            resource_type="conversation_archive",
            metadata={
                "total_archived": total_archived,
                "per_org": results,
            },
        )

    return {"status": "ok", "archived": total_archived, "per_org": results}
