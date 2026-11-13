"""Tests for Organization and OrganizationMembership models."""

import pytest
from django.db import IntegrityError

from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    ROLE_HIERARCHY,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)


@pytest.mark.django_db
class TestOrganizationModel:
    """Organization creation, slug generation, and member queries."""

    def test_create_organization(self):
        org = Organization.objects.create(name="Acme Corp")
        assert org.pk is not None
        assert org.name == "Acme Corp"
        assert org.slug == "acme-corp"
        assert org.description == ""
        assert org.created_at is not None
        assert org.updated_at is not None

    def test_str_representation(self):
        org = Organization.objects.create(name="Test Org")
        assert str(org) == "Test Org"

    def test_slug_auto_generated(self):
        org = Organization.objects.create(name="My Amazing Organization!")
        assert org.slug == "my-amazing-organization"

    def test_slug_uniqueness(self):
        Organization.objects.create(name="Duplicate")
        org2 = Organization.objects.create(name="Duplicate")
        assert org2.slug == "duplicate-1"

    def test_slug_uniqueness_multiple(self):
        Organization.objects.create(name="Test")
        Organization.objects.create(name="Test")
        org3 = Organization.objects.create(name="Test")
        assert org3.slug == "test-2"

    def test_explicit_slug_preserved(self):
        org = Organization.objects.create(name="Foo", slug="custom-slug")
        assert org.slug == "custom-slug"

    def test_empty_name_slug_fallback(self):
        org = Organization.objects.create(name="")
        assert org.slug == "org"

    def test_has_member(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        assert org.has_member(user) is False
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        assert org.has_member(user) is True

    def test_get_membership(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        assert org.get_membership(user) is None
        membership = OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.ADMIN
        )
        assert org.get_membership(user) == membership

    def test_get_owner(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.OWNER
        )
        owner = org.get_owner()
        assert owner is not None
        assert owner.user == user

    def test_get_owner_none(self):
        org = Organization.objects.create(name="Org")
        assert org.get_owner() is None

    def test_member_count(self):
        org = Organization.objects.create(name="Org")
        assert org.member_count() == 0
        for _ in range(3):
            OrganizationMembership.objects.create(
                organization=org, user=UserFactory(), role=OrganizationRole.MEMBER
            )
        assert org.member_count() == 3

    def test_ordering(self):
        org_b = Organization.objects.create(name="Bravo")
        org_a = Organization.objects.create(name="Alpha")
        orgs = list(Organization.objects.all())
        assert orgs[0] == org_a
        assert orgs[1] == org_b

    def test_cascade_delete_memberships(self):
        org = Organization.objects.create(name="Org")
        OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.MEMBER
        )
        org.delete()
        assert OrganizationMembership.objects.count() == 0

    def test_members_m2m_field(self):
        org = Organization.objects.create(name="Org")
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        assert user in org.members.all()
        assert org in user.organizations.all()


