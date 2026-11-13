"""
Helper utilities for integration tests.

These helpers work with the real database and real services.
"""

from asgiref.sync import sync_to_async

from apps.storage.models import AgentRun, Conversation

# ============================================================================
# CONVERSATION HELPERS
# ============================================================================


async def set_conversation_ongoing(
    conversation: Conversation, ongoing: bool = True
) -> None:
    """Set conversation ongoing status via AgentRun.

    on_going is now a derived property from the current_task's status.
    To make a conversation "ongoing", we ensure it has a running AgentRun.
    To make it "not ongoing", we mark the current AgentRun as completed.
    """

    @sync_to_async
    def _update():
        if ongoing:
            # Ensure there's a running AgentRun linked to this conversation
            if conversation.current_task_id is None:
                run = AgentRun.objects.create(
                    conversation=conversation,
                    user=conversation.user,
                    task="test",
                    status=AgentRun.Status.RUNNING,
                )
                conversation.current_task = run
                conversation.save(update_fields=["current_task"])
            else:
                run = conversation.current_task
                if run.status not in ("pending", "running"):
                    run.status = AgentRun.Status.RUNNING
                    run.save(update_fields=["status"])
        else:
            if conversation.current_task_id is not None:
                run = conversation.current_task
                if run.status in ("pending", "running"):
                    run.mark_completed()

    await _update()


async def request_conversation_cancellation(conversation: Conversation) -> None:
    """Request cancellation for a conversation via AgentRun.

    cancellation_requested is now derived from current_task.status == "cancelled".
    """

    @sync_to_async
    def _update():
        if conversation.current_task_id is not None:
            run = conversation.current_task
            run.mark_cancelled()

    await _update()


# ============================================================================
# ASSERTION HELPERS
# ============================================================================


def assert_contains_text(result, text: str) -> bool:
    """Check if any response contains the given text"""
    all_text = result.all_text.lower() if hasattr(result, "all_text") else ""
    return text.lower() in all_text


def assert_error_contains(result, expected_substring: str) -> bool:
    """Check if error message contains expected text"""
    if not result.error:
        return False
    return expected_substring.lower() in result.error.lower()


def assert_status(result, expected_status: str) -> bool:
    """Check if final status matches expected"""
    return result.final_status == expected_status
