"""Tests for consent management services — grant, revoke, current, history."""

import pytest

from apps.compliance.models import AuditAction, AuditLog, ConsentRecord, ConsentType
from apps.compliance.services import (
    get_consent_history,
    get_current_consents,
    grant_consent,
    revoke_consent,
)
from apps.users.models import UserSettings
from apps.users.tests.factories import UserFactory


@pytest.mark.django_db
class TestGrantConsent:
    def test_creates_record(self):
        user = UserFactory()
        record = grant_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        assert record.pk is not None
        assert record.consent_type == ConsentType.ANALYTICS
        assert record.version == "1.0"
        assert record.action == "granted"
        assert record.user == user
        assert record.user_email == user.email

    def test_creates_audit_log_entry(self):
        user = UserFactory()
        AuditLog.objects.all().delete()
        record = grant_consent(
            user,
            consent_type=ConsentType.TRAINING,
            version="2.0",
            ip_address="10.0.0.1",
            request_id="req-123",
        )
        entry = AuditLog.objects.filter(action=AuditAction.CONSENT_GRANTED).first()
        assert entry is not None
        assert entry.resource_type == "consent"
        assert entry.resource_id == str(record.pk)
        assert entry.actor_id.int == user.pk
        assert entry.actor_email == user.email
        assert entry.actor_ip == "10.0.0.1"
        assert entry.request_id == "req-123"
        assert entry.metadata["consent_type"] == ConsentType.TRAINING
        assert entry.metadata["version"] == "2.0"

    def test_syncs_analytics_setting(self):
        user = UserFactory()
        UserSettings.objects.filter(user=user).update(data_share_analytics=False)
        grant_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        settings_obj = UserSettings.objects.get(user=user)
        assert settings_obj.data_share_analytics is True

    def test_syncs_training_setting(self):
        user = UserFactory()
        UserSettings.objects.filter(user=user).update(data_share_training=False)
        grant_consent(user, consent_type=ConsentType.TRAINING, version="1.0")
        settings_obj = UserSettings.objects.get(user=user)
        assert settings_obj.data_share_training is True

    def test_syncs_marketing_setting(self):
        user = UserFactory()
        UserSettings.objects.filter(user=user).update(notification_marketing=False)
        grant_consent(user, consent_type=ConsentType.MARKETING, version="1.0")
        settings_obj = UserSettings.objects.get(user=user)
        assert settings_obj.notification_marketing is True

    def test_creates_settings_if_missing(self):
        user = UserFactory()
        UserSettings.objects.filter(user=user).delete()
        assert not UserSettings.objects.filter(user=user).exists()
        grant_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        settings_obj = UserSettings.objects.get(user=user)
        assert settings_obj.data_share_analytics is True

    def test_no_settings_sync_for_terms_of_service(self):
        user = UserFactory()
        UserSettings.objects.filter(user=user).delete()
        grant_consent(user, consent_type=ConsentType.TERMS_OF_SERVICE, version="1.0")
        assert not UserSettings.objects.filter(user=user).exists()

    def test_no_settings_sync_for_privacy_policy(self):
        user = UserFactory()
        UserSettings.objects.filter(user=user).delete()
        grant_consent(user, consent_type=ConsentType.PRIVACY_POLICY, version="1.0")
        assert not UserSettings.objects.filter(user=user).exists()

    def test_ip_address_stored(self):
        user = UserFactory()
        record = grant_consent(
            user,
            consent_type=ConsentType.ANALYTICS,
            version="1.0",
            ip_address="192.168.1.1",
        )
        assert record.ip_address == "192.168.1.1"

    def test_multiple_grants_create_separate_records(self):
        user = UserFactory()
        r1 = grant_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        r2 = grant_consent(user, consent_type=ConsentType.ANALYTICS, version="2.0")
        assert r1.pk != r2.pk
        assert (
            ConsentRecord.objects.filter(
                user=user, consent_type=ConsentType.ANALYTICS
            ).count()
            == 2
        )


