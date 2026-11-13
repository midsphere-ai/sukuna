"""API endpoints for conversation CRUD, bulk operations, sharing, and SSE streaming."""

import asyncio
import json
import logging
from typing import AsyncGenerator, List, Optional

from asgiref.sync import sync_to_async
from django.core.handlers.wsgi import WSGIRequest
from django.http import StreamingHttpResponse
from ninja import Schema
from ninja.pagination import paginate

from apps.storage.factory.memory import get_memory_service
from apps.storage.memory import ConversationNotFoundError
from apps.storage.schemas.memory import (
    ConversationCreateResponse,
    ConversationModelSchema,
    ConversationUpdateRequest,
    DeleteResponse,
    SharedConversationSchema,
)
from apps.storage.views import (
    CustomPageNumberPagination,
    memory_api,
    memory_public_api,
    storage_stream_api,
)
from config.errors.common import NotFoundError, UnauthorizedAccessError

logger = logging.getLogger(__name__)


@memory_api.post("/conversations", response=ConversationCreateResponse)
def start_conversation(
    request: WSGIRequest,
):
    """
    Start a new conversation or return existing empty conversation.

    Returns:
        ConversationCreateResponse: Conversation details and creation status
    """
    memory = get_memory_service()
    result = memory.create_conversation(request)
    return ConversationCreateResponse(
        conversation_id=str(result.conversation_id),
        is_new=result.is_new,
        message="New conversation created"
        if result.is_new
        else "Existing empty conversation returned",
    )


@memory_api.get("/conversations/search", response=List[ConversationModelSchema])
@paginate(CustomPageNumberPagination)
def search_threads(request: WSGIRequest, query: str):
    """
    Search conversations by query string.

    Args:
        query: Search query string

    Returns:
        List[ConversationModelSchema]: Paginated list of matching conversations
    """
    service = get_memory_service()
    return service.search_threads(request, query)


@memory_api.post(
    "/conversations/{conversation_id}/cancel", response=ConversationModelSchema
)
def cancel_task(
    request: WSGIRequest,
    conversation_id: str,
):
    """Cancel the active task on a conversation.

    Args:
        conversation_id: ID of the conversation whose task to cancel.

    Returns:
        ConversationModelSchema: The updated conversation.
    """
    from apps.storage.services.memory import get_memory_service

    memory = get_memory_service()
    conversation = memory._get_conversation_for_user(conversation_id, request.auth)
    conversation.status = "cancelled"
    conversation.save(update_fields=["status"])
    return conversation


@memory_api.get("/conversations", response=List[ConversationModelSchema])
@paginate(CustomPageNumberPagination)
def get_all_conversations(
    request: WSGIRequest,
):
    """
    Get all conversations for the authenticated user with pagination.

    Returns:
        List[ConversationModelSchema]: Paginated list of conversations
    """
    memory = get_memory_service()
    return memory.get_user_conversations(request)


@memory_api.delete("/conversations/{conversation_id}", response=DeleteResponse)
def delete_chat(
    request: WSGIRequest,
    conversation_id: str,
):
    """
    Delete a specific conversation.

    Args:
        conversation_id: ID of the conversation to delete

    Returns:
        DeleteResponse: Confirmation message
    """
    memory = get_memory_service()
    memory.delete_conversation(request, conversation_id)
    return DeleteResponse(message="Chat deleted successfully", deleted_count=1)


@memory_api.patch("/conversations/{conversation_id}", response=ConversationModelSchema)
def update_conversation(
    request: WSGIRequest,
    conversation_id: str,
    data: ConversationUpdateRequest,
):
    """
    Update a conversation's title and/or metadata.

    Args:
        conversation_id: ID of the conversation to update
        data: Request body with optional title and metadata fields

    Returns:
        ConversationModelSchema: Updated conversation
    """
    memory = get_memory_service()
    return memory.update_conversation(
        request,
        conversation_id,
        title=data.title,
        metadata=data.metadata,
    )


@memory_api.delete("/conversations", response=DeleteResponse)
def delete_all_chats(
    request: WSGIRequest,
):
    """
    Delete all conversations for the authenticated user.

    Returns:
        DeleteResponse: Confirmation message with count of deleted conversations
    """
    memory = get_memory_service()
    deleted_count = memory.delete_all_user_conversations(request)
    return DeleteResponse(
        message="All chats deleted successfully", deleted_count=deleted_count
    )


# Bulk Operations
class BulkDeleteRequest(Schema):
    """Request schema for bulk deleting conversations."""

    conversation_ids: List[str]


