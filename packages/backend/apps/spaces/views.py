"""Django Ninja API views for project CRUD and file management operations."""

import logging
from typing import List

from django.core.handlers.wsgi import WSGIRequest
from ninja import File, NinjaAPI, Schema
from ninja.files import UploadedFile as NinjaUploadedFile
from ninja.pagination import PageNumberPagination, paginate

from apps.spaces.factory import (
    get_projects_service,
)
from apps.spaces.schemas import (
    BulkMoveProjectRequest,
    BulkMoveProjectResult,
    CreateProjectResult,
    CreateShareRequest,
    MoveProjectRequest,
    MoveProjectResult,
    ProjectAddonAddRequest,
    ProjectAddonOut,
    ProjectAddonRemoveResult,
    ProjectDataSchema,
    ProjectDetailSchema,
    ProjectFileRemoveResult,
    ProjectFileSchema,
    ProjectFileUploadResult,
    ProjectListSchema,
    ProjectMCPConfigCreateRequest,
    ProjectMCPConfigOut,
    ProjectMCPConfigRemoveResult,
    ProjectMCPConfigUpdateRequest,
    ProjectRemoveResult,
    ProjectSandboxStatusSchema,
    ProjectShareOut,
    # Toolkit schemas
    ProjectSkillAddRequest,
    ProjectSkillOut,
    ProjectSkillRemoveResult,
    ProjectToolkitOut,
    ProjectToolkitUpdateRequest,
    ProjectUpdateSchema,
    ProjectUpdationResult,
    ShareDeleteResult,
    UpdateShareRequest,
)
from apps.users.adapters import NinjaAuthAdapter
from config.errors.handlers import register_error_handlers

logger = logging.getLogger(__name__)

app_name = "spaces"
spaces_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="spaces")

register_error_handlers(spaces_api)


@spaces_api.post("/projects", response=CreateProjectResult)
def create_project(request: WSGIRequest, data: ProjectDataSchema):
    """Create a new project for the authenticated user or within an organization."""
    projects = get_projects_service()
    return projects.create_project(
        request=request,
        title=data.title,
        description=data.description,
        icon=data.icon,
        custom_instructions=data.custom_instructions,
        organization_id=data.organization_id,
        template_id=getattr(data, "template_id", None),
        initial_skill_ids=data.initial_skill_ids,
        isolated_toolkit=data.isolated_toolkit,
    )


@spaces_api.post("/projects/bulk-move", response={200: BulkMoveProjectResult})
def bulk_move_projects(request: WSGIRequest, data: BulkMoveProjectRequest):
    """Move multiple projects to or from an organization."""
    projects = get_projects_service()
    return projects.bulk_move_projects(request=request, data=data)


@spaces_api.patch("/projects/{project_id}", response=ProjectUpdationResult)
def modify_project(request: WSGIRequest, project_id: str, data: ProjectUpdateSchema):
    """Update an existing project's details (partial update)."""
    projects = get_projects_service()
    return projects.modify_project(
        request=request,
        project_id=project_id,
        data=data,
    )


@spaces_api.delete("/projects/{project_id}", response=ProjectRemoveResult)
def delete_project(request: WSGIRequest, project_id: str):
    """Delete a project by its ID."""
    projects = get_projects_service()
    return projects.delete_project(request=request, project_id=project_id)


@spaces_api.get("/projects/{project_id}", response=ProjectDetailSchema)
def get_project_info(request: WSGIRequest, project_id: str):
    """Retrieve details for a single project with its conversations."""
    projects = get_projects_service()
    return projects.get_project_info(request=request, project_id=project_id)


@spaces_api.get("/projects", response=List[ProjectListSchema])
@paginate(PageNumberPagination, page_size=500)
def get_all_user_projects(request):
    """List all projects owned by the authenticated user with conversation counts."""
    projects = get_projects_service()
    return projects.get_all_user_projects(request=request)


# --- Project file management endpoints ---


@spaces_api.post("/projects/{project_id}/files", response=ProjectFileUploadResult)
def upload_project_file(
    request: WSGIRequest,
    project_id: str,
    file: NinjaUploadedFile = File(...),
):
    """Upload a file to a project for preloading into its sandbox."""
    projects = get_projects_service()
    return projects.upload_project_file(
        request=request, project_id=project_id, uploaded_file=file
    )


@spaces_api.get("/projects/{project_id}/files", response=List[ProjectFileSchema])
def list_project_files(request: WSGIRequest, project_id: str):
    """List all files belonging to a project."""
    projects = get_projects_service()
    return projects.list_project_files(request=request, project_id=project_id)


@spaces_api.delete(
    "/projects/{project_id}/files/{file_id}",
    response=ProjectFileRemoveResult,
)
def delete_project_file(request: WSGIRequest, project_id: str, file_id: str):
    """Delete a file from a project."""
    projects = get_projects_service()
    return projects.delete_project_file(
        request=request, project_id=project_id, file_id=file_id
    )


