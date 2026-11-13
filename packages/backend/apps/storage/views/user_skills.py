"""API endpoints for user-authored skills (parallel to the marketplace)."""

import logging
from typing import List

from django.core.handlers.wsgi import WSGIRequest
from ninja import File
from ninja.files import UploadedFile as NinjaUploadedFile
from ninja.pagination import paginate

from apps.storage.models import UserSkill
from apps.storage.schemas.user_skills import (
    UserSkillCreateFromEditorSchema,
    UserSkillCreateFromGithubSchema,
    UserSkillDeleteResultSchema,
    UserSkillDetailSchema,
    UserSkillListSchema,
    UserSkillUpdateSchema,
)
from apps.storage.services import user_skills as svc
from apps.storage.views import CustomPageNumberPagination, memory_api
from config.errors.common import InvalidInputError, NotFoundError

logger = logging.getLogger(__name__)


# ── List + detail ────────────────────────────────────────────────────────────


@memory_api.get("/my-skills", response=List[UserSkillListSchema], tags=["My Skills"])
@paginate(CustomPageNumberPagination)
def list_my_skills(request: WSGIRequest):
    """List the authenticated user's authored skills (most recently updated first)."""
    return UserSkill.objects.for_owner(request.auth)


@memory_api.get(
    "/my-skills/{skill_id}",
    response=UserSkillDetailSchema,
    tags=["My Skills"],
)
def get_my_skill(request: WSGIRequest, skill_id: str):
    """Get full details of a user-authored skill including SKILL.md and files."""
    skill = UserSkill.objects.get_for_owner(request.auth, skill_id)
    if skill is None:
        raise NotFoundError(f"User skill '{skill_id}' not found")
    return skill


# ── Create flows ─────────────────────────────────────────────────────────────


@memory_api.post("/my-skills", response=UserSkillDetailSchema, tags=["My Skills"])
def create_my_skill_from_editor(
    request: WSGIRequest, payload: UserSkillCreateFromEditorSchema
):
    """Create a user skill from in-UI editor fields."""
    return svc.build_from_editor(
        request.auth,
        name=payload.name,
        description=payload.description,
        body=payload.body,
        category=payload.category,
        icon=payload.icon,
        skill_files=payload.skill_files,
    )


@memory_api.post(
    "/my-skills/from-github",
    response=UserSkillDetailSchema,
    tags=["My Skills"],
)
def create_my_skill_from_github(
    request: WSGIRequest, payload: UserSkillCreateFromGithubSchema
):
    """Import a user skill from a public GitHub URL."""
    return svc.build_from_github(request.auth, url=payload.url)


@memory_api.post(
    "/my-skills/upload", response=UserSkillDetailSchema, tags=["My Skills"]
)
def upload_my_skill(
    request: WSGIRequest,
    file: NinjaUploadedFile = File(...),
):
    """Upload a SKILL.md file or a .zip bundle. Dispatches on extension."""
    filename = (file.name or "").strip()
    lower = filename.lower()
    data = file.read()

    if lower.endswith(".zip"):
        return svc.build_from_zip(request.auth, file_bytes=data, filename=filename)
    if lower.endswith(".md") or lower.endswith(".markdown") or not lower:
        return svc.build_from_skill_md(
            request.auth, file_bytes=data, filename=filename or "SKILL.md"
        )
    raise InvalidInputError(
        "Unsupported file type. Upload a SKILL.md file or a .zip bundle."
    )


# ── Update + delete ──────────────────────────────────────────────────────────


@memory_api.patch(
    "/my-skills/{skill_id}",
    response=UserSkillDetailSchema,
    tags=["My Skills"],
)
def update_my_skill(
    request: WSGIRequest, skill_id: str, payload: UserSkillUpdateSchema
):
    """Partially update a user skill (editor-sourced skills support body edits)."""
    skill = UserSkill.objects.get_for_owner(request.auth, skill_id)
    if skill is None:
        raise NotFoundError(f"User skill '{skill_id}' not found")
    return svc.update_skill(
        skill,
        name=payload.name,
        description=payload.description,
        body=payload.body,
        category=payload.category,
        icon=payload.icon,
        skill_files=payload.skill_files,
    )


@memory_api.delete(
    "/my-skills/{skill_id}",
    response=UserSkillDeleteResultSchema,
    tags=["My Skills"],
)
def delete_my_skill(request: WSGIRequest, skill_id: str):
    """Delete a user-authored skill."""
    skill = UserSkill.objects.get_for_owner(request.auth, skill_id)
    if skill is None:
        raise NotFoundError(f"User skill '{skill_id}' not found")
    svc.delete_skill(skill)
    return UserSkillDeleteResultSchema(id=skill_id, deleted=True)
