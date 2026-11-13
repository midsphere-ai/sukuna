"""Tests for ComplianceExportConfig model, API endpoints, and Celery tasks."""

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.compliance.models import (
    AuditLog,
    ComplianceExportConfig,
    ConsentRecord,
    RetentionPolicy,
)
from apps.compliance.tasks import (
    _generate_audit_log_export,
    _generate_consent_export,
    _generate_retention_export,
    _should_run_now,
    run_compliance_exports,
    run_single_compliance_export,
)
from apps.users.tests.factories import UserFactory


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def superuser():
    return UserFactory(is_superuser=True)


@pytest.fixture
def regular_user():
    return UserFactory()


def _authed_request(rf, method, path, user, body=None, **kwargs):
    factory_method = getattr(rf, method)
    if body is not None:
        request = factory_method(
            path,
            data=json.dumps(body),
            content_type="application/json",
            **kwargs,
        )
    else:
        request = factory_method(path, **kwargs)
    request.auth = user
    request.request_id = "test-req-id"
    return request


@pytest.fixture
def s3_export_config():
    return ComplianceExportConfig.objects.create(
        export_type="audit_log",
        format="csv",
        schedule="daily",
        destination_type="s3",
        destination_config={"bucket": "my-bucket", "prefix": "exports"},
        is_active=True,
    )


@pytest.fixture
def email_export_config():
    return ComplianceExportConfig.objects.create(
        export_type="consent",
        format="json",
        schedule="weekly",
        destination_type="email",
        destination_config={"emails": ["admin@example.com"]},
        is_active=True,
    )


# ── Model Tests ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestComplianceExportConfigModel:
    def test_create_config(self, s3_export_config):
        assert s3_export_config.pk is not None
        assert s3_export_config.export_type == "audit_log"
        assert s3_export_config.destination_type == "s3"
        assert s3_export_config.is_active is True
        assert s3_export_config.last_export_at is None
        assert s3_export_config.last_export_record_count == 0

    def test_str_representation(self, s3_export_config):
        result = str(s3_export_config)
        assert "audit_log" in result
        assert "s3" in result

    def test_nullable_org(self, s3_export_config):
        assert s3_export_config.organization is None

    def test_config_with_org(self):
        from apps.workspace.models import Organization

        org = Organization.objects.create(name="Test Org", slug="test-org")
        config = ComplianceExportConfig.objects.create(
            organization=org,
            export_type="consent",
            format="json",
            schedule="monthly",
            destination_type="email",
            destination_config={"emails": ["admin@example.com"]},
        )
        assert config.organization == org
        assert "Test Org" in str(config)


# ── Export Generation Tests ───────────────────────────────────────────────


@pytest.mark.django_db
class TestExportGeneration:
    def test_audit_log_csv_export(self):
        AuditLog.log(
            action="login",
            resource_type="user",
            resource_id="123",
            actor_email="test@example.com",
        )
        content, count = _generate_audit_log_export("csv")
        assert count == 1
        text = content.decode("utf-8")
        assert "test@example.com" in text
        assert "login" in text

    def test_audit_log_json_export(self):
        AuditLog.log(
            action="login",
            resource_type="user",
            resource_id="456",
            actor_email="json@example.com",
        )
        content, count = _generate_audit_log_export("json")
        assert count >= 1
        data = json.loads(content)
        assert isinstance(data, list)
        assert any(r["actor_email"] == "json@example.com" for r in data)

    def test_audit_log_incremental(self):
        # Create record in the past
        old = AuditLog.log(
            action="login",
            resource_type="user",
            resource_id="old",
        )
        AuditLog.objects.filter(pk=old.pk).update(
            timestamp=timezone.now() - timedelta(hours=2)
        )

        # Create recent record
        AuditLog.log(
            action="logout",
            resource_type="user",
            resource_id="new",
        )

        since = timezone.now() - timedelta(hours=1)
        content, count = _generate_audit_log_export("csv", since=since)
        assert count == 1
        assert b"new" in content
        assert b"old" not in content

    def test_consent_csv_export(self):
        user = UserFactory()
        ConsentRecord.objects.create(
            user=user,
            user_email="consent@example.com",
            consent_type="analytics",
            version="1.0",
            action="granted",
        )
        content, count = _generate_consent_export("csv")
        assert count >= 1
        assert b"consent@example.com" in content

    def test_consent_json_export(self):
        user = UserFactory()
        ConsentRecord.objects.create(
            user=user,
            user_email="consent@example.com",
            consent_type="analytics",
            version="1.0",
            action="granted",
        )
        content, count = _generate_consent_export("json")
        assert count >= 1
        data = json.loads(content)
        assert isinstance(data, list)

    def test_consent_incremental(self):
        user = UserFactory()
        old = ConsentRecord.objects.create(
            user=user,
            user_email="old@example.com",
            consent_type="analytics",
            version="1.0",
            action="granted",
        )
        ConsentRecord.objects.filter(pk=old.pk).update(
            recorded_at=timezone.now() - timedelta(hours=2)
        )

        ConsentRecord.objects.create(
            user=user,
            user_email="new@example.com",
            consent_type="training",
            version="1.0",
            action="granted",
        )

        since = timezone.now() - timedelta(hours=1)
        content, count = _generate_consent_export("csv", since=since)
        assert count == 1
        assert b"new@example.com" in content

    def test_retention_csv_export(self):
        RetentionPolicy.objects.get_or_create(
            resource_type="test_export",
            defaults={"retention_days": 30, "action": "delete"},
        )
        content, count = _generate_retention_export("csv")
        assert count >= 1
        assert b"test_export" in content

    def test_retention_json_export(self):
        RetentionPolicy.objects.get_or_create(
            resource_type="test_export_json",
            defaults={"retention_days": 60, "action": "keep"},
        )
        content, count = _generate_retention_export("json")
        assert count >= 1
        data = json.loads(content)
        assert isinstance(data, list)