@spaces_api.get(
    "/projects/{project_id}/sandbox-status",
    response=ProjectSandboxStatusSchema,
)
def get_project_sandbox_status(request: WSGIRequest, project_id: str):
    """Check if the project's shared sandbox is busy with another conversation.

    Returns which conversation (if any) currently has an active agent run
    using the project's sandbox.
    """
    from apps.spaces.models import Project
    from apps.storage.models import Conversation

    project = Project.objects.get_by_uuid(project_id)
    if not project:
        from ninja.errors import HttpError

        raise HttpError(404, "Project not found")

    # Check access: personal ownership or org membership
    if project.organization_id:
        from apps.workspace.permissions import OrgPermission, check_org_permission

        check_org_permission(
            request.auth, project.organization, OrgPermission.VIEW_PROJECTS
        )
    elif not project.is_owned_by(request.auth):
        from ninja.errors import HttpError as HttpErr

        raise HttpErr(404, "Project not found")

    # Find any conversation in this project with an active run
    active_statuses = ("pending", "queued", "provisioning", "running")
    busy_conversation = (
        Conversation.objects.filter(
            project=project,
            current_task__isnull=False,
            current_task__status__in=active_statuses,
        )
        .select_related("current_task")
        .first()
    )

    if busy_conversation:
        return {
            "busy": True,
            "active_conversation_id": str(busy_conversation.id),
            "active_conversation_title": busy_conversation.title or "Untitled",
        }

    return {
        "busy": False,
        "active_conversation_id": None,
        "active_conversation_title": None,
    }


# --- Project move endpoints ---


@spaces_api.post("/projects/{project_id}/move", response={200: MoveProjectResult})
def move_project(request: WSGIRequest, project_id: str, data: MoveProjectRequest):
    """Move a project to or from an organization."""
    projects = get_projects_service()
    return projects.move_project(request=request, project_id=project_id, data=data)


# --- Project sharing endpoints ---


@spaces_api.post("/projects/{project_id}/shares", response=ProjectShareOut)
def create_share(request: WSGIRequest, project_id: str, data: CreateShareRequest):
    """Share a project with a user or organization."""
    projects = get_projects_service()
    return projects.create_share(request=request, project_id=project_id, data=data)


@spaces_api.get("/projects/{project_id}/shares", response=List[ProjectShareOut])
def list_shares(request: WSGIRequest, project_id: str):
    """List all shares for a project."""
    projects = get_projects_service()
    return projects.list_shares(request=request, project_id=project_id)


@spaces_api.patch("/projects/{project_id}/shares/{share_id}", response=ProjectShareOut)
def update_share(
    request: WSGIRequest, project_id: str, share_id: str, data: UpdateShareRequest
):
    """Update a share's permission level."""
    projects = get_projects_service()
    return projects.update_share(
        request=request, project_id=project_id, share_id=share_id, data=data
    )


@spaces_api.delete(
    "/projects/{project_id}/shares/{share_id}", response=ShareDeleteResult
)
def delete_share(request: WSGIRequest, project_id: str, share_id: str):
    """Revoke a project share."""
    projects = get_projects_service()
    return projects.delete_share(
        request=request, project_id=project_id, share_id=share_id
    )


# ── Project Budget ───────────────────────────────────────────────────────────


class UpdateProjectBudgetRequest(Schema):
    monthly_credit_limit: int | None = None
    alert_threshold_percent: int | None = None


class ProjectBudgetOut(Schema):
    project_id: str
    monthly_credit_limit: int | None = None
    alert_threshold_percent: int = 80
    current_month_usage: int = 0


@spaces_api.patch(
    "/projects/{project_id}/budget",
    response={200: ProjectBudgetOut, 403: dict, 404: dict},
)
def update_project_budget(
    request: WSGIRequest, project_id: str, data: UpdateProjectBudgetRequest
):
    """Set or update a project's monthly credit budget. Requires admin role in the project's org."""
    from apps.spaces.models import Project, ProjectBudget
    from apps.workspace.enterprise import require_enterprise
    from apps.workspace.permissions import OrgPermission, check_org_permission

    require_enterprise(request)
    user = request.auth

    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return 404, {"detail": "Project not found"}

    if not project.organization_id:
        return 403, {
            "detail": "Project budgets are only available for org-scoped projects"
        }

    check_org_permission(user, project.organization, OrgPermission.MANAGE_SETTINGS)

    budget, _ = ProjectBudget.objects.get_or_create(project=project)

    if data.monthly_credit_limit is not None:
        budget.monthly_credit_limit = data.monthly_credit_limit or None
    if data.alert_threshold_percent is not None:
        budget.alert_threshold_percent = data.alert_threshold_percent
    budget.save()

    return 200, {
        "project_id": str(project.id),
        "monthly_credit_limit": budget.monthly_credit_limit,
        "alert_threshold_percent": budget.alert_threshold_percent,
        "current_month_usage": budget.current_month_usage,
    }


