"""API view endpoints for the blogs app, serving CMS content to the frontend."""

import logging
from pathlib import Path
from typing import List, Optional

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import FileResponse
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from apps.blogs.schemas import (
    ChangelogEntrySchema,
    HomeBannerSchema,
    PartialTutorialBlogModelSchema,
    PlanFooterModelSchema,
    TutorialBlogModelSchema,
    api,
    authenticated_api,
    get_full_media_url,
)
from apps.blogs.service import CMS

logger = logging.getLogger(__name__)

cms = CMS()


def serialize_tutorial_partial(obj):
    """Serialize TutorialBlog to PartialTutorialBlogModelSchema dict."""
    return {
        "id": str(obj.id),
        "title": obj.title,
        "subtitle": obj.subtitle,
        "image": get_full_media_url(obj.image.name) if obj.image else None,
        "as_info_button": obj.as_info_button,
        "date_created": obj.date_created.isoformat(),
    }


def serialize_tutorial_full(obj):
    """Serialize TutorialBlog to TutorialBlogModelSchema dict."""
    return {
        "id": str(obj.id),
        "title": obj.title,
        "subtitle": obj.subtitle,
        "image": get_full_media_url(obj.image.name) if obj.image else None,
        "markdownText": obj.markdownText,
        "as_info_button": obj.as_info_button,
        "date_created": obj.date_created.isoformat(),
    }


@authenticated_api.get("/home-banner", response=HomeBannerSchema)
def get_home_banner(request: WSGIRequest):
    """Return the home banner containing the latest change log and announcement.

    Args:
        request: The incoming HTTP request.

    Returns:
        dict: Serialized home banner data.
    """
    return cms.get_home_banner()


@authenticated_api.get("/plan-footer", response=Optional[PlanFooterModelSchema])
def get_plan_footer(request: WSGIRequest):
    """Return the most recent plan footer content.

    Args:
        request: The incoming HTTP request.

    Returns:
        PlanFooterModelSchema or None: The serialized plan footer, or None.
    """
    return cms.get_plan_footer()


@authenticated_api.get("/tutorials", response=List[PartialTutorialBlogModelSchema])
@paginate(PageNumberPagination, page_size=500)
def get_tutorials(request: WSGIRequest):
    """Return a paginated list of all tutorial blogs (without body content).

    Args:
        request: The incoming HTTP request.

    Returns:
        list[dict]: A list of partially serialized tutorial blog entries.
    """
    return [serialize_tutorial_partial(obj) for obj in cms.get_tutorial_blogs()]


@authenticated_api.get("/tutorials/info", response=List[PartialTutorialBlogModelSchema])
@paginate(PageNumberPagination, page_size=500)
def get_tutorial_info(request: WSGIRequest):
    """Return a paginated list of tutorial blogs flagged as info buttons.

    Args:
        request: The incoming HTTP request.

    Returns:
        list[dict]: A list of partially serialized info-button tutorial entries.
    """
    return [serialize_tutorial_partial(obj) for obj in cms.get_tutorial_info_blogs()]


@authenticated_api.get("/tutorials/content", response=Optional[TutorialBlogModelSchema])
def get_tutorial_data(request: WSGIRequest, title: str):
    """Return full tutorial blog content for a given title.

    Args:
        request: The incoming HTTP request.
        title: The exact title of the tutorial to retrieve.

    Returns:
        dict or None: The fully serialized tutorial, or None if not found.
    """
    obj = cms.get_tutorial_data(title=title)
    if obj:
        return serialize_tutorial_full(obj)
    return None


@api.get("/changelog", response=List[ChangelogEntrySchema])
@paginate(PageNumberPagination, page_size=20)
def get_changelog(request: WSGIRequest):
    """Return a paginated list of published changelog entries.

    Args:
        request: The incoming HTTP request.

    Returns:
        list[ChangelogEntry]: A list of published changelog entry instances.
    """
    return list(cms.get_changelog_entries())


@api.get("/public/home-banner", response=HomeBannerSchema)
def get_public_home_banner(request: WSGIRequest):
    """Return the home banner data for unauthenticated users.

    Args:
        request: The incoming HTTP request.

    Returns:
        dict: Serialized home banner data.
    """
    return cms.get_home_banner()


@api.get("/public/tutorials", response=List[PartialTutorialBlogModelSchema])
@paginate(PageNumberPagination, page_size=500)
def get_public_tutorials(request: WSGIRequest):
    """Return a paginated list of all tutorial blogs for unauthenticated users.

    Args:
        request: The incoming HTTP request.

    Returns:
        list[dict]: A list of partially serialized tutorial blog entries.
    """
    return [serialize_tutorial_partial(obj) for obj in cms.get_tutorial_blogs()]


@api.get("/public/tutorials/content", response=Optional[TutorialBlogModelSchema])
def get_public_tutorial_data(request: WSGIRequest, title: str):
    """Return full tutorial blog content for unauthenticated users.

    Args:
        request: The incoming HTTP request.
        title: The exact title of the tutorial to retrieve.

    Returns:
        dict or None: The fully serialized tutorial, or None if not found.
    """
    obj = cms.get_tutorial_data(title=title)
    if obj:
        return serialize_tutorial_full(obj)
    return None


@api.get("/images")
def get_image(request, key: str):
    """
    Returns the image from the specified path.
    Handles path sanitization for different formats.
    """
    clean_key = key.replace('"', "").replace("\\", "/").strip("/")

    # Construct the path using pathlib for better cross-platform handling
    image_path = Path(settings.BASE_DIR) / clean_key
    if not image_path.is_file():
        raise HttpError(404, "Image not found")

    return FileResponse(image_path.open("rb"), content_type="image/jpeg")