@pytest.mark.django_db
class TestRevokeConsent:
    def test_creates_revoke_record(self):
        user = UserFactory()
        record = revoke_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        assert record.action == "revoked"
        assert record.consent_type == ConsentType.ANALYTICS

    def test_creates_audit_log_entry(self):
        user = UserFactory()
        AuditLog.objects.all().delete()
        record = revoke_consent(
            user,
            consent_type=ConsentType.MARKETING,
            version="1.0",
            ip_address="10.0.0.2",
            request_id="req-456",
        )
        entry = AuditLog.objects.filter(action=AuditAction.CONSENT_REVOKED).first()
        assert entry is not None
        assert entry.resource_type == "consent"
        assert entry.resource_id == str(record.pk)
        assert entry.metadata["consent_type"] == ConsentType.MARKETING

    def test_syncs_analytics_setting_to_false(self):
        user = UserFactory()
        UserSettings.objects.filter(user=user).update(data_share_analytics=True)
        revoke_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        settings_obj = UserSettings.objects.get(user=user)
        assert settings_obj.data_share_analytics is False

    def test_syncs_training_setting_to_false(self):
        user = UserFactory()
        UserSettings.objects.filter(user=user).update(data_share_training=True)
        revoke_consent(user, consent_type=ConsentType.TRAINING, version="1.0")
        settings_obj = UserSettings.objects.get(user=user)
        assert settings_obj.data_share_training is False

    def test_syncs_marketing_setting_to_false(self):
        user = UserFactory()
        UserSettings.objects.filter(user=user).update(notification_marketing=True)
        revoke_consent(user, consent_type=ConsentType.MARKETING, version="1.0")
        settings_obj = UserSettings.objects.get(user=user)
        assert settings_obj.notification_marketing is False


@pytest.mark.django_db
class TestGetCurrentConsents:
    def test_empty_user_returns_all_types_with_nulls(self):
        user = UserFactory()
        result = get_current_consents(user)
        assert set(result.keys()) == {c.value for c in ConsentType}
        for ct_value, entry in result.items():
            assert entry["consent_type"] == ct_value
            assert entry["action"] is None
            assert entry["version"] is None

    def test_returns_latest_record_per_type(self):
        user = UserFactory()
        grant_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        revoke_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        grant_consent(user, consent_type=ConsentType.ANALYTICS, version="2.0")

        result = get_current_consents(user)
        assert result[ConsentType.ANALYTICS]["action"] == "granted"
        assert result[ConsentType.ANALYTICS]["version"] == "2.0"

    def test_different_types_tracked_independently(self):
        user = UserFactory()
        grant_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        revoke_consent(user, consent_type=ConsentType.TRAINING, version="1.0")

        result = get_current_consents(user)
        assert result[ConsentType.ANALYTICS]["action"] == "granted"
        assert result[ConsentType.TRAINING]["action"] == "revoked"
        assert result[ConsentType.MARKETING]["action"] is None


@pytest.mark.django_db
class TestGetConsentHistory:
    def test_empty_user(self):
        user = UserFactory()
        history = get_consent_history(user)
        assert history == []

    def test_returns_all_records_newest_first(self):
        user = UserFactory()
        grant_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        revoke_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")
        grant_consent(user, consent_type=ConsentType.TRAINING, version="2.0")

        history = get_consent_history(user)
        assert len(history) == 3
        # Newest first
        assert history[0]["consent_type"] == ConsentType.TRAINING
        assert history[0]["action"] == "granted"
        assert history[1]["consent_type"] == ConsentType.ANALYTICS
        assert history[1]["action"] == "revoked"
        assert history[2]["consent_type"] == ConsentType.ANALYTICS
        assert history[2]["action"] == "granted"

    def test_records_include_all_fields(self):
        user = UserFactory()
        grant_consent(
            user,
            consent_type=ConsentType.MARKETING,
            version="3.0",
            ip_address="1.2.3.4",
        )

        history = get_consent_history(user)
        assert len(history) == 1
        record = history[0]
        assert "id" in record
        assert record["consent_type"] == ConsentType.MARKETING
        assert record["action"] == "granted"
        assert record["version"] == "3.0"
        assert record["recorded_at"] is not None
        assert record["ip_address"] == "1.2.3.4"

    def test_does_not_include_other_users(self):
        user1 = UserFactory()
        user2 = UserFactory()
        grant_consent(user1, consent_type=ConsentType.ANALYTICS, version="1.0")
        grant_consent(user2, consent_type=ConsentType.ANALYTICS, version="1.0")

        history = get_consent_history(user1)
        assert len(history) == 1


@pytest.mark.django_db
class TestConsentExportIntegration:
    """Verify consent records appear in GDPR data export."""

    def test_export_includes_consent_records(self):
        from apps.compliance.services import export_user_data

        user = UserFactory()
        grant_consent(
            user,
            consent_type=ConsentType.ANALYTICS,
            version="1.0",
            ip_address="10.0.0.1",
        )
        revoke_consent(user, consent_type=ConsentType.ANALYTICS, version="1.0")

        data = export_user_data(user)
        assert "consent_records" in data
        assert len(data["consent_records"]) == 2
        # Newest first
        assert data["consent_records"][0]["action"] == "revoked"
        assert data["consent_records"][1]["action"] == "granted"
        assert data["consent_records"][1]["ip_address"] == "10.0.0.1"

    def test_export_empty_consent(self):
        from apps.compliance.services import export_user_data

        user = UserFactory()
        data = export_user_data(user)
        assert data["consent_records"] == []
