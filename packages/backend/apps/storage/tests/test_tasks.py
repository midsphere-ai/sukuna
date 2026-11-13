"""Tests for storage Celery tasks after core/ elimination refactor."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.storage.models import AgentRun, Conversation
from apps.storage.tasks import (
    purge_empty_conversations,
    set_title_conversations,
)
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def old_conversation(user):
    """A conversation created 20 minutes ago with no runs."""
    conv = Conversation.objects.create(user=user, title="Old Empty")
    Conversation.objects.filter(pk=conv.pk).update(
        date_created=timezone.now() - timedelta(minutes=20)
    )
    conv.refresh_from_db()
    return conv


class TestPurgeEmptyConversations:
    def test_purges_old_empty_conversations(self, old_conversation):
        result = purge_empty_conversations()
        assert result["purged_count"] == 1
        assert not Conversation.objects.filter(pk=old_conversation.pk).exists()

    def test_keeps_recent_empty_conversations(self, user):
        conv = Conversation.objects.create(user=user, title="Recent")
        result = purge_empty_conversations()
        assert result["purged_count"] == 0
        assert Conversation.objects.filter(pk=conv.pk).exists()

    def test_keeps_conversations_with_runs(self, user):
        conv = Conversation.objects.create(user=user, title="Has Run")
        Conversation.objects.filter(pk=conv.pk).update(
            date_created=timezone.now() - timedelta(minutes=20)
        )
        AgentRun.objects.create(conversation=conv, user=user, task="do something")
        result = purge_empty_conversations()
        assert result["purged_count"] == 0
        assert Conversation.objects.filter(pk=conv.pk).exists()


class TestSetTitleConversations:
    def test_sets_title_from_first_run(self, user):
        conv = Conversation.objects.create(user=user, title="")
        Conversation.objects.filter(pk=conv.pk).update(
            date_created=timezone.now() - timedelta(minutes=20)
        )
        AgentRun.objects.create(
            conversation=conv, user=user, task="Build a landing page for my startup"
        )

        result = set_title_conversations()
        conv.refresh_from_db()
        assert conv.title == "Build a landing page for my startup"
        assert result["updated"] == 1

    def test_truncates_long_titles(self, user):
        conv = Conversation.objects.create(user=user, title="")
        Conversation.objects.filter(pk=conv.pk).update(
            date_created=timezone.now() - timedelta(minutes=20)
        )
        long_prompt = "A" * 200
        AgentRun.objects.create(conversation=conv, user=user, task=long_prompt)

        set_title_conversations()
        conv.refresh_from_db()
        assert len(conv.title) == 120
        assert conv.title.endswith("...")

    def test_uses_first_line_only(self, user):
        conv = Conversation.objects.create(user=user, title="")
        Conversation.objects.filter(pk=conv.pk).update(
            date_created=timezone.now() - timedelta(minutes=20)
        )
        AgentRun.objects.create(
            conversation=conv, user=user, task="First line\nSecond line\nThird"
        )

        set_title_conversations()
        conv.refresh_from_db()
        assert conv.title == "First line"

    def test_skips_recent_conversations(self, user):
        conv = Conversation.objects.create(user=user, title="")
        AgentRun.objects.create(conversation=conv, user=user, task="Hello")

        result = set_title_conversations()
        conv.refresh_from_db()
        assert conv.title == ""
        assert result["updated"] == 0

    def test_skips_conversations_with_existing_title(self, user):
        conv = Conversation.objects.create(user=user, title="Already titled")
        Conversation.objects.filter(pk=conv.pk).update(
            date_created=timezone.now() - timedelta(minutes=20)
        )
        AgentRun.objects.create(conversation=conv, user=user, task="Something else")

        result = set_title_conversations()
        conv.refresh_from_db()
        assert conv.title == "Already titled"
        assert result["updated"] == 0


# Stuck-run reaping moved to the sandbox agent server — it owns terminal-state
# transitions after the backend purge.


class TestTerminateDelayedSandboxes:
    def test_import_and_callable(self):
        """Verify terminate_delayed_sandboxes can be imported and called (no idle sandboxes)."""
        from apps.agents.tasks import terminate_delayed_sandboxes

        count = terminate_delayed_sandboxes()
        assert count == 0


class TestCeleryBeatScheduleReferences:
    """Verify all task paths in CELERY_BEAT_SCHEDULE are importable."""

    def test_all_beat_tasks_importable(self, settings):
        from importlib import import_module

        for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
            task_path = entry["task"]
            module_path, func_name = task_path.rsplit(".", 1)
            mod = import_module(module_path)
            assert hasattr(mod, func_name), (
                f"Beat schedule '{name}' references '{task_path}' "
                f"but '{func_name}' not found in '{module_path}'"
            )
