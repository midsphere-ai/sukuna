"""Tests for the ConsentRecord model — creation, immutability, and choices."""

import pytest

from apps.compliance.models import ConsentRecord, ConsentType
from apps.users.tests.factories import UserFactory


@pytest.mark.django_db
class TestConsentRecordCreation:
    """Verify basic creation via the ORM."""

    def test_create_grant_record(self):
        user = UserFactory()
        record = ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=ConsentType.ANALYTICS,
            version="1.0",
            action="granted",
            ip_address="10.0.0.1",
        )
        assert record.pk is not None
        assert record.consent_type == ConsentType.ANALYTICS
        assert record.version == "1.0"
        assert record.action == "granted"
        assert record.user == user
        assert record.user_email == user.email
        assert record.ip_address == "10.0.0.1"
        assert record.recorded_at is not None

    def test_create_revoke_record(self):
        user = UserFactory()
        record = ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=ConsentType.TRAINING,
            version="2.0",
            action="revoked",
        )
        assert record.action == "revoked"
        assert record.consent_type == ConsentType.TRAINING
        assert record.ip_address is None

    def test_user_set_null_on_delete(self):
        user = UserFactory()
        record = ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=ConsentType.MARKETING,
            version="1.0",
            action="granted",
        )
        email = user.email
        user.delete()
        record.refresh_from_db()
        assert record.user is None
        assert record.user_email == email

    def test_str_representation(self):
        user = UserFactory()
        record = ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=ConsentType.PRIVACY_POLICY,
            version="3.1",
            action="granted",
        )
        s = str(record)
        assert "privacy_policy" in s
        assert "granted" in s
        assert "3.1" in s
        assert user.email in s

    def test_ordering_newest_first(self):
        user = UserFactory()
        r1 = ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=ConsentType.ANALYTICS,
            version="1.0",
            action="granted",
        )
        r2 = ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=ConsentType.ANALYTICS,
            version="1.0",
            action="revoked",
        )
        records = list(ConsentRecord.objects.filter(user=user))
        assert records[0].pk == r2.pk
        assert records[1].pk == r1.pk


@pytest.mark.django_db
class TestConsentRecordImmutability:
    """ConsentRecord must refuse updates and deletes."""

    def test_update_via_save_raises(self):
        user = UserFactory()
        record = ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=ConsentType.ANALYTICS,
            version="1.0",
            action="granted",
        )
        record.version = "2.0"
        with pytest.raises(ValueError, match="immutable"):
            record.save()

    def test_delete_raises(self):
        user = UserFactory()
        record = ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=ConsentType.ANALYTICS,
            version="1.0",
            action="granted",
        )
        with pytest.raises(ValueError, match="immutable"):
            record.delete()


@pytest.mark.django_db
class TestConsentTypeChoices:
    """Verify all expected consent types exist."""

    def test_all_types_defined(self):
        expected = {
            "analytics",
            "training",
            "marketing",
            "terms_of_service",
            "privacy_policy",
        }
        actual = {choice[0] for choice in ConsentType.choices}
        assert expected == actual

    def test_each_type_can_be_stored(self):
        user = UserFactory()
        for ct_value, _ in ConsentType.choices:
            record = ConsentRecord.objects.create(
                user=user,
                user_email=user.email,
                consent_type=ct_value,
                version="1.0",
                action="granted",
            )
            assert record.consent_type == ct_value
