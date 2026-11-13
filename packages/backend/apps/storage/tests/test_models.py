"""Unit tests for storage app models and managers."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.storage.models import (
    AgentRun,
    AgentServerEvent,
    Conversation,
    ConversationComposioAddon,
    ConversationFile,
    MarketplaceAddon,
    StoredFile,
    SystemWideMemory,
    UserMarketplaceAddons,
    upload_to,
)
from apps.users.tests.factories import UserFactory

# ---------------------------------------------------------------------------
# upload_to helper
# ---------------------------------------------------------------------------


class TestUploadTo:
    def test_generates_unique_path(self):
        instance = type("Obj", (), {"owner": type("U", (), {"id": 42})()})()
        path = upload_to(instance, "photo.png")
        assert path.startswith("uploads/42/")
        assert path.endswith(".png")
        # UUID in filename
        basename = path.split("/")[-1]
        name_part = basename.replace(".png", "")
        uuid.UUID(name_part)  # Should not raise

    def test_handles_no_extension(self):
        instance = type("Obj", (), {"owner": type("U", (), {"id": 1})()})()
        path = upload_to(instance, "Makefile")
        assert "Makefile" in path


# ---------------------------------------------------------------------------
# MarketplaceAddon & MarketplaceAddonManager
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMarketplaceAddon:
    def test_create(self):
        addon = MarketplaceAddon.objects.create(
            name="Slack",
            description="Slack integration",
            link="https://slack.com",
            logo="https://slack.com/logo.png",
            enum="SLACK",
        )
        assert addon.pk is not None
        assert addon.categories == []
        assert addon.tags == []

    def test_create_with_categories_and_tags(self):
        addon = MarketplaceAddon.objects.create(
            name="GitHub",
            description="GitHub integration",
            link="https://github.com",
            logo="https://github.com/logo.png",
            enum="GITHUB",
            categories=["dev-tools", "vcs"],
            tags=["git", "code"],
        )
        assert addon.categories == ["dev-tools", "vcs"]
        assert addon.tags == ["git", "code"]


@pytest.mark.django_db
class TestMarketplaceAddonManager:
    def test_get_all(self):
        MarketplaceAddon.objects.create(
            name="A", description="", link="", logo="", enum="A"
        )
        MarketplaceAddon.objects.create(
            name="B", description="", link="", logo="", enum="B"
        )
        assert MarketplaceAddon.objects.get_all().count() == 2

    def test_get_by_id(self):
        addon = MarketplaceAddon.objects.create(
            name="X", description="", link="", logo="", enum="X"
        )
        found = MarketplaceAddon.objects.get_by_id(addon.id)
        assert found == addon

    def test_get_by_id_not_found(self):
        result = MarketplaceAddon.objects.get_by_id(uuid.uuid4())
        assert result is None

    def test_get_by_id_with_user_prefetch_no_user(self):
        addon = MarketplaceAddon.objects.create(
            name="Y", description="", link="", logo="", enum="Y"
        )
        found = MarketplaceAddon.objects.get_by_id_with_user_prefetch(addon.id)
        assert found == addon

    def test_get_by_id_with_user_prefetch_with_user(self):
        user = UserFactory()
        addon = MarketplaceAddon.objects.create(
            name="Z", description="", link="", logo="", enum="Z"
        )
        UserMarketplaceAddons.objects.create(enabled_addon=addon, owner=user)
        found = MarketplaceAddon.objects.get_by_id_with_user_prefetch(
            addon.id, user_id=user.id
        )
        assert found == addon
        assert len(found.user_specific_addons) == 1


# ---------------------------------------------------------------------------
# UserMarketplaceAddons & Manager
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUserMarketplaceAddons:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.addon = MarketplaceAddon.objects.create(
            name="Slack", description="", link="", logo="", enum="SLACK"
        )

    def test_create(self):
        ua = UserMarketplaceAddons.objects.create(
            enabled_addon=self.addon, owner=self.user
        )
        assert ua.pk is not None
        assert ua.auth_complete is False
        assert ua.auth_link is None
        assert ua.config_id is None

    def test_check_auth_status_complete(self):
        ua = UserMarketplaceAddons.objects.create(
            enabled_addon=self.addon, owner=self.user, auth_complete=True
        )
        # Should not raise
        ua.check_auth_status()

    def test_check_auth_status_incomplete_no_link(self):
        ua = UserMarketplaceAddons.objects.create(
            enabled_addon=self.addon, owner=self.user
        )
        with pytest.raises(ValueError, match="not complete"):
            ua.check_auth_status()

    def test_check_auth_status_expired_link(self):
        ua = UserMarketplaceAddons.objects.create(
            enabled_addon=self.addon,
            owner=self.user,
            auth_link="https://auth.example.com/link",
            auth_link_created_at=timezone.now() - timedelta(hours=7),
        )
        with pytest.raises(ValueError, match="expired"):
            ua.check_auth_status()
        ua.refresh_from_db()
        assert ua.auth_link is None
        assert ua.auth_link_created_at is None

    def test_check_auth_status_valid_link_still_incomplete(self):
        ua = UserMarketplaceAddons.objects.create(
            enabled_addon=self.addon,
            owner=self.user,
            auth_link="https://auth.example.com/link",
            auth_link_created_at=timezone.now() - timedelta(hours=1),
        )
        with pytest.raises(ValueError, match="not complete"):
            ua.check_auth_status()

    def test_check_auth_status_expired_falls_back_to_date_created(self):
        ua = UserMarketplaceAddons.objects.create(
            enabled_addon=self.addon,
            owner=self.user,
            auth_link="https://auth.example.com/link",
            auth_link_created_at=None,
        )
        # date_created is auto_now_add, so it's very recent — should NOT expire
        with pytest.raises(ValueError, match="not complete"):
            ua.check_auth_status()


@pytest.mark.django_db
class TestUserMarketplaceAddonsManager:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.addon = MarketplaceAddon.objects.create(
            name="Slack", description="", link="", logo="", enum="SLACK"
        )

    def test_for_user(self):
        UserMarketplaceAddons.objects.create(enabled_addon=self.addon, owner=self.user)
        other = UserFactory()
        addon2 = MarketplaceAddon.objects.create(
            name="GH", description="", link="", logo="", enum="GH"
        )
        UserMarketplaceAddons.objects.create(enabled_addon=addon2, owner=other)

        result = UserMarketplaceAddons.objects.for_user(self.user)
        assert result.count() == 1

    def test_get_by_id(self):
        ua = UserMarketplaceAddons.objects.create(
            enabled_addon=self.addon, owner=self.user
        )
        found = UserMarketplaceAddons.objects.get_by_id(ua.id)
        assert found == ua

    def test_get_by_id_not_found(self):
        result = UserMarketplaceAddons.objects.get_by_id(uuid.uuid4())
        assert result is None

    def test_count_for_user(self):
        UserMarketplaceAddons.objects.create(enabled_addon=self.addon, owner=self.user)
        assert UserMarketplaceAddons.objects.count_for_user(self.user) == 1

    def test_pending_authorizations(self):
        UserMarketplaceAddons.objects.create(
            enabled_addon=self.addon,
            owner=self.user,
            auth_complete=False,
            config_id="cfg-123",
        )
        # Complete auth — should not appear
        addon2 = MarketplaceAddon.objects.create(
            name="GH", description="", link="", logo="", enum="GH"
        )
        UserMarketplaceAddons.objects.create(
            enabled_addon=addon2,
            owner=self.user,
            auth_complete=True,
            config_id="cfg-456",
        )
        # No config_id — should not appear
        addon3 = MarketplaceAddon.objects.create(
            name="LI", description="", link="", logo="", enum="LI"
        )
        UserMarketplaceAddons.objects.create(
            enabled_addon=addon3,
            owner=self.user,
            auth_complete=False,
            config_id=None,
        )

        pending = UserMarketplaceAddons.objects.pending_authorizations(self.user.id)
        assert pending.count() == 1

    def test_create_registration(self):
        ua = UserMarketplaceAddons.objects.create_registration(self.addon, self.user)
        assert ua.pk is not None
        assert ua.enabled_addon == self.addon
        assert ua.owner == self.user


# ---------------------------------------------------------------------------
# StoredFile & StoredFileManager
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStoredFile:
    def test_create(self):
        user = UserFactory()
        sf = StoredFile.objects.create(
            owner=user, name="doc.pdf", size=1024, mime_type="application/pdf"
        )
        assert sf.pk is not None
        assert isinstance(sf.pk, uuid.UUID)
        assert sf.uploaded_at is not None
        assert str(sf) == "doc.pdf (1024 bytes)"

    def test_ordering_newest_first(self):
        user = UserFactory()
        sf1 = StoredFile.objects.create(
            owner=user, name="old.txt", size=10, mime_type="text/plain"
        )
        sf2 = StoredFile.objects.create(
            owner=user, name="new.txt", size=20, mime_type="text/plain"
        )
        files = list(StoredFile.objects.filter(owner=user))
        assert files[0].pk == sf2.pk


@pytest.mark.django_db
class TestStoredFileManager:
    def test_for_user(self):
        user = UserFactory()
        other = UserFactory()
        StoredFile.objects.create(
            owner=user, name="a.txt", size=10, mime_type="text/plain"
        )
        StoredFile.objects.create(
            owner=other, name="b.txt", size=10, mime_type="text/plain"
        )
        result = StoredFile.objects.for_user(user)
        assert result.count() == 1

    def test_create_file(self):
        user = UserFactory()
        sf = StoredFile.objects.create_file(
            owner=user, file=None, name="test.txt", size=100, mime_type="text/plain"
        )
        assert sf.pk is not None
        assert sf.name == "test.txt"


# ---------------------------------------------------------------------------
# Conversation & ConversationManager
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConversation:
    def test_create_defaults(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        assert conv.pk is not None
        assert conv.title == "New chat"
        assert conv.summary is None
        assert conv.requires_user_input is False
        assert conv.metadata == {}
        assert str(conv) == f"{user}:New chat"

    def test_on_going_no_task(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        assert conv.on_going is False

    def test_on_going_with_running_task(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        run = AgentRun.objects.create(
            conversation=conv,
            user=user,
            task="do stuff",
            status=AgentRun.Status.RUNNING,
        )
        conv.current_task = run
        conv.save()
        conv.refresh_from_db()
        assert conv.on_going is True

    def test_on_going_with_completed_task(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        run = AgentRun.objects.create(
            conversation=conv,
            user=user,
            task="do stuff",
            status=AgentRun.Status.COMPLETED,
        )
        conv.current_task = run
        conv.save()
        conv.refresh_from_db()
        assert conv.on_going is False

    def test_has_error_no_task(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        assert conv.has_error is False

    def test_has_error_with_failed_task(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        run = AgentRun.objects.create(
            conversation=conv,
            user=user,
            task="fail",
            status=AgentRun.Status.FAILED,
            error="boom",
        )
        conv.current_task = run
        conv.save()
        conv.refresh_from_db()
        assert conv.has_error is True

    def test_error_message(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        run = AgentRun.objects.create(
            conversation=conv,
            user=user,
            task="fail",
            status=AgentRun.Status.FAILED,
            error="Something broke",
        )
        conv.current_task = run
        conv.save()
        conv.refresh_from_db()
        assert conv.error == "Something broke"

    def test_error_message_no_task(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        assert conv.error == ""

    def test_cancellation_requested(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        run = AgentRun.objects.create(
            conversation=conv,
            user=user,
            task="cancel me",
            status=AgentRun.Status.CANCELLED,
        )
        conv.current_task = run
        conv.save()
        conv.refresh_from_db()
        assert conv.cancellation_requested is True

    def test_cancellation_not_requested(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        assert conv.cancellation_requested is False

    def test_ongoing_statuses(self):
        """Test all statuses that should make on_going True."""
        user = UserFactory()
        for status in ["pending", "queued", "provisioning", "running"]:
            conv = Conversation.objects.create(user=user)
            run = AgentRun.objects.create(
                conversation=conv, user=user, task="t", status=status
            )
            conv.current_task = run
            conv.save()
            conv.refresh_from_db()
            assert conv.on_going is True, f"Expected on_going=True for status={status}"


@pytest.mark.django_db
class TestConversationManager:
    def test_for_user(self):
        user = UserFactory()
        other = UserFactory()
        Conversation.objects.create(user=user, title="A")
        Conversation.objects.create(user=user, title="B")
        Conversation.objects.create(user=other, title="C")

        result = Conversation.objects.for_user(user)
        assert result.count() == 2

    def test_by_user_id(self):
        user = UserFactory()
        Conversation.objects.create(user=user)

        result = Conversation.objects.by_user_id(user.id)
        assert result.count() == 1

    def test_get_by_id(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)

        found = Conversation.objects.get_by_id(conv.id)
        assert found == conv

    def test_get_by_id_not_found(self):
        result = Conversation.objects.get_by_id(uuid.uuid4())
        assert result is None

    def test_create_conversation(self):
        user = UserFactory()
        conv = Conversation.objects.create_conversation(user)
        assert conv.pk is not None
        assert conv.user == user

    def test_delete_for_user(self):
        user = UserFactory()
        other = UserFactory()
        Conversation.objects.create(user=user)
        Conversation.objects.create(user=user)
        Conversation.objects.create(user=other)

        count = Conversation.objects.delete_for_user(user)
        assert count == 2
        assert Conversation.objects.filter(user=user).count() == 0
        assert Conversation.objects.filter(user=other).count() == 1


# ---------------------------------------------------------------------------
# AgentRun — State Machine
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAgentRunStateMachine:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.conv = Conversation.objects.create(user=self.user)

    def _make_run(self, status=AgentRun.Status.PENDING, **kwargs):
        return AgentRun.objects.create(
            conversation=self.conv,
            user=self.user,
            task="test task",
            status=status,
            **kwargs,
        )

    # -- Valid transitions --

    def test_pending_to_queued(self):
        run = self._make_run(AgentRun.Status.PENDING)
        run.transition_to(AgentRun.Status.QUEUED)
        run.refresh_from_db()
        assert run.status == AgentRun.Status.QUEUED

    def test_pending_to_running(self):
        run = self._make_run(AgentRun.Status.PENDING)
        run.transition_to(AgentRun.Status.RUNNING)
        run.refresh_from_db()
        assert run.status == AgentRun.Status.RUNNING
        assert run.started_at is not None

    def test_queued_to_provisioning(self):
        run = self._make_run(AgentRun.Status.QUEUED)
        run.transition_to(AgentRun.Status.PROVISIONING)
        run.refresh_from_db()
        assert run.status == AgentRun.Status.PROVISIONING

    def test_provisioning_to_running(self):
        run = self._make_run(AgentRun.Status.PROVISIONING)
        run.transition_to(AgentRun.Status.RUNNING)
        run.refresh_from_db()
        assert run.status == AgentRun.Status.RUNNING
        assert run.started_at is not None

    def test_running_to_completed(self):
        run = self._make_run(AgentRun.Status.RUNNING)
        run.transition_to(AgentRun.Status.COMPLETED)
        run.refresh_from_db()
        assert run.status == AgentRun.Status.COMPLETED
        assert run.finished_at is not None

    def test_running_to_failed(self):
        run = self._make_run(AgentRun.Status.RUNNING)
        run.transition_to(AgentRun.Status.FAILED, error="out of memory")
        run.refresh_from_db()
        assert run.status == AgentRun.Status.FAILED
        assert run.error == "out of memory"
        assert run.finished_at is not None

    def test_running_to_cancelled(self):
        run = self._make_run(AgentRun.Status.RUNNING)
        run.transition_to(AgentRun.Status.CANCELLED)
        run.refresh_from_db()
        assert run.status == AgentRun.Status.CANCELLED
        assert run.finished_at is not None

    def test_queued_to_failed(self):
        run = self._make_run(AgentRun.Status.QUEUED)
        run.transition_to(AgentRun.Status.FAILED, error="provision failed")
        run.refresh_from_db()
        assert run.status == AgentRun.Status.FAILED

    def test_queued_to_cancelled(self):
        run = self._make_run(AgentRun.Status.QUEUED)
        run.transition_to(AgentRun.Status.CANCELLED)
        run.refresh_from_db()
        assert run.status == AgentRun.Status.CANCELLED

    def test_provisioning_to_failed(self):
        run = self._make_run(AgentRun.Status.PROVISIONING)
        run.transition_to(AgentRun.Status.FAILED)
        run.refresh_from_db()
        assert run.status == AgentRun.Status.FAILED

    def test_provisioning_to_cancelled(self):
        run = self._make_run(AgentRun.Status.PROVISIONING)
        run.transition_to(AgentRun.Status.CANCELLED)
        run.refresh_from_db()
        assert run.status == AgentRun.Status.CANCELLED

    # -- Invalid transitions --

    def test_completed_to_running_raises(self):
        run = self._make_run(AgentRun.Status.COMPLETED)
        with pytest.raises(ValueError, match="terminal status"):
            run.transition_to(AgentRun.Status.RUNNING)

    def test_failed_to_running_raises(self):
        run = self._make_run(AgentRun.Status.FAILED)
        with pytest.raises(ValueError, match="terminal status"):
            run.transition_to(AgentRun.Status.RUNNING)

    def test_cancelled_to_running_raises(self):
        run = self._make_run(AgentRun.Status.CANCELLED)
        with pytest.raises(ValueError, match="terminal status"):
            run.transition_to(AgentRun.Status.RUNNING)

    def test_queued_to_completed_raises(self):
        run = self._make_run(AgentRun.Status.QUEUED)
        with pytest.raises(ValueError, match="Invalid transition"):
            run.transition_to(AgentRun.Status.COMPLETED)

    def test_queued_to_running_raises(self):
        run = self._make_run(AgentRun.Status.QUEUED)
        with pytest.raises(ValueError, match="Invalid transition"):
            run.transition_to(AgentRun.Status.RUNNING)

    def test_provisioning_to_completed_raises(self):
        run = self._make_run(AgentRun.Status.PROVISIONING)
        with pytest.raises(ValueError, match="Invalid transition"):
            run.transition_to(AgentRun.Status.COMPLETED)

    # -- Convenience methods --

    def test_mark_running(self):
        run = self._make_run(AgentRun.Status.PROVISIONING)
        run.mark_running()
        run.refresh_from_db()
        assert run.status == AgentRun.Status.RUNNING

    def test_mark_completed(self):
        run = self._make_run(AgentRun.Status.RUNNING)
        run.mark_completed()
        run.refresh_from_db()
        assert run.status == AgentRun.Status.COMPLETED

    def test_mark_failed_with_error(self):
        run = self._make_run(AgentRun.Status.RUNNING)
        run.mark_failed(error="oops")
        run.refresh_from_db()
        assert run.status == AgentRun.Status.FAILED
        assert run.error == "oops"

    def test_mark_failed_no_error(self):
        run = self._make_run(AgentRun.Status.RUNNING)
        run.mark_failed()
        run.refresh_from_db()
        assert run.status == AgentRun.Status.FAILED
        assert run.error == ""

    def test_mark_cancelled(self):
        run = self._make_run(AgentRun.Status.RUNNING)
        run.mark_cancelled()
        run.refresh_from_db()
        assert run.status == AgentRun.Status.CANCELLED

    # -- Timestamp auto-set --

    def test_started_at_set_on_running(self):
        run = self._make_run(AgentRun.Status.PENDING)
        assert run.started_at is None
        run.transition_to(AgentRun.Status.RUNNING)
        run.refresh_from_db()
        assert run.started_at is not None

    def test_started_at_not_overwritten(self):
        original = timezone.now() - timedelta(hours=1)
        run = self._make_run(AgentRun.Status.PENDING, started_at=original)
        run.transition_to(AgentRun.Status.RUNNING)
        run.refresh_from_db()
        assert run.started_at == original

    def test_finished_at_set_on_terminal(self):
        run = self._make_run(AgentRun.Status.RUNNING)
        assert run.finished_at is None
        run.transition_to(AgentRun.Status.COMPLETED)
        run.refresh_from_db()
        assert run.finished_at is not None

    # -- str --

    def test_str(self):
        run = self._make_run()
        s = str(run)
        assert "AgentRun:" in s
        assert "pending" in s


# -- Pending (legacy compat) allows any target --


@pytest.mark.django_db
class TestAgentRunPendingLegacyCompat:
    def test_pending_to_all_valid(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        valid_targets = [
            "queued",
            "provisioning",
            "running",
            "completed",
            "failed",
            "cancelled",
        ]
        for target in valid_targets:
            run = AgentRun.objects.create(
                conversation=conv, user=user, task="t", status=AgentRun.Status.PENDING
            )
            run.transition_to(target)
            run.refresh_from_db()
            assert run.status == target


# ---------------------------------------------------------------------------
# ConversationFile
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConversationFile:
    def test_create(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sf = StoredFile.objects.create(
            owner=user, name="f.txt", size=10, mime_type="text/plain"
        )
        cf = ConversationFile.objects.create(conversation=conv, stored_file=sf)
        assert cf.pk is not None

    def test_cascade_on_conversation_delete(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sf = StoredFile.objects.create(
            owner=user, name="f.txt", size=10, mime_type="text/plain"
        )
        ConversationFile.objects.create(conversation=conv, stored_file=sf)
        conv.delete()
        assert ConversationFile.objects.count() == 0

    def test_cascade_on_file_delete(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sf = StoredFile.objects.create(
            owner=user, name="f.txt", size=10, mime_type="text/plain"
        )
        ConversationFile.objects.create(conversation=conv, stored_file=sf)
        sf.delete()
        assert ConversationFile.objects.count() == 0


# ---------------------------------------------------------------------------
# ConversationComposioAddon
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConversationComposioAddon:
    def test_create(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        addon = MarketplaceAddon.objects.create(
            name="S", description="", link="", logo="", enum="S"
        )
        ua = UserMarketplaceAddons.objects.create(enabled_addon=addon, owner=user)
        cca = ConversationComposioAddon.objects.create(conversation=conv, addon=ua)
        assert cca.pk is not None


# ---------------------------------------------------------------------------
# SystemWideMemory & Manager
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSystemWideMemory:
    def test_create(self):
        user = UserFactory()
        mem = SystemWideMemory.objects.create(
            user=user, memory_summary="User likes Python"
        )
        assert mem.pk is not None
        assert str(mem) == user.email
        assert mem.date_created is not None

    def test_for_user(self):
        user = UserFactory()
        SystemWideMemory.objects.create(user=user, memory_summary="test")
        found = SystemWideMemory.objects.for_user(user)
        assert found is not None
        assert found.memory_summary == "test"

    def test_for_user_not_found(self):
        user = UserFactory()
        result = SystemWideMemory.objects.for_user(user)
        assert result is None


# ---------------------------------------------------------------------------
# AgentServerEvent (unmanaged model — only test meta)
# ---------------------------------------------------------------------------


class TestAgentServerEvent:
    def test_meta_unmanaged(self):
        assert AgentServerEvent._meta.managed is False
        assert AgentServerEvent._meta.db_table == "agent_events"

    def test_ordering(self):
        assert AgentServerEvent._meta.ordering == ["sequence"]
