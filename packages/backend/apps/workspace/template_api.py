"""Project template CRUD API — org-scoped, enterprise-gated.

Endpoints are mounted under /api/v1/workspace/organizations/{org_id}/templates/.
Admin+ can create/update/delete templates. Member+ can list and view.
"""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from django.db import transaction
from ninja import NinjaAPI, Schema

from apps.spaces.models import (
    Project,
    ProjectTemplate,
    ProjectTemplateFile,
)
from apps.users.adapters import NinjaAuthAdapter
from apps.workspace.enterprise import require_enterprise
from apps.workspace.models import Organization
from apps.workspace.permissions import OrgPermission, check_org_permission
from config.errors.common import NotFoundError
from config.errors.handlers import register_error_handlers

logger = logging.getLogger(__name__)

template_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="templates")
register_error_handlers(template_api)

# ── Size limits ────────────────────────────────────────────────────────────

MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB per file
MAX_TOTAL_SIZE = 10 * 1024 * 1024  # 10 MB per template


# ── Schemas ────────────────────────────────────────────────────────────────


class TemplateFileIn(Schema):
    file_name: str
    file_content: str
    sort_order: int = 0


class TemplateFileOut(Schema):
    id: UUID
    file_name: str
    file_content: str
    sort_order: int


class TemplateOut(Schema):
    id: UUID
    name: str
    description: str
    custom_instructions: str
    icon: str
    created_by_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    files: List[TemplateFileOut] = []


class CreateTemplateRequest(Schema):
    name: str
    description: str = ""
    custom_instructions: str = ""
    icon: str = ""
    files: List[TemplateFileIn] = []


class UpdateTemplateRequest(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    custom_instructions: Optional[str] = None
    icon: Optional[str] = None
    files: Optional[List[TemplateFileIn]] = None


# ── Helpers ────────────────────────────────────────────────────────────────


def _get_org_or_404(org_id: str) -> Organization:
    try:
        return Organization.objects.get(pk=org_id)
    except (Organization.DoesNotExist, ValueError):
        raise NotFoundError("Organization not found.")


def _get_template_or_404(template_id: str, org: Organization) -> ProjectTemplate:
    try:
        return ProjectTemplate.objects.get(pk=template_id, organization=org)
    except (ProjectTemplate.DoesNotExist, ValueError):
        raise NotFoundError("Template not found.")


def _validate_file_sizes(files: list[TemplateFileIn]) -> None:
    """Validate individual and total file sizes. Returns 413 on violation."""
    total = 0
    for f in files:
        size = len(f.file_content.encode("utf-8"))
        if size > MAX_FILE_SIZE:
            from ninja.errors import HttpError

            raise HttpError(
                413,
                f"File '{f.file_name}' exceeds 1 MB limit ({size} bytes).",
            )
        total += size
    if total > MAX_TOTAL_SIZE:
        from ninja.errors import HttpError

        raise HttpError(
            413,
            f"Total file size exceeds 10 MB limit ({total} bytes).",
        )


def _serialize_template(template: ProjectTemplate) -> dict:
    return {
        "id": template.pk,
        "name": template.name,
        "description": template.description,
        "custom_instructions": template.custom_instructions,
        "icon": template.icon,
        "created_by_id": str(template.created_by_id)
        if template.created_by_id
        else None,
        "created_at": template.date_created,
        "updated_at": template.date_updated,
        "files": [
            {
                "id": f.pk,
                "file_name": f.file_name,
                "file_content": f.file_content,
                "sort_order": f.sort_order,
            }
            for f in template.template_files.all()
        ],
    }


# ── CRUD endpoints ─────────────────────────────────────────────────────────


@template_api.post("/{org_id}", response={201: TemplateOut})
def create_template(request, org_id: str, body: CreateTemplateRequest):
    """Create a new project template (admin+)."""
    require_enterprise(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_SETTINGS)

    if body.files:
        _validate_file_sizes(body.files)

    with transaction.atomic():
        template = ProjectTemplate.objects.create(
            organization=org,
            name=body.name.strip(),
            description=body.description.strip(),
            custom_instructions=body.custom_instructions,
            icon=body.icon.strip(),
            created_by=request.auth,
        )
        for f in body.files:
            ProjectTemplateFile.objects.create(
                template=template,
                file_name=f.file_name,
                file_content=f.file_content,
                sort_order=f.sort_order,
            )

    return 201, _serialize_template(template)


@template_api.get("/{org_id}", response=list[TemplateOut])
def list_templates(request, org_id: str):
    """List all templates for an organization (member+)."""
    require_enterprise(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.VIEW_PROJECTS)
    templates = ProjectTemplate.objects.filter(organization=org).prefetch_related(
        "template_files"
    )
    return [_serialize_template(t) for t in templates]


@template_api.get("/{org_id}/{template_id}", response=TemplateOut)
def get_template(request, org_id: str, template_id: str):
    """Get a single template detail (member+)."""
    require_enterprise(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.VIEW_PROJECTS)
    template = _get_template_or_404(template_id, org)
    return _serialize_template(template)


@template_api.patch("/{org_id}/{template_id}", response=TemplateOut)
def update_template(
    request, org_id: str, template_id: str, body: UpdateTemplateRequest
):
    """Update a project template (admin+)."""
    require_enterprise(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_SETTINGS)
    template = _get_template_or_404(template_id, org)

    with transaction.atomic():
        if body.name is not None:
            template.name = body.name.strip()
        if body.description is not None:
            template.description = body.description.strip()
        if body.custom_instructions is not None:
            template.custom_instructions = body.custom_instructions
        if body.icon is not None:
            template.icon = body.icon.strip()
        template.save()

        if body.files is not None:
            _validate_file_sizes(body.files)
            template.template_files.all().delete()
            for f in body.files:
                ProjectTemplateFile.objects.create(
                    template=template,
                    file_name=f.file_name,
                    file_content=f.file_content,
                    sort_order=f.sort_order,
                )

    return _serialize_template(template)


@template_api.delete("/{org_id}/{template_id}", response={200: dict})
def delete_template(request, org_id: str, template_id: str):
    """Delete a project template (admin+)."""
    require_enterprise(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_SETTINGS)
    template = _get_template_or_404(template_id, org)
    template_id_str = str(template.pk)
    template.delete()
    return 200, {"id": template_id_str, "deleted": True}


# ── Create template from existing project ──────────────────────────────────


@template_api.post(
    "/{org_id}/from-project/{project_id}",
    response={201: TemplateOut},
)
def create_template_from_project(request, org_id: str, project_id: str):
    """Snapshot an existing project as a template (admin+)."""
    require_enterprise(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_SETTINGS)

    try:
        project = Project.objects.get(pk=project_id)
    except (Project.DoesNotExist, ValueError):
        raise NotFoundError("Project not found.")

    with transaction.atomic():
        template = ProjectTemplate.objects.create(
            organization=org,
            name=project.title,
            description=project.description,
            custom_instructions=project.custom_instructions,
            icon=project.icon,
            created_by=request.auth,
        )
        # Copy project files as template files (content only, no binary blobs)
        for pf in project.files.all():
            # Read text content from FileField if available; skip binary files
            content = ""
            if pf.file and pf.mime_type.startswith("text/"):
                try:
                    pf.file.open("r")
                    content = pf.file.read()
                    pf.file.close()
                except Exception:
                    content = ""
            ProjectTemplateFile.objects.create(
                template=template,
                file_name=pf.filename,
                file_content=content if isinstance(content, str) else "",
                sort_order=0,
            )

    return 201, _serialize_template(template)