# ── Schedule Tests ────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestScheduleLogic:
    def test_never_run_before(self, s3_export_config):
        assert _should_run_now(s3_export_config) is True

    def test_daily_not_due(self, s3_export_config):
        s3_export_config.last_export_at = timezone.now() - timedelta(hours=12)
        assert _should_run_now(s3_export_config) is False

    def test_daily_is_due(self, s3_export_config):
        s3_export_config.last_export_at = timezone.now() - timedelta(hours=24)
        assert _should_run_now(s3_export_config) is True

    def test_weekly_not_due(self, email_export_config):
        email_export_config.last_export_at = timezone.now() - timedelta(days=3)
        assert _should_run_now(email_export_config) is False

    def test_weekly_is_due(self, email_export_config):
        email_export_config.last_export_at = timezone.now() - timedelta(days=7)
        assert _should_run_now(email_export_config) is True

    def test_monthly_not_due(self):
        config = ComplianceExportConfig.objects.create(
            export_type="retention",
            format="csv",
            schedule="monthly",
            destination_type="s3",
            destination_config={"bucket": "b"},
        )
        config.last_export_at = timezone.now() - timedelta(days=15)
        assert _should_run_now(config) is False

    def test_monthly_is_due(self):
        config = ComplianceExportConfig.objects.create(
            export_type="retention",
            format="csv",
            schedule="monthly",
            destination_type="s3",
            destination_config={"bucket": "b"},
        )
        config.last_export_at = timezone.now() - timedelta(days=30)
        assert _should_run_now(config) is True


# ── S3 Upload Mock Tests ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestS3Upload:
    @patch("apps.compliance.tasks.boto3")
    def test_s3_upload_called(self, mock_boto3, s3_export_config):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        AuditLog.log(action="login", resource_type="user", resource_id="1")

        result = run_single_compliance_export(str(s3_export_config.pk))

        assert result["status"] == "success"
        assert result["record_count"] >= 1
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "my-bucket"
        assert "exports/" in call_kwargs["Key"]

    @patch("apps.compliance.tasks.boto3")
    def test_s3_upload_updates_metadata(self, mock_boto3, s3_export_config):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        AuditLog.log(action="login", resource_type="user", resource_id="2")

        assert s3_export_config.last_export_at is None
        run_single_compliance_export(str(s3_export_config.pk))

        s3_export_config.refresh_from_db()
        assert s3_export_config.last_export_at is not None
        assert s3_export_config.last_export_record_count >= 1


# ── Email Delivery Mock Tests ────────────────────────────────────────────


@pytest.mark.django_db
class TestEmailDelivery:
    @patch("apps.compliance.tasks.EmailMessage")
    def test_email_sent(self, mock_email_cls, email_export_config):
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg

        user = UserFactory()
        ConsentRecord.objects.create(
            user=user,
            user_email="test@example.com",
            consent_type="analytics",
            version="1.0",
            action="granted",
        )

        result = run_single_compliance_export(str(email_export_config.pk))

        assert result["status"] == "success"
        mock_email_cls.assert_called_once()
        mock_msg.attach.assert_called_once()
        mock_msg.send.assert_called_once()

    @patch("apps.compliance.tasks.EmailMessage")
    def test_large_file_no_attachment(self, mock_email_cls, email_export_config):
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg

        # Patch generator to return >10MB content
        large_content = b"x" * (11 * 1024 * 1024)
        with patch(
            "apps.compliance.tasks._EXPORT_GENERATORS",
            {
                "consent": lambda fmt, since=None: (large_content, 999),
            },
        ):
            result = run_single_compliance_export(str(email_export_config.pk))

        assert result["status"] == "success"
        mock_msg.attach.assert_not_called()
        mock_msg.send.assert_called_once()


