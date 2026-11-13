"""Signal handlers for users app."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import User, UserSettings


@receiver(post_save, sender=User)
def create_default_user_settings(
    sender, instance: User, created: bool, **kwargs
) -> None:
    """Ensure every new user has settings with onboarding marked incomplete."""
    if not created:
        return

    UserSettings.objects.get_or_create(
        user=instance,
        defaults={"onboarding_completed": False},
    )
