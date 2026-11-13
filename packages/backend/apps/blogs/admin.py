"""Django admin configuration for the blogs app models."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Announcements, ChangeLog, ChangelogEntry, PlanFooter, TutorialBlog


@admin.register(ChangeLog)
class ChangeLogAdmin(ModelAdmin):
    """Admin interface for managing ChangeLog entries."""

    list_display = ("markdownText", "date_created")
    list_filter = ("date_created",)
    search_fields = ("markdownText",)
    readonly_fields = ("id", "date_created")
    fieldsets = (("Change Log Details", {"fields": ("markdownText", "date_created")}),)


@admin.register(Announcements)
class AnnouncementsAdmin(ModelAdmin):
    """Admin interface for managing Announcements."""

    list_display = ("text", "date_created")
    list_filter = ("date_created",)
    search_fields = ("text",)
    readonly_fields = ("id", "date_created")
    fieldsets = (("Announcement Details", {"fields": ("text", "date_created")}),)


@admin.register(TutorialBlog)
class TutorialBlogAdmin(ModelAdmin):
    """Admin interface for managing TutorialBlog posts."""

    list_display = ("title", "date_created", "as_info_button")
    list_filter = ("date_created", "as_info_button")
    search_fields = ("title", "subtitle", "markdownText")
    ordering = ("-date_created",)
    readonly_fields = ("date_created",)
    fieldsets = (
        ("Content", {"fields": ("title", "subtitle", "markdownText", "image")}),
        ("Settings", {"fields": ("as_info_button",)}),
        ("Metadata", {"fields": ("date_created",)}),
    )


@admin.register(PlanFooter)
class PlanFooterAdmin(ModelAdmin):
    """Admin interface for managing PlanFooter content."""

    list_display = ("markdownText", "date_created")
    list_filter = ("date_created",)
    search_fields = ("markdownText",)
    readonly_fields = ("id", "date_created")
    fieldsets = (("Plan Footer Details", {"fields": ("markdownText", "date_created")}),)


@admin.register(ChangelogEntry)
class ChangelogEntryAdmin(ModelAdmin):
    """Admin interface for managing ChangelogEntry records."""

    list_display = ("title", "category", "is_published", "date")
    list_filter = ("category", "is_published", "date")
    search_fields = ("title", "body")
    ordering = ("-date",)
    readonly_fields = ("id", "date")
    fieldsets = (
        ("Content", {"fields": ("title", "body", "category")}),
        ("Publishing", {"fields": ("is_published",)}),
        ("Metadata", {"fields": ("date",)}),
    )
