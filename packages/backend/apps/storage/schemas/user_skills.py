"""Request/response schemas for the user-authored skills API."""

from typing import Dict, Optional

from ninja import ModelSchema, Schema

from apps.storage.models import UserSkill


class UserSkillListSchema(ModelSchema):
    """Summary schema (no full content) for list views."""

    class Meta:
        model = UserSkill
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "category",
            "icon",
            "source",
            "source_url",
            "version",
            "date_created",
            "date_updated",
        ]


class UserSkillDetailSchema(ModelSchema):
    """Full schema including SKILL.md content and supporting files."""

    class Meta:
        model = UserSkill
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "category",
            "icon",
            "source",
            "source_url",
            "version",
            "skill_md_content",
            "skill_files",
            "date_created",
            "date_updated",
        ]


class UserSkillCreateFromEditorSchema(Schema):
    """Body for POST /memory/my-skills (editor flow)."""

    name: str
    description: str
    body: str
    category: str = ""
    icon: str = ""
    skill_files: Dict[str, str] = {}


class UserSkillCreateFromGithubSchema(Schema):
    """Body for POST /memory/my-skills/from-github."""

    url: str


class UserSkillUpdateSchema(Schema):
    """Partial update body for PATCH /memory/my-skills/{id}."""

    name: Optional[str] = None
    description: Optional[str] = None
    body: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    skill_files: Optional[Dict[str, str]] = None


class UserSkillDeleteResultSchema(Schema):
    id: str
    deleted: bool