# ── Scheduled Task Tests ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestRunComplianceExports:
    @patch("apps.compliance.tasks.boto3")
    def test_runs_due_configs(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        config = ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="csv",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "test-bucket"},
            is_active=True,
        )
        AuditLog.log(action="login", resource_type="user", resource_id="1")

        results = run_compliance_exports()
        assert str(config.pk) in results
        assert results[str(config.pk)]["status"] == "success"

    @patch("apps.compliance.tasks.boto3")
    def test_skips_inactive_configs(self, mock_boto3):
        config = ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="csv",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "test-bucket"},
            is_active=False,
        )

        results = run_compliance_exports()
        assert str(config.pk) not in results

    @patch("apps.compliance.tasks.boto3")
    def test_skips_not_due(self, mock_boto3):
        config = ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="csv",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "test-bucket"},
            is_active=True,
            last_export_at=timezone.now() - timedelta(hours=1),
        )

        results = run_compliance_exports()
        assert results[str(config.pk)]["status"] == "skipped"

    @patch("apps.compliance.tasks.boto3")
    def test_creates_audit_log(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        config = ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="json",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "audit-bucket"},
            is_active=True,
        )
        AuditLog.log(action="login", resource_type="user", resource_id="1")

        run_compliance_exports()

        audit = AuditLog.objects.filter(
            action="compliance_export_run",
            resource_type="compliance_export_config",
            resource_id=str(config.pk),
        ).first()
        assert audit is not None
        assert audit.metadata["export_type"] == "audit_log"
        assert audit.metadata["record_count"] >= 1

    def test_config_not_found(self):
        result = run_single_compliance_export("00000000-0000-0000-0000-000000000000")
        assert result["status"] == "error"
        assert result["reason"] == "config_not_found"


# ── Beat Schedule Tests ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestBeatSchedule:
    def test_compliance_exports_in_beat_schedule(self):
        from django.conf import settings

        schedule = settings.CELERY_BEAT_SCHEDULE
        assert "run-compliance-exports" in schedule
        assert (
            schedule["run-compliance-exports"]["task"]
            == "apps.compliance.tasks.run_compliance_exports"
        )


# ── API Tests ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestExportConfigListAPI:
    def test_admin_can_list(self, rf, superuser):
        ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="csv",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "b"},
        )
        request = _authed_request(
            rf, "get", "/api/v1/compliance/export-configs", superuser
        )

        from apps.compliance.api import list_export_configs

        status, data = list_export_configs(request)
        assert status == 200
        assert len(data) >= 1

    def test_non_admin_rejected(self, rf, regular_user):
        request = _authed_request(
            rf, "get", "/api/v1/compliance/export-configs", regular_user
        )

        from apps.compliance.api import list_export_configs

        status, data = list_export_configs(request)
        assert status == 403


@pytest.mark.django_db
class TestExportConfigCreateAPI:
    def test_create_valid_config(self, rf, superuser):
        body = {
            "export_type": "audit_log",
            "format": "csv",
            "schedule": "daily",
            "destination_type": "s3",
            "destination_config": {"bucket": "test-bucket", "prefix": "audit"},
        }
        request = _authed_request(
            rf, "post", "/api/v1/compliance/export-configs", superuser, body=body
        )

        from apps.compliance.api import ExportConfigCreate, create_export_config

        status, data = create_export_config(request, body=ExportConfigCreate(**body))
        assert status == 201
        assert data["export_type"] == "audit_log"
        assert data["destination_config"]["bucket"] == "test-bucket"

    def test_create_invalid_export_type(self, rf, superuser):
        body = {
            "export_type": "invalid",
            "destination_type": "s3",
        }
        request = _authed_request(
            rf, "post", "/api/v1/compliance/export-configs", superuser, body=body
        )

        from apps.compliance.api import ExportConfigCreate, create_export_config

        status, data = create_export_config(request, body=ExportConfigCreate(**body))
        assert status == 400
        assert "export_type" in data["detail"]

    def test_create_non_admin_rejected(self, rf, regular_user):
        body = {"export_type": "audit_log", "destination_type": "s3"}
        request = _authed_request(
            rf, "post", "/api/v1/compliance/export-configs", regular_user, body=body
        )

        from apps.compliance.api import ExportConfigCreate, create_export_config

        status, data = create_export_config(request, body=ExportConfigCreate(**body))
        assert status == 403