@memory_api.post("/conversations/bulk-delete", response=DeleteResponse)
def bulk_delete_conversations(
    request: WSGIRequest,
    data: BulkDeleteRequest,
):
    """
    Delete multiple conversations in bulk.

    Args:
        data: Request containing list of conversation IDs to delete

    Returns:
        DeleteResponse: Confirmation with count of deleted conversations
    """
    deleted_count = 0
    errors = []
    memory = get_memory_service()
    for conversation_id in data.conversation_ids:
        try:
            memory.delete_conversation(request, conversation_id)
            deleted_count += 1
        except (ConversationNotFoundError, UnauthorizedAccessError) as e:
            errors.append(f"Failed to delete {conversation_id}: {str(e)}")

    message = f"Successfully deleted {deleted_count} conversations"
    if errors:
        message += f". {len(errors)} errors occurred."

    return DeleteResponse(message=message, deleted_count=deleted_count)


# =============================================================================
# PUBLIC (UNAUTHENTICATED) ENDPOINTS
# =============================================================================


@memory_public_api.get(
    "/conversations/{conversation_id}/shared", response=SharedConversationSchema
)
def get_shared_conversation(
    request,
    conversation_id: str,
):
    """
    Get a shared conversation without authentication.

    Returns conversation info only if the conversation exists and has
    metadata.shared set to True. Returns 404 otherwise.
    """
    from apps.storage.models import Conversation

    try:
        conversation = Conversation.objects.get(id=conversation_id)
    except Conversation.DoesNotExist:
        raise NotFoundError("Conversation not found")

    metadata = conversation.metadata or {}
    if not metadata.get("shared"):
        raise NotFoundError("Conversation not found")

    return SharedConversationSchema(
        id=str(conversation.id),
        title=conversation.title or "Untitled",
        date_created=conversation.date_created.isoformat()
        if conversation.date_created
        else "",
        date_updated=conversation.date_updated.isoformat()
        if conversation.date_updated
        else "",
    )


# =============================================================================
# SSE STREAMING ENDPOINTS
# =============================================================================


class ConversationSSEData(Schema):
    """Schema for conversation data in SSE events."""

    id: str
    title: Optional[str] = None
    summary: Optional[str] = None
    on_going: bool = False
    has_error: bool = False
    requires_user_input: bool = False
    date_updated: Optional[str] = None
    status: str = "completed"


