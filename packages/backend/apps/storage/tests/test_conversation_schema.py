import pytest

from apps.storage.models import AgentRun, Conversation
from apps.storage.schemas.memory import ConversationModelSchema
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _create_conversation_with_status(status: str | None) -> Conversation:
    user = UserFactory()
    conversation = Conversation.objects.create(user=user, title="Schema status test")
    if status is not None:
        run = AgentRun.objects.create(
            user=user,
            conversation=conversation,
            task="Test task",
            status=status,
        )
        conversation.current_task = run
        conversation.save(update_fields=["current_task"])
    return conversation


def test_resolve_status_returns_idle_when_no_run():
    conversation = _create_conversation_with_status(None)
    assert ConversationModelSchema.resolve_status(conversation) == "idle"


def test_resolve_status_maps_pending_to_queued():
    conversation = _create_conversation_with_status(AgentRun.Status.PENDING)
    assert ConversationModelSchema.resolve_status(conversation) == "queued"


@pytest.mark.parametrize(
    "run_status",
    [
        AgentRun.Status.QUEUED,
        AgentRun.Status.PROVISIONING,
        AgentRun.Status.RUNNING,
        AgentRun.Status.COMPLETED,
        AgentRun.Status.FAILED,
        AgentRun.Status.CANCELLED,
    ],
)
def test_resolve_status_preserves_supported_statuses(run_status: str):
    conversation = _create_conversation_with_status(run_status)
    assert ConversationModelSchema.resolve_status(conversation) == run_status
