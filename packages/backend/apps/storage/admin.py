"""Django admin configuration for the storage app models."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import (
    AgentRun,
    Conversation,
    ConversationComposioAddon,
    ConversationFile,
    MarketplaceAddon,
    StoredFile,
    SystemWideMemory,
    UserMarketplaceAddons,
)


@admin.register(MarketplaceAddon)
class MarketplaceAddonAdmin(ModelAdmin):
    """Admin interface for managing marketplace addons."""

    list_display = ("id", "name", "enum", "date_created")
    list_filter = ("date_created",)
    search_fields = ("name", "description", "enum")
    readonly_fields = ("id", "date_created")
    ordering = ("-date_created",)
    fieldsets = (
        ("Addon Details", {"fields": ("name", "description", "link", "logo", "enum")}),
        ("Timestamps", {"fields": ("date_created",)}),
    )


@admin.register(UserMarketplaceAddons)
class UserMarketplaceAddonsAdmin(ModelAdmin):
    """Admin interface for managing user-registered marketplace addons."""

    list_display = ("id", "owner", "enabled_addon", "auth_complete", "date_created")
    list_filter = ("auth_complete", "date_created")
    search_fields = ("owner__email", "enabled_addon__name", "config_id", "server_id")
    readonly_fields = ("id", "date_created")
    ordering = ("-date_created",)
    fieldsets = (
        ("User & Addon", {"fields": ("owner", "enabled_addon")}),
        ("Authentication", {"fields": ("auth_complete", "auth_link")}),
        ("Configuration", {"fields": ("config_id", "server_id")}),
        ("Timestamps", {"fields": ("date_created",)}),
    )


@admin.register(StoredFile)
class StoredFileAdmin(ModelAdmin):
    """Admin interface for managing uploaded files."""

    list_display = ("id", "name", "owner", "size", "mime_type", "uploaded_at")
    list_filter = ("mime_type", "uploaded_at")
    search_fields = ("name", "owner__email", "mime_type")
    readonly_fields = ("id", "uploaded_at", "updated_at")
    ordering = ("-uploaded_at",)
    fieldsets = (
        ("File Details", {"fields": ("name", "file", "size", "mime_type")}),
        ("Owner", {"fields": ("owner",)}),
        ("Timestamps", {"fields": ("uploaded_at", "updated_at")}),
    )


@admin.register(Conversation)
class ConversationAdmin(ModelAdmin):
    """Admin interface for managing conversations with derived status display."""

    list_display = (
        "id",
        "title",
        "user",
        "display_is_ongoing",
        "display_has_error",
        "requires_user_input",
        "date_created",
    )
    list_filter = (
        "requires_user_input",
        "date_created",
    )
    search_fields = ("title", "user__email", "summary")
    readonly_fields = ("id", "date_created")
    ordering = ("-date_created",)
    fieldsets = (
        ("Conversation Details", {"fields": ("title", "user", "project", "summary")}),
        (
            "Status",
            {"fields": ("requires_user_input",)},
        ),
        ("Current Task", {"fields": ("current_task",)}),
        ("Metadata", {"fields": ("metadata",)}),
        ("Timestamps", {"fields": ("date_created",)}),
    )

    def display_is_ongoing(self, obj):
        """Return whether the conversation has an active agent run.

        Args:
            obj: The Conversation instance.

        Returns:
            bool: True if the conversation's current task is in an active state.
        """
        return obj.get_is_ongoing()

    display_is_ongoing.boolean = True
    display_is_ongoing.short_description = "Ongoing"

    def display_has_error(self, obj):
        """Return whether the conversation's current task has failed.

        Args:
            obj: The Conversation instance.

        Returns:
            bool: True if the conversation's current task status is 'failed'.
        """
        return obj.get_has_error()

    display_has_error.boolean = True
    display_has_error.short_description = "Has Error"


@admin.register(AgentRun)
class AgentRunAdmin(ModelAdmin):
    """Admin interface for managing agent run records."""

    list_display = (
        "id",
        "run_id",
        "conversation",
        "user",
        "status",
        "model",
        "created_at",
    )
    list_filter = ("status", "conversation__project", "created_at")
    search_fields = ("id", "run_id", "conversation__title", "user__email")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-created_at",)
    fieldsets = (
        ("Run Details", {"fields": ("id", "run_id", "conversation", "user", "task")}),
        ("Status", {"fields": ("status", "model", "error", "sandbox_id")}),
        ("Metadata", {"fields": ("metadata",)}),
        (
            "Timestamps",
            {"fields": ("created_at", "started_at", "finished_at", "updated_at")},
        ),
    )


@admin.register(ConversationFile)
class ConversationFileAdmin(ModelAdmin):
    """Admin interface for conversation-file associations."""

    list_display = ("id", "conversation", "stored_file")
    search_fields = ("conversation__title", "stored_file__name")
    ordering = ("-id",)


@admin.register(ConversationComposioAddon)
class ConversationComposioAddonAdmin(ModelAdmin):
    """Admin interface for conversation-addon associations."""

    list_display = ("id", "conversation", "addon")
    search_fields = ("conversation__title", "addon__enabled_addon__name")
    ordering = ("-id",)


@admin.register(SystemWideMemory)
class SystemWideMemoryAdmin(ModelAdmin):
    """Admin interface for system-wide memory records."""

    list_display = ("id", "user", "date_created")
    list_filter = ("date_created",)
    search_fields = ("user__email", "memory_summary")
    readonly_fields = ("date_created",)
    ordering = ("-date_created",)
    fieldsets = (
        ("Memory Details", {"fields": ("user", "memory_summary")}),
        ("Timestamps", {"fields": ("date_created",)}),
    )
