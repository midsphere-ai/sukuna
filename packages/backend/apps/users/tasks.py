"""Celery tasks for the users app."""

from celery import shared_task

from .models import User


@shared_task()
def get_users_count():
    """Return the total number of registered users.

    Returns:
        The integer count of User records in the database.
    """
    return User.objects.count()
