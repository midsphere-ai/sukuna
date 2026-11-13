"""API endpoints for file upload, listing, download, and retrieval from object storage."""

from typing import List

from django.core.handlers.wsgi import WSGIRequest
from ninja import File, Query
from ninja.files import UploadedFile as NinjaUploadedFile
from ninja.pagination import paginate

from apps.storage.factory.memory import get_memory_service
from apps.storage.schemas.memory import (
    FileRetrieveResponse,
    FileUploadResponse,
    StoreFiledSchema,
)
from apps.storage.views import CustomPageNumberPagination, memory_api
from config.errors.common import NotFoundError, UnauthorizedAccessError


@memory_api.get(
    "/conversations/{conversation_id}/files",
    response=List[StoreFiledSchema],
    tags=["Files"],
)
def get_conversation_files(request: WSGIRequest, conversation_id: str):
    """Get all files associated with a specific conversation."""
    from apps.storage.models import ConversationFile, StoredFile

    memory = get_memory_service()
    # Validate ownership
    conv = memory._get_conversation_for_user(
        memory._validate_uuid(conversation_id, "Conversation ID"),
        memory._get_authenticated_user(request),
    )
    file_ids = ConversationFile.objects.filter(conversation=conv).values_list(
        "stored_file_id", flat=True
    )
    return StoredFile.objects.filter(id__in=file_ids).order_by("-uploaded_at")


@memory_api.post("/files", response=FileUploadResponse)
def upload_file(
    request: WSGIRequest,
    file: NinjaUploadedFile = File(...),
):
    """
    Upload a file and store it for the authenticated user.

    Args:
        file: The uploaded file

    Returns:
        FileUploadResponse: File upload confirmation with details
    """
    memory = get_memory_service()
    result = memory.upload_file(request, file)
    return FileUploadResponse(
        file_id=str(result.file_id),
        filename=result.filename,
        size=result.size,
        mime_type=result.mime_type,
    )


@memory_api.get("/files", response=List[StoreFiledSchema])
@paginate(CustomPageNumberPagination)
def get_user_files(
    request: WSGIRequest,
):
    """
    Get all files uploaded by the authenticated user.

    Returns:
        Paginated list of user files
    """
    memory = get_memory_service()
    return memory.get_user_files(request)


@memory_api.get(
    "/files/{file_id}/download", response=FileRetrieveResponse, tags=["Files"]
)
def download_file(
    request: WSGIRequest,
    file_id: str,
):
    """
    Download a file by its ID.

    Returns a presigned URL to download the file directly from storage.

    Args:
        file_id: UUID of the stored file

    Returns:
        FileRetrieveResponse: File URL and metadata
    """
    from apps.storage.models import StoredFile

    user = request.auth
    if not user:
        raise UnauthorizedAccessError("Authentication required")

    try:
        stored_file = StoredFile.objects.get(id=file_id, owner=user)
    except StoredFile.DoesNotExist:
        raise NotFoundError(f"File not found: {file_id}")

    return FileRetrieveResponse(
        url=stored_file.file.url,
        filename=stored_file.name,
        mime_type=stored_file.mime_type,
        size=stored_file.size,
    )


@memory_api.get("/files/retrieve", response=FileRetrieveResponse, tags=["Files"])
def retrieve_file(
    request: WSGIRequest,
    path: str = Query(..., description="File path within the storage bucket"),
):
    """
    Retrieve a file from DigitalOcean Spaces storage by path.

    Returns a presigned URL to access the file directly from storage.
    The path should be relative to the media bucket root.

    Args:
        path: File path within the storage bucket (e.g., 'uploads/user123/file.pdf')

    Returns:
        FileRetrieveResponse: File URL and metadata
    """
    import mimetypes

    from django.core.files.storage import default_storage

    user = request.auth
    if not user:
        raise UnauthorizedAccessError("Authentication required")

    # Normalize path - remove leading/trailing slashes
    normalized_path = path.strip("/")

    # Check if file exists in storage
    if not default_storage.exists(normalized_path):
        raise NotFoundError(f"File not found: {normalized_path}")

    # Get the file URL from storage
    file_url = default_storage.url(normalized_path)

    # Try to get file size
    try:
        file_size = default_storage.size(normalized_path)
    except Exception:
        file_size = None

    # Determine MIME type from filename
    filename = (
        normalized_path.split("/")[-1] if "/" in normalized_path else normalized_path
    )
    mime_type, _ = mimetypes.guess_type(filename)

    return FileRetrieveResponse(
        url=file_url,
        filename=filename,
        mime_type=mime_type,
        size=file_size,
    )