@storage_stream_api.get("/conversations/stream/")
async def stream_conversation_updates(request):
    """
    Production-ready SSE endpoint for streaming conversation list updates.

    Features:
    - SSE event IDs for client reconnection
    - Last-Event-ID support for resumption after disconnect
    - Proper change detection using date_updated tracking
    - Heartbeat comments every iteration for keepalive
    - Retry directive for automatic reconnection

    Headers:
    - Last-Event-ID: Resume from this event ID (monotonic counter)

    Events:
    - conversation_updated: A conversation was created or modified
    - conversation_deleted: A conversation was deleted
    - sync_complete: Initial load finished
    - error: Error occurred (stream continues)

    Query parameters:
    - poll_interval: Polling interval in milliseconds (default 500, min 200, max 5000)
    """
    from apps.storage.models import Conversation

    user = request.auth

    # Get poll interval from query params (default 500ms)
    poll_interval_ms = 500
    if hasattr(request, "GET") and "poll_interval" in request.GET:
        try:
            poll_interval_ms = max(
                200, min(5000, int(request.GET.get("poll_interval", 500)))
            )
        except (ValueError, TypeError):
            poll_interval_ms = 500

    poll_interval = poll_interval_ms / 1000.0

    # Parse Last-Event-ID for resumption
    last_event_id = 0
    if hasattr(request, "headers"):
        try:
            last_event_id = int(request.headers.get("Last-Event-ID", 0))
        except (ValueError, TypeError):
            pass
    elif hasattr(request, "META"):
        try:
            last_event_id = int(request.META.get("HTTP_LAST_EVENT_ID", 0))
        except (ValueError, TypeError):
            pass

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events from database polling."""
        # Track conversation states for change detection
        # Maps conversation_id -> (date_updated, hash of key fields)
        conversation_states: dict = {}
        event_counter = last_event_id

        # Send retry directive at start (1 second reconnection)
        yield "retry: 1000\n\n"

        # Initial load of most recent conversations (limit to prevent memory issues)
        _SSE_CONVERSATION_LIMIT = 200
        conversations = await sync_to_async(list)(
            Conversation.objects.filter(user=user)
            .select_related("current_task")
            .order_by("-date_created")[:_SSE_CONVERSATION_LIMIT]
        )

        for conv in conversations:
            conv_id = str(conv.id)
            is_ongoing = conv.get_is_ongoing()
            has_error = conv.get_has_error()

            # Determine run status from current_task
            run_status = "idle"
            if conv.current_task_id:
                try:
                    run_status = conv.current_task.status
                except Exception:
                    pass
            if run_status == "pending":
                run_status = "queued"

            # Store state for change detection
            conv_hash = hash(
                (
                    conv.title,
                    conv.icon,
                    conv.summary,
                    is_ongoing,
                    has_error,
                    conv.requires_user_input,
                    run_status,
                )
            )
            conversation_states[conv_id] = (conv.date_updated, conv_hash)

            event_counter += 1
            event_data = {
                "type": "conversation_updated",
                "conversation": {
                    "id": conv_id,
                    "title": conv.title,
                    "icon": conv.icon or "",
                    "summary": conv.summary,
                    "on_going": is_ongoing,
                    "has_error": has_error,
                    "requires_user_input": conv.requires_user_input,
                    "date_updated": conv.date_updated.isoformat()
                    if conv.date_updated
                    else None,
                    "status": run_status,
                    "project_id": str(conv.project_id) if conv.project_id else None,
                },
                "is_new": True,
            }
            yield f"id: {event_counter}\n"
            yield "event: conversation_updated\n"
            yield f"data: {json.dumps(event_data)}\n\n"

        # Yield initial sync complete event
        event_counter += 1
        yield f"id: {event_counter}\n"
        yield "event: sync_complete\n"
        yield f"data: {json.dumps({'type': 'sync_complete', 'count': len(conversations)})}\n\n"

        while True:
            try:
                # Query for recent user conversations
                current_conversations = await sync_to_async(list)(
                    Conversation.objects.filter(user=user)
                    .select_related("current_task")
                    .order_by("-date_created")[:_SSE_CONVERSATION_LIMIT]
                )

                current_ids = set()

                for conv in current_conversations:
                    conv_id = str(conv.id)
                    current_ids.add(conv_id)

                    is_ongoing = conv.get_is_ongoing()
                    has_error = conv.get_has_error()

                    # Determine run status from current_task
                    run_status = "idle"
                    if conv.current_task_id:
                        try:
                            run_status = conv.current_task.status
                        except Exception:
                            pass
                    if run_status == "pending":
                        run_status = "queued"

                    # Calculate current state hash
                    conv_hash = hash(
                        (
                            conv.title,
                            conv.icon,
                            conv.summary,
                            is_ongoing,
                            has_error,
                            conv.requires_user_input,
                            run_status,
                        )
                    )

                    # Check if new or modified
                    is_new = conv_id not in conversation_states
                    is_modified = False

                    if not is_new:
                        old_date, old_hash = conversation_states[conv_id]
                        # Check if date_updated changed OR if key fields changed
                        if conv.date_updated != old_date or conv_hash != old_hash:
                            is_modified = True

                    # Update tracked state
                    conversation_states[conv_id] = (conv.date_updated, conv_hash)

                    # Send event for new or modified conversations
                    if is_new or is_modified:
                        event_counter += 1
                        event_data = {
                            "type": "conversation_updated",
                            "conversation": {
                                "id": conv_id,
                                "title": conv.title,
                                "icon": conv.icon or "",
                                "summary": conv.summary,
                                "on_going": is_ongoing,
                                "has_error": has_error,
                                "requires_user_input": conv.requires_user_input,
                                "date_updated": conv.date_updated.isoformat()
                                if conv.date_updated
                                else None,
                                "status": run_status,
                                "project_id": str(conv.project_id)
                                if conv.project_id
                                else None,
                            },
                            "is_new": is_new,
                        }
                        yield f"id: {event_counter}\n"
                        yield "event: conversation_updated\n"
                        yield f"data: {json.dumps(event_data)}\n\n"

                # Detect deleted conversations
                deleted_ids = set(conversation_states.keys()) - current_ids
                for deleted_id in deleted_ids:
                    del conversation_states[deleted_id]
                    event_counter += 1
                    yield f"id: {event_counter}\n"
                    yield "event: conversation_deleted\n"
                    yield f"data: {json.dumps({'type': 'conversation_deleted', 'conversation_id': deleted_id})}\n\n"

                # Send heartbeat comment every iteration (SSE comment format)
                yield ": heartbeat\n\n"

                await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                # Client disconnected
                logger.info(f"SSE conversation stream cancelled for user {user.id}")
                break
            except Exception as e:
                logger.error(f"Error in conversation SSE stream: {e}", exc_info=True)
                event_counter += 1
                yield f"id: {event_counter}\n"
                yield "event: error\n"
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                # Continue streaming after error
                await asyncio.sleep(poll_interval)

    response = StreamingHttpResponse(
        event_generator(), content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["X-Accel-Buffering"] = "no"
    response["Connection"] = "keep-alive"
    return response