@pytest.mark.django_db
class TestExportConfigGetAPI:
    def test_get_existing_config(self, rf, superuser):
        config = ComplianceExportConfig.objects.create(
            export_type="consent",
            format="json",
            schedule="weekly",
            destination_type="email",
            destination_config={"emails": ["a@b.com"]},
        )
        request = _authed_request(
            rf, "get", f"/api/v1/compliance/export-configs/{config.pk}", superuser
        )

        from apps.compliance.api import get_export_config

        status, data = get_export_config(request, config_id=config.pk)
        assert status == 200
        assert data["export_type"] == "consent"

    def test_get_not_found(self, rf, superuser):
        import uuid

        request = _authed_request(
            rf, "get", "/api/v1/compliance/export-configs/xxx", superuser
        )

        from apps.compliance.api import get_export_config

        status, data = get_export_config(request, config_id=uuid.uuid4())
        assert status == 404


@pytest.mark.django_db
class TestExportConfigUpdateAPI:
    def test_update_schedule(self, rf, superuser):
        config = ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="csv",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "b"},
        )
        body = {"schedule": "weekly"}
        request = _authed_request(
            rf,
            "patch",
            f"/api/v1/compliance/export-configs/{config.pk}",
            superuser,
            body=body,
        )

        from apps.compliance.api import ExportConfigUpdate, update_export_config

        status, data = update_export_config(
            request, config_id=config.pk, body=ExportConfigUpdate(**body)
        )
        assert status == 200
        assert data["schedule"] == "weekly"

    def test_update_invalid_format(self, rf, superuser):
        config = ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="csv",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "b"},
        )
        body = {"format": "xml"}
        request = _authed_request(
            rf,
            "patch",
            f"/api/v1/compliance/export-configs/{config.pk}",
            superuser,
            body=body,
        )

        from apps.compliance.api import ExportConfigUpdate, update_export_config

        status, data = update_export_config(
            request, config_id=config.pk, body=ExportConfigUpdate(**body)
        )
        assert status == 400

    def test_update_not_found(self, rf, superuser):
        import uuid

        body = {"schedule": "monthly"}
        request = _authed_request(
            rf, "patch", "/api/v1/compliance/export-configs/xxx", superuser, body=body
        )

        from apps.compliance.api import ExportConfigUpdate, update_export_config

        status, data = update_export_config(
            request, config_id=uuid.uuid4(), body=ExportConfigUpdate(**body)
        )
        assert status == 404


@pytest.mark.django_db
class TestExportConfigDeleteAPI:
    def test_delete_config(self, rf, superuser):
        config = ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="csv",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "b"},
        )
        request = _authed_request(
            rf, "delete", f"/api/v1/compliance/export-configs/{config.pk}", superuser
        )

        from apps.compliance.api import delete_export_config

        status, data = delete_export_config(request, config_id=config.pk)
        assert status == 200
        assert not ComplianceExportConfig.objects.filter(pk=config.pk).exists()

    def test_delete_not_found(self, rf, superuser):
        import uuid

        request = _authed_request(
            rf, "delete", "/api/v1/compliance/export-configs/xxx", superuser
        )

        from apps.compliance.api import delete_export_config

        status, data = delete_export_config(request, config_id=uuid.uuid4())
        assert status == 404

    def test_delete_non_admin_rejected(self, rf, regular_user):
        config = ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="csv",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "b"},
        )
        request = _authed_request(
            rf, "delete", f"/api/v1/compliance/export-configs/{config.pk}", regular_user
        )

        from apps.compliance.api import delete_export_config

        status, data = delete_export_config(request, config_id=config.pk)
        assert status == 403


@pytest.mark.django_db
class TestRunNowAPI:
    @patch("apps.compliance.tasks.boto3")
    def test_run_now_triggers_export(self, mock_boto3, rf, superuser):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        config = ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="csv",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "b"},
        )
        AuditLog.log(action="login", resource_type="user", resource_id="1")

        request = _authed_request(
            rf,
            "post",
            f"/api/v1/compliance/export-configs/{config.pk}/run-now",
            superuser,
        )

        from apps.compliance.api import run_export_now

        status, data = run_export_now(request, config_id=config.pk)
        assert status == 200
        assert data["status"] == "success"
        assert data["record_count"] >= 1

    def test_run_now_not_found(self, rf, superuser):
        import uuid

        request = _authed_request(
            rf, "post", "/api/v1/compliance/export-configs/xxx/run-now", superuser
        )

        from apps.compliance.api import run_export_now

        status, data = run_export_now(request, config_id=uuid.uuid4())
        assert status == 404

    def test_run_now_non_admin_rejected(self, rf, regular_user):
        config = ComplianceExportConfig.objects.create(
            export_type="audit_log",
            format="csv",
            schedule="daily",
            destination_type="s3",
            destination_config={"bucket": "b"},
        )
        request = _authed_request(
            rf,
            "post",
            f"/api/v1/compliance/export-configs/{config.pk}/run-now",
            regular_user,
        )

        from apps.compliance.api import run_export_now

        status, data = run_export_now(request, config_id=config.pk)
        assert status == 403