@pytest.mark.django_db
class TestOrganizationMembershipModel:
    """Membership creation, uniqueness, role changes, and constraints."""

    def test_create_membership(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        membership = OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        assert membership.pk is not None
        assert membership.role == OrganizationRole.MEMBER
        assert membership.joined_at is not None

    def test_default_role_is_member(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        membership = OrganizationMembership.objects.create(organization=org, user=user)
        assert membership.role == OrganizationRole.MEMBER

    def test_str_representation(self):
        user = UserFactory()
        org = Organization.objects.create(name="Acme")
        membership = OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.ADMIN
        )
        s = str(membership)
        assert "Acme" in s
        assert "admin" in s

    def test_unique_together_user_org(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        with pytest.raises(IntegrityError):
            OrganizationMembership.objects.create(
                organization=org, user=user, role=OrganizationRole.ADMIN
            )

    def test_user_can_join_multiple_orgs(self):
        user = UserFactory()
        org1 = Organization.objects.create(name="Org 1")
        org2 = Organization.objects.create(name="Org 2")
        OrganizationMembership.objects.create(
            organization=org1, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org2, user=user, role=OrganizationRole.ADMIN
        )
        assert user.org_memberships.count() == 2

    def test_invited_by_tracked(self):
        owner = UserFactory()
        invitee = UserFactory()
        org = Organization.objects.create(name="Org")
        membership = OrganizationMembership.objects.create(
            organization=org,
            user=invitee,
            role=OrganizationRole.MEMBER,
            invited_by=owner,
        )
        assert membership.invited_by == owner

    def test_invited_by_set_null_on_delete(self):
        inviter = UserFactory()
        invitee = UserFactory()
        org = Organization.objects.create(name="Org")
        OrganizationMembership.objects.create(
            organization=org,
            user=invitee,
            role=OrganizationRole.MEMBER,
            invited_by=inviter,
        )
        inviter.delete()
        membership = OrganizationMembership.objects.get(user=invitee)
        assert membership.invited_by is None

    def test_role_level_property(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        for role, expected_level in ROLE_HIERARCHY.items():
            membership = OrganizationMembership(organization=org, user=user, role=role)
            assert membership.role_level == expected_level

    def test_has_role_or_higher(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        admin = OrganizationMembership(
            organization=org, user=user, role=OrganizationRole.ADMIN
        )
        assert admin.has_role_or_higher(OrganizationRole.VIEWER) is True
        assert admin.has_role_or_higher(OrganizationRole.MEMBER) is True
        assert admin.has_role_or_higher(OrganizationRole.ADMIN) is True
        assert admin.has_role_or_higher(OrganizationRole.OWNER) is False

    def test_cascade_on_user_delete(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        user.delete()
        assert OrganizationMembership.objects.count() == 0


@pytest.mark.django_db
class TestRoleChangeConstraints:
    """Ownership transfer and demotion constraints."""

    def test_change_role(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        membership = OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        membership.change_role(OrganizationRole.ADMIN)
        membership.refresh_from_db()
        assert membership.role == OrganizationRole.ADMIN

    def test_cannot_demote_last_owner(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        membership = OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.OWNER
        )
        with pytest.raises(ValueError, match="last owner"):
            membership.change_role(OrganizationRole.ADMIN)

    def test_can_demote_owner_when_multiple_owners(self):
        org = Organization.objects.create(name="Org")
        owner1 = OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.OWNER
        )
        OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.OWNER
        )
        owner1.change_role(OrganizationRole.ADMIN)
        owner1.refresh_from_db()
        assert owner1.role == OrganizationRole.ADMIN

    def test_cannot_delete_last_owner(self):
        user = UserFactory()
        org = Organization.objects.create(name="Org")
        membership = OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.OWNER
        )
        with pytest.raises(ValueError, match="last owner"):
            membership.delete()

    def test_can_delete_owner_when_multiple_owners(self):
        org = Organization.objects.create(name="Org")
        owner1 = OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.OWNER
        )
        OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.OWNER
        )
        owner1.delete()
        assert (
            OrganizationMembership.objects.filter(
                organization=org, role=OrganizationRole.OWNER
            ).count()
            == 1
        )

    def test_can_delete_non_owner_membership(self):
        org = Organization.objects.create(name="Org")
        membership = OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.MEMBER
        )
        membership.delete()
        assert OrganizationMembership.objects.count() == 0

    def test_promote_member_to_owner(self):
        org = Organization.objects.create(name="Org")
        OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.OWNER
        )
        member = OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.MEMBER
        )
        member.change_role(OrganizationRole.OWNER)
        member.refresh_from_db()
        assert member.role == OrganizationRole.OWNER


@pytest.mark.django_db
class TestRoleHierarchy:
    """Verify the role hierarchy ordering."""

    def test_hierarchy_order(self):
        assert (
            ROLE_HIERARCHY[OrganizationRole.VIEWER]
            < ROLE_HIERARCHY[OrganizationRole.MEMBER]
        )
        assert (
            ROLE_HIERARCHY[OrganizationRole.MEMBER]
            < ROLE_HIERARCHY[OrganizationRole.ADMIN]
        )
        assert (
            ROLE_HIERARCHY[OrganizationRole.ADMIN]
            < ROLE_HIERARCHY[OrganizationRole.OWNER]
        )

    def test_all_roles_in_hierarchy(self):
        for role in OrganizationRole:
            assert role in ROLE_HIERARCHY
