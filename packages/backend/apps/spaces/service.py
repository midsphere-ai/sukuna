"""Service layer for project CRUD operations with caching and validation."""

import mimetypes
from functools import cached_property
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.db.models import Count, Q, QuerySet

from apps.spaces.errors import (
    CreateProjectFailedError,
    ProjectFileNotFoundError,
    ProjectFileUploadError,
    ProjectObjectNotFoundError,
    ProjectsServiceError,
    UpdateProjectFailedError,
)
from apps.spaces.models import (
    Project,
    ProjectAddon,
    ProjectFile,
    ProjectMCPConfig,
    ProjectShare,
    ProjectSkill,
    SharePermission,
)
from apps.spaces.schemas import (
    CreateProjectResult,
    ProjectAddonRemoveResult,
    ProjectFileRemoveResult,
    ProjectFileUploadResult,
    ProjectMCPConfigRemoveResult,
    ProjectRemoveResult,
    ProjectSkillRemoveResult,
    ProjectUpdationResult,
    ShareDeleteResult,
)
from config.errors.common import (
    FileProcessingError,
    InvalidInputError,
    UnauthorizedAccessError,
)
from config.services.base import BaseService


class ProjectsService(BaseService):
    """Service handling all project-related business logic, validation, and persistence."""

    SERVICE_NAME = "projects_service"
    SERVICE_VERSION = "1.0.0"

    def __init__(self, **kwargs):
        """Initialize ProjectsService with base infrastructure."""
        super().__init__(**kwargs)

    @cached_property
    def config(self):
        """Service configuration.

        Returns:
            A dict of configuration values including limits and allowed types.
        """
        return {
            "version": "1.0.0",
            "message_limit": getattr(settings, "MEMORY_MESSAGE_LIMIT", 50),
            "title_length_limit": getattr(settings, "PROJECTS_TITLE_LIMIT", 128),
            "description_length_limit": getattr(
                settings, "PROJECTS_DESCRIPTION_LIMIT", 512
            ),
            "max_file_size": getattr(
                settings, "MAX_FILE_UPLOAD_SIZE", 10 * 1024 * 1024
            ),  # 10MB
            "allowed_mime_types": getattr(
                settings,
                "ALLOWED_FILE_TYPES",
                [
                    "text/plain",
                    "application/pdf",
                    "image/jpeg",
                    "image/png",
                    "application/msword",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ],
            ),
            "cache_timeout": getattr(settings, "MEMORY_CACHE_TIMEOUT", 3600),  # 1 hour
        }

    def _map_and_log_error(self, e: Exception, context: str) -> Exception:
        """Map raw exceptions to domain-specific errors."""
        from apps.workspace.enterprise import EnterpriseDisabledError

        known_exceptions = (
            CreateProjectFailedError,
            UnauthorizedAccessError,
            InvalidInputError,
            UpdateProjectFailedError,
            ProjectObjectNotFoundError,
            ProjectFileNotFoundError,
            ProjectFileUploadError,
            FileProcessingError,
            EnterpriseDisabledError,
        )
        if isinstance(e, known_exceptions):
            self._logger.info(f"ProjectError in {context}: {e}")
            return e

        if isinstance(e, ValidationError):
            self._logger.warning(f"Validation error in {context}: {e}")
            return InvalidInputError(str(e))

        self._logger.error(f"Unexpected error in {context}: {e}", exc_info=True)
        return ProjectsServiceError(f"An unexpected error occurred: {e}")

    def _validate_project_fields(self, title: str, description: str) -> None:
        """Validate title and description fields."""
        self._validate_required_field(title, "title", str)
        self._validate_required_field(description, "description", str)

        if len(title) > self.config["title_length_limit"]:
            raise InvalidInputError(
                f"Title should not exceed {self.config['title_length_limit']} characters"
            )

        if len(description) > self.config["description_length_limit"]:
            raise InvalidInputError(
                f"Description should not exceed {self.config['description_length_limit']} characters"
            )

    def _get_project_for_user(
        self, project_id: str, user, *, require_write: bool = False
    ) -> Project:
        """Retrieve a project by ID and verify access.

        For personal projects, checks ownership then falls back to share-based access.
        For org-owned projects, checks org membership then falls back to share-based access.
        """
        project_uuid = self._validate_uuid(project_id, "Project ID")
        project_object = Project.objects.get_by_uuid(project_uuid)

        if not project_object:
            raise ProjectObjectNotFoundError("Project not found")

        # Owner always has full access
        if project_object.is_owned_by(user):
            return project_object

        # Org-owned project: check org membership
        if project_object.organization_id:
            from apps.workspace.permissions import OrgPermission, check_org_permission

            permission = (
                OrgPermission.EDIT_OWN_PROJECT
                if require_write
                else OrgPermission.VIEW_PROJECTS
            )
            try:
                check_org_permission(user, project_object.organization, permission)
                return project_object
            except UnauthorizedAccessError:
                pass  # Fall through to share check

        # Check share-based access
        share = get_effective_share(project_object, user)
        if share is not None:
            if require_write and share.permission_level == SharePermission.VIEW:
                raise UnauthorizedAccessError(
                    "User does not have write permission on this Project"
                )
            return project_object

        raise UnauthorizedAccessError(
            "User does not have permission to access this Project"
        )

    def create_project(
        self, request: WSGIRequest, title: str, description: str, **kwargs
    ) -> CreateProjectResult:
        """Create a new Project and return the Project ID.

        If ``organization_id`` is provided in kwargs, the project is created
        under that organization and the user must have CREATE_PROJECT permission.

        Args:
            request: The incoming HTTP request with authenticated user.
            title: The display title for the new project.
            description: A text description of the project.
            **kwargs: Optional fields (icon, custom_instructions, organization_id).

        Returns:
            A CreateProjectResult containing the new project's ID.

        Raises:
            InvalidInputError: If title or description validation fails.
            CreateProjectFailedError: If project creation fails.
        """
        with self._handle_service_errors():
            self._validate_project_fields(title, description)

            user = self._get_authenticated_user(request)

            # Handle optional organization assignment
            # If no org explicitly provided, use the active org context
            organization_id = kwargs.pop("organization_id", None)
            if not organization_id:
                active_org = self._get_active_org(user)
                if active_org is not None:
                    organization_id = str(active_org.pk)

            organization = None
            if organization_id:
                from apps.workspace.models import Organization
                from apps.workspace.permissions import (
                    OrgPermission,
                    check_org_permission,
                )

                try:
                    organization = Organization.objects.get(pk=organization_id)
                except (Organization.DoesNotExist, ValueError):
                    raise InvalidInputError("Organization not found.")
                check_org_permission(user, organization, OrgPermission.CREATE_PROJECT)

            # Snapshot template data before creating (read once, don't reference live)
            template_id = kwargs.pop("template_id", None)
            template_snapshot = None
            if template_id:
                from apps.spaces.models import ProjectTemplate

                try:
                    tmpl = ProjectTemplate.objects.prefetch_related(
                        "template_files",
                        "template_skills",
                        "template_mcp_configs",
                    ).get(pk=template_id)
                except (ProjectTemplate.DoesNotExist, ValueError):
                    raise InvalidInputError("Template not found.")
                template_snapshot = {
                    "custom_instructions": tmpl.custom_instructions,
                    "icon": tmpl.icon,
                    "files": [
                        {
                            "file_name": f.file_name,
                            "file_content": f.file_content,
                            "sort_order": f.sort_order,
                        }
                        for f in tmpl.template_files.all()
                    ],
                    "skills": [
                        {
                            "skill_id": str(s.skill_id),
                            "config_overrides": s.config_overrides,
                        }
                        for s in tmpl.template_skills.all()
                    ],
                    "mcp_configs": [
                        {
                            "server_name": m.server_name,
                            "server_type": m.server_type,
                            "command": m.command,
                            "arguments": m.arguments,
                            "env": m.env,
                            "url": m.url,
                            "timeout": m.timeout,
                            "description": m.description,
                        }
                        for m in tmpl.template_mcp_configs.all()
                    ],
                }
                # Apply template defaults if not explicitly provided
                if not kwargs.get("custom_instructions"):
                    kwargs["custom_instructions"] = template_snapshot[
                        "custom_instructions"
                    ]
                if not kwargs.get("icon"):
                    kwargs["icon"] = template_snapshot["icon"]

            # Pop toolkit fields before passing kwargs to create_project
            initial_skill_ids = kwargs.pop("initial_skill_ids", None) or []
            isolated_toolkit = kwargs.pop("isolated_toolkit", False)

            with transaction.atomic():
                project = Project.objects.create_project(
                    title=title,
                    description=description,
                    user=user,
                    organization=organization,
                    isolated_toolkit=isolated_toolkit,
                    **kwargs,
                )
                # Copy template files into the new project
                if template_snapshot and template_snapshot["files"]:
                    for tf in template_snapshot["files"]:
                        ProjectFile.objects.create(
                            project=project,
                            filename=tf["file_name"],
                            file_path=tf["file_name"],
                            size_bytes=len(tf["file_content"].encode("utf-8")),
                            mime_type="text/plain",
                        )
                # Copy template toolkit into the new project
                if template_snapshot:
                    for ts in template_snapshot.get("skills", []):
                        ProjectSkill.objects.create(
                            project=project,
                            skill_id=ts["skill_id"],
                            added_by=user,
                            config_overrides=ts.get("config_overrides", {}),
                        )
                    for mc in template_snapshot.get("mcp_configs", []):
                        ProjectMCPConfig.objects.create(
                            project=project, added_by=user, **mc
                        )

                # Apply initial skills from creation request
                if initial_skill_ids:
                    from apps.storage.models import SkillCatalogEntry

                    valid_skills = SkillCatalogEntry.objects.filter(
                        pk__in=[
                            self._validate_uuid(sid, "Skill ID")
                            for sid in initial_skill_ids
                        ]
                    )
                    for skill in valid_skills:
                        ProjectSkill.objects.get_or_create(
                            project=project,
                            skill=skill,
                            defaults={"added_by": user},
                        )

                self._logger.info(f"Created new project {project.id}")

            cache_key = self._get_cache_key("project", str(project.id))
            self._cache_set(cache_key, project, self.config["cache_timeout"])

            return CreateProjectResult(project_id=project.id)

    def modify_project(
        self, request: WSGIRequest, project_id: str, data
    ) -> ProjectUpdationResult:
        """Update details related to a project (partial update).

        Args:
            request: The incoming HTTP request with authenticated user.
            project_id: UUID of the project to update.
            data: ProjectUpdateSchema with optional fields to update.

        Returns:
            A ProjectUpdationResult indicating success.

        Raises:
            ProjectObjectNotFoundError: If the project does not exist.
            UnauthorizedAccessError: If the user does not own the project.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project_object = self._get_project_for_user(
                project_id, user, require_write=True
            )

            # Build update dict from non-None fields
            update_fields = {}
            for field in ("title", "description", "icon", "custom_instructions"):
                value = getattr(data, field, None)
                if value is not None:
                    update_fields[field] = value

            # Handle isolated_toolkit toggle separately (boolean field)
            isolated_toolkit = getattr(data, "isolated_toolkit", None)
            if isolated_toolkit is not None:
                project_object.isolated_toolkit = isolated_toolkit
                project_object.save(update_fields=["isolated_toolkit"])

            if not update_fields and isolated_toolkit is None:
                return ProjectUpdationResult(
                    project_id=project_object.id, modified=False
                )

            # Validate fields that are being updated
            title = update_fields.get("title", project_object.title)
            description = update_fields.get("description", project_object.description)
            self._validate_project_fields(title, description)

            with transaction.atomic():
                project_object.update_details(
                    title=title,
                    description=description,
                    **{
                        k: v
                        for k, v in update_fields.items()
                        if k not in ("title", "description")
                    },
                )
                self._logger.info(
                    f"Project object {project_object.id} has been modified."
                )

            cache_key = self._get_cache_key("project", str(project_object.id))
            self._cache_set(cache_key, project_object, self.config["cache_timeout"])
            return ProjectUpdationResult(project_id=project_object.id, modified=True)

    def delete_project(
        self, request: WSGIRequest, project_id: str
    ) -> ProjectRemoveResult:
        """Delete a project and return ProjectRemoveResult.

        Args:
            request: The incoming HTTP request with authenticated user.
            project_id: UUID of the project to delete.

        Returns:
            A ProjectRemoveResult indicating the project was deleted.

        Raises:
            ProjectObjectNotFoundError: If the project does not exist.
            UnauthorizedAccessError: If the user does not own the project.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project_object = self._get_project_for_user(
                project_id, user, require_write=True
            )

            with transaction.atomic():
                project_object.delete()
                self._logger.info(f"Project {project_id} has been deleted")

            cache_key = self._get_cache_key("project", str(project_id))
            self._cache_delete(cache_key)
            return ProjectRemoveResult(project_id=project_id, deleted=True)

    def get_project_info(
        self, request: WSGIRequest, project_id: str
    ) -> Optional[Project]:
        """Get all information related to a single project.

        Args:
            request: The incoming HTTP request with authenticated user.
            project_id: UUID of the project to retrieve.

        Returns:
            The Project object, or None if not found.

        Raises:
            ProjectObjectNotFoundError: If the project does not exist.
            UnauthorizedAccessError: If the user does not own the project.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)

            cache_key = self._get_cache_key("project", str(project_id))
            cached_project = self._cache_service.get(cache_key)
            if cached_project:
                return cached_project

            project_object = self._get_project_for_user(project_id, user)

            self._cache_set(cache_key, project_object, self.config["cache_timeout"])
            return project_object

    def _get_active_org(self, user):
        """Return the user's active organization or None (personal space)."""
        from apps.users.models import UserSettings

        settings, _ = UserSettings.objects.get_or_create(user=user)
        org = settings.last_active_org
        if org is None:
            return None
        # Verify user is still a member
        if not org.members.filter(pk=user.pk).exists():
            settings.last_active_org = None
            settings.save(update_fields=["last_active_org"])
            return None
        return org

    def get_all_user_projects(
        self, request: WSGIRequest
    ) -> Optional[QuerySet[Project]]:
        """Get projects scoped to the user's active organization context.

        When an active org is set, returns that org's projects + projects shared with the user.
        When in personal space (null), returns personal projects + projects shared with the user.

        Args:
            request: The incoming HTTP request with authenticated user.

        Returns:
            A QuerySet of Project objects annotated with conversation_count.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            active_org = self._get_active_org(user)

            # IDs of projects shared directly with this user
            shared_project_ids = ProjectShare.objects.filter(
                user=user,
            ).values_list("project_id", flat=True)

            if active_org is not None:
                # Also include projects shared with the org
                org_shared_ids = ProjectShare.objects.filter(
                    organization=active_org,
                ).values_list("project_id", flat=True)

                qs = Project.objects.filter(
                    Q(organization=active_org)
                    | Q(pk__in=shared_project_ids)
                    | Q(pk__in=org_shared_ids)
                ).distinct()
            else:
                # Personal space: own projects + projects shared with user (that aren't org-scoped)
                qs = Project.objects.filter(
                    Q(user=user, organization__isnull=True)
                    | Q(pk__in=shared_project_ids)
                ).distinct()

            projects = list(
                qs.annotate(conversation_count=Count("conversations")).order_by(
                    "-date_created"
                )
            )
            # Mark shared projects (not owned by requesting user)
            shared_set = set(shared_project_ids)
            for p in projects:
                p._is_shared = p.pk in shared_set
            return projects

    # --- File management ---

    def _validate_file(self, uploaded_file) -> None:
        """Validate an uploaded file's size and MIME type.

        Args:
            uploaded_file: The Django UploadedFile to validate.

        Raises:
            InvalidInputError: If the file exceeds size limits or has a disallowed type.
        """
        if uploaded_file.size > self.config["max_file_size"]:
            max_mb = self.config["max_file_size"] / (1024 * 1024)
            raise InvalidInputError(
                f"File size exceeds the maximum allowed size of {max_mb:.0f}MB"
            )

        mime_type = (
            uploaded_file.content_type
            or mimetypes.guess_type(uploaded_file.name)[0]
            or "application/octet-stream"
        )
        if mime_type not in self.config["allowed_mime_types"]:
            raise InvalidInputError(f"File type '{mime_type}' is not allowed")

    def upload_project_file(
        self, request: WSGIRequest, project_id: str, uploaded_file
    ) -> ProjectFileUploadResult:
        """Upload a file to a project.

        Args:
            request: The incoming HTTP request with authenticated user.
            project_id: UUID of the project to upload to.
            uploaded_file: The uploaded file object.

        Returns:
            A ProjectFileUploadResult with file metadata.

        Raises:
            ProjectObjectNotFoundError: If the project does not exist.
            UnauthorizedAccessError: If the user does not own the project.
            InvalidInputError: If the file fails validation.
            ProjectFileUploadError: If the upload fails.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)

            self._validate_file(uploaded_file)

            mime_type = (
                uploaded_file.content_type
                or mimetypes.guess_type(uploaded_file.name)[0]
                or "application/octet-stream"
            )

            with transaction.atomic():
                project_file = ProjectFile.objects.create(
                    project=project,
                    filename=uploaded_file.name,
                    file_path=f"/home/user/workspace/{uploaded_file.name}",
                    file=uploaded_file,
                    mime_type=mime_type,
                    size_bytes=uploaded_file.size,
                )
                self._logger.info(
                    f"Uploaded file {project_file.id} to project {project_id}"
                )

            return ProjectFileUploadResult(
                file_id=str(project_file.id),
                filename=project_file.filename,
                size_bytes=project_file.size_bytes,
                mime_type=project_file.mime_type,
            )

    def list_project_files(
        self, request: WSGIRequest, project_id: str
    ) -> QuerySet[ProjectFile]:
        """List all files belonging to a project.

        Args:
            request: The incoming HTTP request with authenticated user.
            project_id: UUID of the project.

        Returns:
            A QuerySet of ProjectFile objects.

        Raises:
            ProjectObjectNotFoundError: If the project does not exist.
            UnauthorizedAccessError: If the user does not own the project.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            return ProjectFile.objects.filter(project=project)

    def delete_project_file(
        self, request: WSGIRequest, project_id: str, file_id: str
    ) -> ProjectFileRemoveResult:
        """Delete a file from a project.

        Args:
            request: The incoming HTTP request with authenticated user.
            project_id: UUID of the project.
            file_id: UUID of the file to delete.

        Returns:
            A ProjectFileRemoveResult indicating success.

        Raises:
            ProjectObjectNotFoundError: If the project does not exist.
            UnauthorizedAccessError: If the user does not own the project.
            ProjectFileNotFoundError: If the file does not exist.
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)

            file_uuid = self._validate_uuid(file_id, "File ID")
            project_file = ProjectFile.objects.filter(
                id=file_uuid, project=project
            ).first()

            if not project_file:
                raise ProjectFileNotFoundError("Project file not found")

            with transaction.atomic():
                # Delete the stored file from disk
                if project_file.file:
                    project_file.file.delete(save=False)
                project_file.delete()
                self._logger.info(f"Deleted file {file_id} from project {project_id}")

            return ProjectFileRemoveResult(file_id=file_id, deleted=True)

    # --- Project move ---

    def _get_move_warnings(self, project: Project) -> list[str]:
        """Check for user-specific configs that won't transfer with the project."""
        warnings = []
        from apps.agents.models import UserCustomMCPConfig, UserProviderConfig

        if UserProviderConfig.objects.filter(user=project.user).exists():
            warnings.append(
                "This project's owner has custom BYOM provider configs that other "
                "org members won't have access to."
            )
        if UserCustomMCPConfig.objects.filter(user=project.user).exists():
            warnings.append(
                "This project's owner has custom MCP tool configs that won't "
                "transfer to the organization."
            )
        return warnings

    def move_project(self, request, project_id: str, data) -> dict:
        """Move a project to or from an organization."""
        from apps.workspace.enterprise import require_enterprise

        with self._handle_service_errors():
            require_enterprise(request)
            user = self._get_authenticated_user(request)

            project_uuid = self._validate_uuid(project_id, "Project ID")
            project = Project.objects.get_by_uuid(project_uuid)
            if not project:
                raise ProjectObjectNotFoundError("Project not found")

            # Only the project owner can move it
            if not project.is_owned_by(user):
                raise UnauthorizedAccessError(
                    "Only the project owner can move a project"
                )

            organization_id = getattr(data, "organization_id", None)

            old_org_id = (
                str(project.organization_id) if project.organization_id else None
            )
            warnings = []

            with transaction.atomic():
                if organization_id:
                    # Moving to an organization
                    from apps.workspace.models import Organization
                    from apps.workspace.permissions import (
                        OrgPermission,
                        check_org_permission,
                    )

                    try:
                        org = Organization.objects.get(pk=organization_id)
                    except (Organization.DoesNotExist, ValueError):
                        raise InvalidInputError("Organization not found")

                    # User must be admin+ in target org
                    check_org_permission(user, org, OrgPermission.EDIT_ANY_PROJECT)

                    warnings = self._get_move_warnings(project)

                    project.organization = org
                    project.save(update_fields=["organization"])

                    # Create ProjectShare for owner at admin level (idempotent)
                    ProjectShare.objects.get_or_create(
                        project=project,
                        user=user,
                        defaults={
                            "permission_level": SharePermission.ADMIN,
                            "shared_by": user,
                        },
                    )
                else:
                    # Moving back to personal — remove org FK and auto-created share
                    project.organization = None
                    project.save(update_fields=["organization"])

                    # Remove auto-created owner share (if exists)
                    ProjectShare.objects.filter(
                        project=project,
                        user=user,
                    ).delete()

            # Audit log
            from apps.compliance.models import AuditAction, AuditLog

            AuditLog.log(
                action=AuditAction.PROJECT_MOVED,
                resource_type="project",
                resource_id=str(project.pk),
                actor_id=user.pk,
                actor_email=user.email,
                metadata={
                    "source_org_id": old_org_id,
                    "destination_org_id": organization_id,
                },
            )

            # Invalidate cache
            cache_key = self._get_cache_key("project", str(project.pk))
            self._cache_delete(cache_key)

            return {
                "project_id": str(project.pk),
                "organization_id": organization_id,
                "moved": True,
                "warnings": warnings,
            }

    def bulk_move_projects(self, request, data) -> dict:
        """Move multiple projects to or from an organization in batches."""
        from apps.workspace.enterprise import require_enterprise

        with self._handle_service_errors():
            require_enterprise(request)
            user = self._get_authenticated_user(request)

            project_ids = getattr(data, "project_ids", [])
            organization_id = getattr(data, "organization_id", None)

            if not project_ids:
                raise InvalidInputError("project_ids is required")

            # Validate target org up front
            target_org = None
            if organization_id:
                from apps.workspace.models import Organization
                from apps.workspace.permissions import (
                    OrgPermission,
                    check_org_permission,
                )

                try:
                    target_org = Organization.objects.get(pk=organization_id)
                except (Organization.DoesNotExist, ValueError):
                    raise InvalidInputError("Organization not found")
                check_org_permission(user, target_org, OrgPermission.EDIT_ANY_PROJECT)

            results = []
            batch_size = 20

            for i in range(0, len(project_ids), batch_size):
                batch = project_ids[i : i + batch_size]
                try:
                    with transaction.atomic():
                        for pid in batch:
                            try:
                                project_uuid = self._validate_uuid(pid, "Project ID")
                                project = Project.objects.get_by_uuid(project_uuid)
                                if not project:
                                    results.append(
                                        {
                                            "project_id": pid,
                                            "organization_id": organization_id,
                                            "moved": False,
                                            "warnings": ["Project not found"],
                                        }
                                    )
                                    continue
                                if not project.is_owned_by(user):
                                    results.append(
                                        {
                                            "project_id": pid,
                                            "organization_id": organization_id,
                                            "moved": False,
                                            "warnings": ["Not the project owner"],
                                        }
                                    )
                                    continue

                                old_org_id = (
                                    str(project.organization_id)
                                    if project.organization_id
                                    else None
                                )
                                warnings = []

                                if target_org:
                                    warnings = self._get_move_warnings(project)
                                    project.organization = target_org
                                    project.save(update_fields=["organization"])
                                    ProjectShare.objects.get_or_create(
                                        project=project,
                                        user=user,
                                        defaults={
                                            "permission_level": SharePermission.ADMIN,
                                            "shared_by": user,
                                        },
                                    )
                                else:
                                    project.organization = None
                                    project.save(update_fields=["organization"])
                                    ProjectShare.objects.filter(
                                        project=project, user=user
                                    ).delete()

                                from apps.compliance.models import AuditAction, AuditLog

                                AuditLog.log(
                                    action=AuditAction.PROJECT_MOVED,
                                    resource_type="project",
                                    resource_id=str(project.pk),
                                    actor_id=user.pk,
                                    actor_email=user.email,
                                    metadata={
                                        "source_org_id": old_org_id,
                                        "destination_org_id": organization_id,
                                        "bulk": True,
                                    },
                                )

                                cache_key = self._get_cache_key(
                                    "project", str(project.pk)
                                )
                                self._cache_delete(cache_key)

                                results.append(
                                    {
                                        "project_id": str(project.pk),
                                        "organization_id": organization_id,
                                        "moved": True,
                                        "warnings": warnings,
                                    }
                                )
                            except Exception as e:
                                results.append(
                                    {
                                        "project_id": pid,
                                        "organization_id": organization_id,
                                        "moved": False,
                                        "warnings": [str(e)],
                                    }
                                )
                except Exception:
                    # Batch failed — mark remaining in batch as failed
                    for pid in batch:
                        if not any(r["project_id"] == pid for r in results):
                            results.append(
                                {
                                    "project_id": pid,
                                    "organization_id": organization_id,
                                    "moved": False,
                                    "warnings": ["Batch transaction failed"],
                                }
                            )

            succeeded = sum(1 for r in results if r["moved"])
            return {
                "results": results,
                "total": len(project_ids),
                "succeeded": succeeded,
                "failed": len(project_ids) - succeeded,
            }

    # --- Project sharing ---

    def _check_share_admin(self, project: Project, user) -> None:
        """Verify user is the project owner or has admin share permission."""
        if project.is_owned_by(user):
            return
        share = get_effective_share(project, user)
        if share is not None and share.permission_level == SharePermission.ADMIN:
            return
        raise UnauthorizedAccessError(
            "Only the project owner or share admins can manage shares"
        )

    def create_share(self, request, project_id: str, data) -> ProjectShare:
        """Share a project with a user or organization."""
        from apps.workspace.enterprise import require_enterprise

        with self._handle_service_errors():
            require_enterprise(request)
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            self._check_share_admin(project, user)

            user_id = getattr(data, "user_id", None)
            organization_id = getattr(data, "organization_id", None)
            permission_level = getattr(data, "permission_level", SharePermission.VIEW)

            if permission_level not in {c[0] for c in SharePermission.choices}:
                raise InvalidInputError(f"Invalid permission_level: {permission_level}")

            if not user_id and not organization_id:
                raise InvalidInputError("Either user_id or organization_id is required")
            if user_id and organization_id:
                raise InvalidInputError(
                    "Provide either user_id or organization_id, not both"
                )

            target_user = None
            target_org = None

            if user_id:
                from apps.users.models import User as UserModel

                try:
                    target_user = UserModel.objects.get(pk=user_id)
                except UserModel.DoesNotExist:
                    raise InvalidInputError("User not found")

                # Cannot share with yourself (the owner)
                if project.is_owned_by(target_user):
                    raise InvalidInputError("Cannot share a project with its owner")

                # Cross-org prevention: if project belongs to an org, target user must be in that org
                if project.organization_id:
                    if not project.organization.has_member(target_user):
                        raise InvalidInputError(
                            "Cannot share with a user outside the project's organization"
                        )

            if organization_id:
                from apps.workspace.models import Organization

                try:
                    target_org = Organization.objects.get(pk=organization_id)
                except Organization.DoesNotExist:
                    raise InvalidInputError("Organization not found")

                # Cross-org prevention
                if project.organization_id and str(project.organization_id) != str(
                    target_org.pk
                ):
                    raise InvalidInputError(
                        "Cannot share a project with a different organization"
                    )

            with transaction.atomic():
                share = ProjectShare.objects.create(
                    project=project,
                    user=target_user,
                    organization=target_org,
                    permission_level=permission_level,
                    shared_by=user,
                )

            # Audit log
            from apps.compliance.models import AuditAction, AuditLog

            AuditLog.log(
                action=AuditAction.PROJECT_SHARED,
                resource_type="project_share",
                resource_id=str(share.pk),
                actor_id=user.pk,
                actor_email=user.email,
                metadata={
                    "project_id": str(project.pk),
                    "target_user_id": str(target_user.pk) if target_user else None,
                    "target_org_id": str(target_org.pk) if target_org else None,
                    "permission_level": permission_level,
                },
            )

            return ProjectShare.objects.select_related("user", "organization").get(
                pk=share.pk
            )

    def list_shares(self, request, project_id: str) -> QuerySet:
        """List all shares for a project."""
        from apps.workspace.enterprise import require_enterprise

        with self._handle_service_errors():
            require_enterprise(request)
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            return ProjectShare.objects.filter(project=project).select_related(
                "user", "organization"
            )

    def update_share(
        self, request, project_id: str, share_id: str, data
    ) -> ProjectShare:
        """Update a share's permission level."""
        from apps.workspace.enterprise import require_enterprise

        with self._handle_service_errors():
            require_enterprise(request)
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            self._check_share_admin(project, user)

            share_uuid = self._validate_uuid(share_id, "Share ID")
            share = ProjectShare.objects.filter(pk=share_uuid, project=project).first()
            if not share:
                raise ProjectObjectNotFoundError("Share not found")

            permission_level = getattr(data, "permission_level", None)
            if permission_level not in {c[0] for c in SharePermission.choices}:
                raise InvalidInputError(f"Invalid permission_level: {permission_level}")

            old_level = share.permission_level
            share.permission_level = permission_level
            share.save(update_fields=["permission_level"])

            from apps.compliance.models import AuditAction, AuditLog

            AuditLog.log(
                action=AuditAction.PROJECT_SHARE_UPDATED,
                resource_type="project_share",
                resource_id=str(share.pk),
                actor_id=user.pk,
                actor_email=user.email,
                changes={
                    "permission_level": {"old": old_level, "new": permission_level}
                },
                metadata={"project_id": str(project.pk)},
            )

            return ProjectShare.objects.select_related("user", "organization").get(
                pk=share.pk
            )

    def delete_share(
        self, request, project_id: str, share_id: str
    ) -> ShareDeleteResult:
        """Revoke a project share."""
        from apps.workspace.enterprise import require_enterprise

        with self._handle_service_errors():
            require_enterprise(request)
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            self._check_share_admin(project, user)

            share_uuid = self._validate_uuid(share_id, "Share ID")
            share = ProjectShare.objects.filter(pk=share_uuid, project=project).first()
            if not share:
                raise ProjectObjectNotFoundError("Share not found")

            share_pk = str(share.pk)
            target_user_id = str(share.user_id) if share.user_id else None
            target_org_id = (
                str(share.organization_id) if share.organization_id else None
            )

            share.delete()

            from apps.compliance.models import AuditAction, AuditLog

            AuditLog.log(
                action=AuditAction.PROJECT_SHARE_REVOKED,
                resource_type="project_share",
                resource_id=share_pk,
                actor_id=user.pk,
                actor_email=user.email,
                metadata={
                    "project_id": str(project.pk),
                    "target_user_id": target_user_id,
                    "target_org_id": target_org_id,
                },
            )

            return ShareDeleteResult(share_id=share_pk, deleted=True)

    # --- Project toolkit management ---

    def _check_toolkit_permission(
        self, project: Project, user, *, require_admin: bool = False
    ) -> None:
        """Verify user has permission to manage toolkit items.

        collaborate level: can manage skills and addons
        admin level: required for MCP configs
        """
        if project.is_owned_by(user):
            return

        if project.organization_id:
            from apps.workspace.permissions import OrgPermission, check_org_permission

            permission = (
                OrgPermission.MANAGE_SETTINGS
                if require_admin
                else OrgPermission.EDIT_OWN_PROJECT
            )
            try:
                check_org_permission(user, project.organization, permission)
                return
            except UnauthorizedAccessError:
                pass

        share = get_effective_share(project, user)
        if share is not None:
            if require_admin and share.permission_level != SharePermission.ADMIN:
                raise UnauthorizedAccessError(
                    "Admin permission required to manage MCP configs"
                )
            if share.permission_level in (
                SharePermission.COLLABORATE,
                SharePermission.ADMIN,
            ):
                return

        raise UnauthorizedAccessError(
            "Insufficient permission to manage project toolkit"
        )

    # Skills

    def list_project_skills(self, request, project_id: str):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            return ProjectSkill.objects.filter(project=project).select_related("skill")

    def add_project_skill(self, request, project_id: str, data):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            self._check_toolkit_permission(project, user)

            skill_uuid = self._validate_uuid(data.skill_id, "Skill ID")
            from apps.storage.models import SkillCatalogEntry

            skill = SkillCatalogEntry.objects.filter(pk=skill_uuid).first()
            if not skill:
                raise InvalidInputError("Skill not found")

            if ProjectSkill.objects.filter(project=project, skill=skill).exists():
                raise InvalidInputError("Skill already added to this project")

            ps = ProjectSkill.objects.create(
                project=project,
                skill=skill,
                added_by=user,
                config_overrides=getattr(data, "config_overrides", None) or {},
            )
            return ProjectSkill.objects.select_related("skill").get(pk=ps.pk)

    def remove_project_skill(self, request, project_id: str, skill_entry_id: str):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            self._check_toolkit_permission(project, user)

            entry_uuid = self._validate_uuid(skill_entry_id, "Skill entry ID")
            ps = ProjectSkill.objects.filter(pk=entry_uuid, project=project).first()
            if not ps:
                raise ProjectObjectNotFoundError("Project skill not found")

            ps.delete()
            return ProjectSkillRemoveResult(skill_entry_id=skill_entry_id, deleted=True)

    # MCP Configs

    def list_project_mcp_configs(self, request, project_id: str):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            return ProjectMCPConfig.objects.filter(project=project)

    def create_project_mcp_config(self, request, project_id: str, data):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            self._check_toolkit_permission(project, user, require_admin=True)

            server_type = getattr(data, "server_type", "stdio")
            valid_types = [c[0] for c in ProjectMCPConfig.ServerType.choices]
            if server_type not in valid_types:
                raise InvalidInputError(f"Invalid server_type: {server_type}")

            if ProjectMCPConfig.objects.filter(
                project=project, server_name=data.server_name
            ).exists():
                raise InvalidInputError(
                    f"MCP config with name '{data.server_name}' already exists in this project"
                )

            config = ProjectMCPConfig.objects.create(
                project=project,
                server_name=data.server_name,
                server_type=server_type,
                command=getattr(data, "command", None),
                arguments=getattr(data, "arguments", "") or "",
                env=getattr(data, "env", "") or "",
                url=getattr(data, "url", None),
                timeout=getattr(data, "timeout", None),
                description=getattr(data, "description", "") or "",
                added_by=user,
            )
            return config

    def update_project_mcp_config(self, request, project_id: str, config_id: str, data):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            self._check_toolkit_permission(project, user, require_admin=True)

            config_uuid = self._validate_uuid(config_id, "MCP Config ID")
            config = ProjectMCPConfig.objects.filter(
                pk=config_uuid, project=project
            ).first()
            if not config:
                raise ProjectObjectNotFoundError("Project MCP config not found")

            updatable = (
                "server_name",
                "server_type",
                "command",
                "arguments",
                "env",
                "url",
                "timeout",
                "description",
            )
            changed = []
            for field in updatable:
                value = getattr(data, field, None)
                if value is not None:
                    setattr(config, field, value)
                    changed.append(field)

            if changed:
                changed.append("date_updated")
                config.save(update_fields=changed)
            return config

    def delete_project_mcp_config(self, request, project_id: str, config_id: str):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            self._check_toolkit_permission(project, user, require_admin=True)

            config_uuid = self._validate_uuid(config_id, "MCP Config ID")
            config = ProjectMCPConfig.objects.filter(
                pk=config_uuid, project=project
            ).first()
            if not config:
                raise ProjectObjectNotFoundError("Project MCP config not found")

            config.delete()
            return ProjectMCPConfigRemoveResult(config_id=config_id, deleted=True)

    # Addons

    def list_project_addons(self, request, project_id: str):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            return ProjectAddon.objects.filter(project=project).select_related("addon")

    def add_project_addon(self, request, project_id: str, data):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            self._check_toolkit_permission(project, user)

            addon_uuid = self._validate_uuid(data.addon_id, "Addon ID")
            from apps.storage.models import UserMarketplaceAddons

            addon = UserMarketplaceAddons.objects.filter(pk=addon_uuid).first()
            if not addon:
                raise InvalidInputError("Addon not found")

            if ProjectAddon.objects.filter(project=project, addon=addon).exists():
                raise InvalidInputError("Addon already added to this project")

            pa = ProjectAddon.objects.create(
                project=project,
                addon=addon,
                added_by=user,
                config=getattr(data, "config", None) or {},
            )
            return ProjectAddon.objects.select_related("addon").get(pk=pa.pk)

    def remove_project_addon(self, request, project_id: str, addon_entry_id: str):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            self._check_toolkit_permission(project, user)

            entry_uuid = self._validate_uuid(addon_entry_id, "Addon entry ID")
            pa = ProjectAddon.objects.filter(pk=entry_uuid, project=project).first()
            if not pa:
                raise ProjectObjectNotFoundError("Project addon not found")

            pa.delete()
            return ProjectAddonRemoveResult(addon_entry_id=addon_entry_id, deleted=True)

    # Bulk toolkit

    def get_project_toolkit(self, request, project_id: str):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user)
            return {
                "isolated_toolkit": project.isolated_toolkit,
                "skills": list(
                    ProjectSkill.objects.filter(project=project).select_related("skill")
                ),
                "mcp_configs": list(ProjectMCPConfig.objects.filter(project=project)),
                "addons": list(
                    ProjectAddon.objects.filter(project=project).select_related("addon")
                ),
            }

    def update_project_toolkit(self, request, project_id: str, data):
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            project = self._get_project_for_user(project_id, user, require_write=True)
            self._check_toolkit_permission(project, user)

            with transaction.atomic():
                if data.isolated_toolkit is not None:
                    project.isolated_toolkit = data.isolated_toolkit
                    project.save(update_fields=["isolated_toolkit"])

                if data.skill_ids is not None:
                    from apps.storage.models import SkillCatalogEntry

                    ProjectSkill.objects.filter(project=project).delete()
                    valid_uuids = [
                        self._validate_uuid(sid, "Skill ID") for sid in data.skill_ids
                    ]
                    skills = SkillCatalogEntry.objects.filter(pk__in=valid_uuids)
                    for skill in skills:
                        ProjectSkill.objects.create(
                            project=project, skill=skill, added_by=user
                        )

                if data.addon_ids is not None:
                    from apps.storage.models import UserMarketplaceAddons

                    ProjectAddon.objects.filter(project=project).delete()
                    valid_uuids = [
                        self._validate_uuid(aid, "Addon ID") for aid in data.addon_ids
                    ]
                    addons = UserMarketplaceAddons.objects.filter(pk__in=valid_uuids)
                    for addon in addons:
                        ProjectAddon.objects.create(
                            project=project, addon=addon, added_by=user
                        )

            return self.get_project_toolkit(request, project_id)


def get_effective_share(project: Project, user) -> Optional[ProjectShare]:
    """Return the most specific share for a user on a project.

    User-specific share takes precedence over org-wide share.
    Returns None if no share exists.
    """
    # Check user-specific share first (more specific wins)
    user_share = ProjectShare.objects.filter(project=project, user=user).first()
    if user_share is not None:
        return user_share

    # Check org-wide share
    if project.organization_id:
        org_share = ProjectShare.objects.filter(
            project=project, organization=project.organization
        ).first()
        if org_share is not None and project.organization.has_member(user):
            return org_share

    return None
