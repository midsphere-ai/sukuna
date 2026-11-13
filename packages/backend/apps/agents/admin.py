"""Django admin configuration for the agents app models."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import (
    E2bSandbox,
    UserCustomMCPConfig,
)


@admin.register(UserCustomMCPConfig)
class UserCustomMCPConfigAdmin(ModelAdmin):
    """Admin interface for managing user-defined MCP server configurations."""

    list_display = ("id", "user", "server_name", "server_type", "date_created")
    list_filter = ("server_type", "date_created")
    search_fields = ("user__email", "server_name", "description")
    readonly_fields = ("id", "date_created", "date_updated")
    ordering = ("-date_created",)
    fieldsets = (
        ("User", {"fields": ("user",)}),
        (
            "Server Configuration",
            {"fields": ("server_name", "server_type", "command", "arguments", "env")},
        ),
        (
            "Network Settings",
            {
                "fields": (
                    "url",
                    "timeout",
                    "sse_read_timeout",
                    "client_session_timeout_seconds",
                )
            },
        ),
        ("Description", {"fields": ("description",)}),
        ("Timestamps", {"fields": ("date_created", "date_updated")}),
    )


@admin.register(E2bSandbox)
class E2bSandboxAdmin(ModelAdmin):
    """Admin interface for monitoring and managing E2B sandbox instances."""

    list_display = (
        "id",
        "conversation",
        "sandbox_id",
        "sandbox_state",
        "usage_in_seconds",
        "date_created",
    )
    list_filter = ("sandbox_state", "project", "date_created")
    search_fields = ("sandbox_id", "conversation__id")
    readonly_fields = ("date_created", "date_updated")
    ordering = ("-date_created",)
    fieldsets = (
        (
            "Sandbox Info",
            {"fields": ("sandbox_id", "conversation", "sandbox_state")},
        ),
        ("Timing", {"fields": ("start_time", "end_time", "usage_in_seconds")}),
        ("Timestamps", {"fields": ("date_created", "date_updated")}),
    )
