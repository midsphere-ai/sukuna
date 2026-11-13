"""Ninja API schemas and serialization for the blogs app."""

from typing import Optional

from django.conf import settings
from ninja import ModelSchema, NinjaAPI, Schema

from apps.blogs.models import (
    Announcements,
    ChangeLog,
    ChangelogEntry,
    PlanFooter,
    TutorialBlog,
)
from apps.users.adapters import NinjaAuthAdapter
from config.errors.handlers import register_error_handlers

api = NinjaAPI(urls_namespace="cms_unauthorised")

authenticated_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="blogs")

register_error_handlers(api)
register_error_handlers(authenticated_api)


def get_full_media_url(file_name: str) -> Optional[str]:
    """Build full DigitalOcean Spaces media URL from file name."""
    if not file_name:
        return None
    # Always use DO Spaces URL if configured
    do_spaces_url = getattr(settings, "DO_SPACES_MEDIA_URL", None)
    if do_spaces_url:
        return f"{do_spaces_url.rstrip('/')}/{file_name}"
    # Fallback to MEDIA_URL (for production where it's the full URL)
    if settings.MEDIA_URL.startswith("http"):
        return f"{settings.MEDIA_URL.rstrip('/')}/{file_name}"
    # Last fallback - relative path
    return f"{settings.MEDIA_URL.rstrip('/')}/{file_name}"


class ChangeLogModelSchema(ModelSchema):
    """Schema for serializing ChangeLog model instances."""

    class Meta:
        model = ChangeLog
        fields = "__all__"


class AnnouncementsModelSchema(ModelSchema):
    """
    AnnouncementsModelSchema is a schema for serializing and deserializing
    the Announcements model. It inherits from ModelSchema and includes
    all fields of the Announcements model.

    Attributes:
        Meta (class): A nested class that defines metadata for the schema.
            model (Announcements): The model class that this schema is for.
            fields (str): Specifies that all fields of the model should be included.
    """

    class Meta:
        model = Announcements
        fields = "__all__"


class TutorialBlogModelSchema(Schema):
    """
    Schema for the TutorialBlog model.
    """

    id: str
    title: str
    subtitle: Optional[str] = None
    image: Optional[str] = None
    markdownText: str
    as_info_button: bool
    date_created: str

    @staticmethod
    def from_orm(obj: TutorialBlog) -> "TutorialBlogModelSchema":
        """Convert a TutorialBlog ORM instance to this schema.

        Args:
            obj: The TutorialBlog model instance.

        Returns:
            TutorialBlogModelSchema: The serialized schema instance.
        """
        return TutorialBlogModelSchema(
            id=str(obj.id),
            title=obj.title,
            subtitle=obj.subtitle,
            image=get_full_media_url(obj.image.name) if obj.image else None,
            markdownText=obj.markdownText,
            as_info_button=obj.as_info_button,
            date_created=obj.date_created.isoformat(),
        )


class PartialTutorialBlogModelSchema(Schema):
    """
    Schema for the TutorialBlog model (without markdownText).
    """

    id: str
    title: str
    subtitle: Optional[str] = None
    image: Optional[str] = None
    as_info_button: bool
    date_created: str

    @staticmethod
    def from_orm(obj: TutorialBlog) -> "PartialTutorialBlogModelSchema":
        """Convert a TutorialBlog ORM instance to this partial schema (without body).

        Args:
            obj: The TutorialBlog model instance.

        Returns:
            PartialTutorialBlogModelSchema: The serialized schema instance.
        """
        return PartialTutorialBlogModelSchema(
            id=str(obj.id),
            title=obj.title,
            subtitle=obj.subtitle,
            image=get_full_media_url(obj.image.name) if obj.image else None,
            as_info_button=obj.as_info_button,
            date_created=obj.date_created.isoformat(),
        )


class HomeBannerSchema(Schema):
    """
    HomeBannerSchema is a schema class that represents the structure of the home banner data.

    Attributes:
        change_log (ChangeLogModelSchema): The schema for the change log associated with the home banner.
        announcement (AnnouncementsModelSchema): The schema for the announcements associated with the home banner.
    """

    change_log: Optional[ChangeLogModelSchema] = None
    announcement: Optional[AnnouncementsModelSchema] = None


class GetTutorialData(Schema):
    """
    Schema for retrieving tutorial data.

    Attributes:
        title (str): The title of the tutorial.
    """

    title: str


class ChangelogEntrySchema(ModelSchema):
    """Schema for serializing ChangelogEntry model instances."""

    class Meta:
        model = ChangelogEntry
        fields = ["id", "title", "body", "date", "category", "is_published"]


class PlanFooterModelSchema(ModelSchema):
    """Schema for serializing PlanFooter model instances."""

    class Meta:
        model = PlanFooter
        fields = "__all__"
