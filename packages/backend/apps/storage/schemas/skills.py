"""Request/response schemas for skill marketplace API endpoints."""

from ninja import ModelSchema, Schema

from apps.storage.models import SkillCatalogEntry


class SkillCatalogSchema(ModelSchema):
    """Schema for skill catalog listing (no full content)."""

    is_installed: bool = False

    class Meta:
        model = SkillCatalogEntry
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "category",
            "source_type",
            "source_repo",
            "author",
            "has_scripts",
            "has_templates",
            "tags",
            "license",
            "version",
            "icon",
            "install_count",
            "is_featured",
            "date_created",
        ]


class SkillDetailSchema(ModelSchema):
    """Schema for skill detail view (includes full SKILL.md content)."""

    is_installed: bool = False

    class Meta:
        model = SkillCatalogEntry
        fields = "__all__"


class SkillInstallResultSchema(Schema):
    """Response for skill install/uninstall actions."""

    slug: str
    installed: bool


class InstalledSkillSchema(Schema):
    """Schema for a user's installed skill."""

    skill: SkillCatalogSchema
    installed_at: str


class CategoryCountSchema(Schema):
    """Schema for category listing with counts."""

    category: str
    count: int
    icon: str
