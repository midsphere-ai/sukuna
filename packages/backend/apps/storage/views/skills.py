"""API endpoints for the skills marketplace: browse, search, install, uninstall."""

import logging
from typing import List

from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Count
from ninja.pagination import paginate

from apps.storage.models import SkillCatalogEntry, UserInstalledSkill
from apps.storage.schemas.skills import (
    CategoryCountSchema,
    SkillCatalogSchema,
    SkillDetailSchema,
    SkillInstallResultSchema,
)
from apps.storage.views import CustomPageNumberPagination, memory_api
from config.errors.common import NotFoundError

logger = logging.getLogger(__name__)

# ── Category icons (must match crawler) ───────────────────────────────────────
CATEGORY_ICONS = {
    "documents": "📄",
    "development": "💻",
    "data-analysis": "📊",
    "integration": "🔗",
    "security": "🔐",
    "ai-ml": "🤖",
    "marketing": "📈",
    "product-management": "📋",
    "collaboration": "🤝",
    "web3": "⛓️",
    "workflow": "⚡",
    "advanced": "🧪",
}


def _annotate_installed(skills, user):
    """Annotate a list of skill dicts with is_installed for the user."""
    installed_slugs = set(
        UserInstalledSkill.objects.filter(user=user).values_list(
            "skill__slug", flat=True
        )
    )
    for skill in skills:
        if hasattr(skill, "slug"):
            skill.is_installed = skill.slug in installed_slugs
    return skills


# ── Browse endpoints ──────────────────────────────────────────────────────────


@memory_api.get("/skills", response=List[SkillCatalogSchema], tags=["Skills"])
@paginate(CustomPageNumberPagination)
def list_skills(request: WSGIRequest, category: str = "", source_type: str = ""):
    """List all skills in the catalog with optional category/source filters."""
    qs = SkillCatalogEntry.objects.get_all()
    if category:
        qs = qs.filter(category=category)
    if source_type:
        qs = qs.filter(source_type=source_type)
    skills = list(qs)
    return _annotate_installed(skills, request.auth)


@memory_api.get("/skills/search", response=List[SkillCatalogSchema], tags=["Skills"])
@paginate(CustomPageNumberPagination)
def search_skills(request: WSGIRequest, q: str):
    """Search skills by name, description, or tags."""
    skills = list(SkillCatalogEntry.objects.search(q))
    return _annotate_installed(skills, request.auth)


@memory_api.get(
    "/skills/categories", response=List[CategoryCountSchema], tags=["Skills"]
)
def list_categories(request: WSGIRequest):
    """List all categories with skill counts."""
    counts = (
        SkillCatalogEntry.objects.values("category")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    return [
        CategoryCountSchema(
            category=row["category"],
            count=row["count"],
            icon=CATEGORY_ICONS.get(row["category"], "📦"),
        )
        for row in counts
    ]


@memory_api.get("/skills/installed", response=List[SkillCatalogSchema], tags=["Skills"])
@paginate(CustomPageNumberPagination)
def get_installed_skills(request: WSGIRequest):
    """Get all skills installed by the authenticated user."""
    installed = UserInstalledSkill.objects.for_user(request.auth)
    skills = [inst.skill for inst in installed]
    for skill in skills:
        skill.is_installed = True
    return skills


@memory_api.get("/skills/{slug}", response=SkillDetailSchema, tags=["Skills"])
def get_skill_detail(request: WSGIRequest, slug: str):
    """Get full skill details including SKILL.md content."""
    skill = SkillCatalogEntry.objects.get_by_slug(slug)
    if not skill:
        raise NotFoundError(f"Skill '{slug}' not found")
    installed_slugs = set(
        UserInstalledSkill.objects.filter(user=request.auth).values_list(
            "skill__slug", flat=True
        )
    )
    skill.is_installed = skill.slug in installed_slugs
    return skill


# ── Install/uninstall endpoints ───────────────────────────────────────────────


@memory_api.post(
    "/skills/{slug}/install", response=SkillInstallResultSchema, tags=["Skills"]
)
def install_skill(request: WSGIRequest, slug: str):
    """Install a skill for the authenticated user."""
    skill = SkillCatalogEntry.objects.get_by_slug(slug)
    if not skill:
        raise NotFoundError(f"Skill '{slug}' not found")
    UserInstalledSkill.objects.install(request.auth, skill)
    return SkillInstallResultSchema(slug=slug, installed=True)


@memory_api.delete(
    "/skills/{slug}/install", response=SkillInstallResultSchema, tags=["Skills"]
)
def uninstall_skill(request: WSGIRequest, slug: str):
    """Uninstall a skill for the authenticated user."""
    skill = SkillCatalogEntry.objects.get_by_slug(slug)
    if not skill:
        raise NotFoundError(f"Skill '{slug}' not found")
    UserInstalledSkill.objects.uninstall(request.auth, skill)
    return SkillInstallResultSchema(slug=slug, installed=False)
