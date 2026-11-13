"""Database models for the blogs app, including changelogs, announcements, and tutorials."""

import os
import uuid

from django.conf import settings
from django.db import models


class CMSFilePaths:
    """Utility class for generating file upload paths for CMS media."""

    def __init__(self) -> None:
        self.VERSION = 1.0
        self.BUILD = settings.BUILD

    @staticmethod
    def blog_image_path(instance, filename):
        """Generate upload path for blog images.

        Args:
            instance: The model instance the file is attached to.
            filename: The original filename of the uploaded file.

        Returns:
            str: The file path under the instance's title directory.
        """
        return os.path.join(f"{instance.title}/image.jpeg")


class ChangeLog(models.Model):
    """Stores change log entries as markdown text, ordered by creation date."""

    id = models.UUIDField(
        editable=False, default=uuid.uuid4, unique=True, primary_key=True
    )
    markdownText = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.markdownText

    class Meta:
        verbose_name = "Change Log"
        verbose_name_plural = "Change Logs"


class Announcements(models.Model):
    """Stores platform announcements displayed to users."""

    id = models.UUIDField(
        editable=False, default=uuid.uuid4, unique=True, primary_key=True
    )
    text = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.text

    class Meta:
        verbose_name = "Announcement"
        verbose_name_plural = "Announcements"


class TutorialBlog(models.Model):
    """Stores tutorial and blog content with optional image and info-button display."""

    id = models.UUIDField(
        editable=False, default=uuid.uuid4, unique=True, primary_key=True
    )
    title = models.TextField()
    subtitle = models.TextField(default="", blank=True, null=True)
    image = models.FileField(
        upload_to=CMSFilePaths.blog_image_path, default="", blank=True, null=True
    )
    markdownText = models.TextField()
    as_info_button = models.BooleanField(default=False)
    date_created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "Blog"
        verbose_name_plural = "Blogs"


class PlanFooter(models.Model):
    """Stores markdown content displayed in the plan footer section."""

    id = models.UUIDField(
        editable=False, default=uuid.uuid4, unique=True, primary_key=True
    )
    markdownText = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.markdownText

    class Meta:
        verbose_name = "Plan Footer"
        verbose_name_plural = "Plan Footers"


class ChangelogEntry(models.Model):
    """Stores categorized changelog entries with publish status, ordered by date."""

    CATEGORY_CHOICES = [
        ("feature", "Feature"),
        ("fix", "Fix"),
        ("improvement", "Improvement"),
        ("announcement", "Announcement"),
    ]

    id = models.UUIDField(
        editable=False, default=uuid.uuid4, unique=True, primary_key=True
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    date = models.DateTimeField(auto_now_add=True)
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="announcement"
    )
    is_published = models.BooleanField(default=False)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "Changelog Entry"
        verbose_name_plural = "Changelog Entries"
        ordering = ["-date"]
