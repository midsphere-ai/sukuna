"""Sukuna project configuration package. Ensures Celery app is loaded on Django startup."""

# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
from .celery import app as celery_app

__all__ = ("celery_app",)
