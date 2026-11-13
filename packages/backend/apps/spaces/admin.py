"""Django admin configuration for the spaces app."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Project, ProjectAddon, ProjectFile, ProjectMCPConfig, ProjectSkill


@admin.register(Project)
class ProjectAdmin(ModelAdmin):
    """Admin interface for managing Project objects via Django Unfold."""

    list_display = ("id", "title", "user", "date_created")
    list_filter = ("user", "date_created")
    search_fields = ("title", "description", "user__email")
    readonly_fields = ("id", "date_created")
    ordering = ("-date_created",)
    fieldsets = (
        (
            "Project Details",
            {
                "fields": (
                    "title",
                    "description",
                    "icon",
                    "custom_instructions",
                    "user",
                    "sandbox",
                )
            },
        ),
        ("Timestamps", {"fields": ("date_created",)}),
    )


@admin.register(ProjectFile)
class ProjectFileAdmin(ModelAdmin):
    """Admin interface for managing ProjectFile objects via Django Unfold."""

    list_display = ("id", "filename", "project", "size_bytes", "date_created")
    list_filter = ("date_created",)
    search_fields = ("filename", "project__title")
    readonly_fields = ("id", "date_created")
    ordering = ("-date_created",)


@admin.register(ProjectSkill)
class ProjectSkillAdmin(ModelAdmin):
    """Admin interface for project-level skill installations."""

    list_display = ("id", "project", "skill", "date_created")
    list_filter = ("date_created",)
    search_fields = ("project__title", "skill__name", "skill__slug")
    readonly_fields = ("id", "date_created")
    ordering = ("-date_created",)


@admin.register(ProjectMCPConfig)
class ProjectMCPConfigAdmin(ModelAdmin):
    """Admin interface for project-level MCP server configurations."""

    list_display = ("id", "project", "server_name", "server_type", "date_created")
    list_filter = ("server_type", "date_created")
    search_fields = ("project__title", "server_name", "description")
    readonly_fields = ("id", "date_created")
    ordering = ("-date_created",)


@admin.register(ProjectAddon)
class ProjectAddonAdmin(ModelAdmin):
    """Admin interface for project-level addon installations."""

    list_display = ("id", "project", "addon", "date_created")
    list_filter = ("date_created",)
    search_fields = ("project__title",)
    readonly_fields = ("id", "date_created")
    ordering = ("-date_created",)
