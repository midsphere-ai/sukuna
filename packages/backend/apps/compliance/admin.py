"""Admin configuration for the compliance app."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import AuditLog, ComplianceExportConfig, RetentionPolicy


@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    """Read-only admin interface for audit log entries."""

    list_display = (
        "timestamp",
        "action",
        "resource_type",
        "resource_id",
        "actor_email",
        "actor_ip",
    )
    list_filter = ("action", "resource_type")
    search_fields = ("actor_email", "resource_id", "request_id")
    readonly_fields = (
        "id",
        "timestamp",
        "actor_id",
        "actor_email",
        "actor_ip",
        "action",
        "resource_type",
        "resource_id",
        "request_id",
        "changes",
        "metadata",
    )
    ordering = ("-timestamp",)
    date_hierarchy = "timestamp"

    fieldsets = (
        ("Event", {"fields": ("id", "timestamp", "action")}),
        ("Actor", {"fields": ("actor_id", "actor_email", "actor_ip")}),
        ("Resource", {"fields": ("resource_type", "resource_id")}),
        ("Context", {"fields": ("request_id", "changes", "metadata")}),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RetentionPolicy)
class RetentionPolicyAdmin(ModelAdmin):
    """Admin interface for retention policy management (superuser only)."""

    list_display = (
        "resource_type",
        "retention_days",
        "action",
        "is_active",
        "last_run_at",
        "records_affected_last_run",
    )
    list_filter = ("action", "is_active")
    search_fields = ("resource_type",)
    readonly_fields = ("id", "last_run_at", "records_affected_last_run")
    ordering = ("resource_type",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "resource_type",
                    "retention_days",
                    "action",
                    "is_active",
                )
            },
        ),
        ("Last Run", {"fields": ("last_run_at", "records_affected_last_run")}),
    )

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(ComplianceExportConfig)
class ComplianceExportConfigAdmin(ModelAdmin):
    """Admin interface for compliance export configuration (superuser only)."""

    list_display = (
        "export_type",
        "destination_type",
        "schedule",
        "is_active",
        "last_export_at",
        "last_export_record_count",
    )
    list_filter = ("export_type", "destination_type", "schedule", "is_active")
    search_fields = ("export_type",)
    readonly_fields = ("id", "created_at", "last_export_at", "last_export_record_count")
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("id", "organization", "export_type", "format", "schedule")}),
        ("Destination", {"fields": ("destination_type", "destination_config")}),
        (
            "Status",
            {
                "fields": (
                    "is_active",
                    "created_at",
                    "last_export_at",
                    "last_export_record_count",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