# ── Project Toolkit ─────────────────────────────────────────────────────────


# --- Skills ---


@spaces_api.get("/projects/{project_id}/skills", response=List[ProjectSkillOut])
def list_project_skills(request: WSGIRequest, project_id: str):
    """List all skills attached to a project."""
    projects = get_projects_service()
    return projects.list_project_skills(request=request, project_id=project_id)


@spaces_api.post("/projects/{project_id}/skills", response={201: ProjectSkillOut})
def add_project_skill(
    request: WSGIRequest, project_id: str, data: ProjectSkillAddRequest
):
    """Add a skill to a project. Requires collaborate permission."""
    projects = get_projects_service()
    return 201, projects.add_project_skill(
        request=request, project_id=project_id, data=data
    )


@spaces_api.delete(
    "/projects/{project_id}/skills/{skill_entry_id}",
    response=ProjectSkillRemoveResult,
)
def remove_project_skill(request: WSGIRequest, project_id: str, skill_entry_id: str):
    """Remove a skill from a project. Requires collaborate permission."""
    projects = get_projects_service()
    return projects.remove_project_skill(
        request=request, project_id=project_id, skill_entry_id=skill_entry_id
    )


# --- MCP Configs ---


@spaces_api.get(
    "/projects/{project_id}/mcp-configs", response=List[ProjectMCPConfigOut]
)
def list_project_mcp_configs(request: WSGIRequest, project_id: str):
    """List all MCP configs for a project."""
    projects = get_projects_service()
    return projects.list_project_mcp_configs(request=request, project_id=project_id)


@spaces_api.post(
    "/projects/{project_id}/mcp-configs", response={201: ProjectMCPConfigOut}
)
def create_project_mcp_config(
    request: WSGIRequest, project_id: str, data: ProjectMCPConfigCreateRequest
):
    """Create a project MCP config. Requires admin permission."""
    projects = get_projects_service()
    return 201, projects.create_project_mcp_config(
        request=request, project_id=project_id, data=data
    )


@spaces_api.patch(
    "/projects/{project_id}/mcp-configs/{config_id}",
    response=ProjectMCPConfigOut,
)
def update_project_mcp_config(
    request: WSGIRequest,
    project_id: str,
    config_id: str,
    data: ProjectMCPConfigUpdateRequest,
):
    """Update a project MCP config. Requires admin permission."""
    projects = get_projects_service()
    return projects.update_project_mcp_config(
        request=request, project_id=project_id, config_id=config_id, data=data
    )


@spaces_api.delete(
    "/projects/{project_id}/mcp-configs/{config_id}",
    response=ProjectMCPConfigRemoveResult,
)
def delete_project_mcp_config(request: WSGIRequest, project_id: str, config_id: str):
    """Delete a project MCP config. Requires admin permission."""
    projects = get_projects_service()
    return projects.delete_project_mcp_config(
        request=request, project_id=project_id, config_id=config_id
    )


# --- Addons ---


@spaces_api.get("/projects/{project_id}/addons", response=List[ProjectAddonOut])
def list_project_addons(request: WSGIRequest, project_id: str):
    """List all addons attached to a project."""
    projects = get_projects_service()
    return projects.list_project_addons(request=request, project_id=project_id)


@spaces_api.post("/projects/{project_id}/addons", response={201: ProjectAddonOut})
def add_project_addon(
    request: WSGIRequest, project_id: str, data: ProjectAddonAddRequest
):
    """Add an addon to a project. Requires collaborate permission."""
    projects = get_projects_service()
    return 201, projects.add_project_addon(
        request=request, project_id=project_id, data=data
    )


@spaces_api.delete(
    "/projects/{project_id}/addons/{addon_entry_id}",
    response=ProjectAddonRemoveResult,
)
def remove_project_addon(request: WSGIRequest, project_id: str, addon_entry_id: str):
    """Remove an addon from a project. Requires collaborate permission."""
    projects = get_projects_service()
    return projects.remove_project_addon(
        request=request, project_id=project_id, addon_entry_id=addon_entry_id
    )


# --- Bulk Toolkit ---


@spaces_api.get("/projects/{project_id}/toolkit", response=ProjectToolkitOut)
def get_project_toolkit(request: WSGIRequest, project_id: str):
    """Get the complete toolkit configuration for a project."""
    projects = get_projects_service()
    return projects.get_project_toolkit(request=request, project_id=project_id)


@spaces_api.put("/projects/{project_id}/toolkit", response=ProjectToolkitOut)
def update_project_toolkit(
    request: WSGIRequest, project_id: str, data: ProjectToolkitUpdateRequest
):
    """Bulk update the project toolkit. Replaces skill/addon sets."""
    projects = get_projects_service()
    return projects.update_project_toolkit(
        request=request, project_id=project_id, data=data
    )
