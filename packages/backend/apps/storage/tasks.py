"""Celery tasks for periodic storage maintenance and addon authorization checks."""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.storage.models import Conversation, UserMarketplaceAddons

logger = logging.getLogger(__name__)


@shared_task
def expire_auth_links():
    """
    Expire authentication links that are older than 6 hours and incomplete.
    """
    threshold = timezone.now() - timedelta(hours=6)

    # Filter for addons with auth_link set, auth not complete, and created before threshold
    expired_count = UserMarketplaceAddons.objects.filter(
        auth_complete=False, auth_link__isnull=False, date_created__lt=threshold
    ).update(auth_link=None)

    return f"Expired {expired_count} auth links"


@shared_task
def check_pending_addon_authorizations():
    """
    Check pending addon authorizations and update their status.

    This task polls Composio's API for all addons with pending authorizations
    (auth_complete=False, config_id not null) and updates them if they become active.

    Should be scheduled to run periodically (e.g., every 30 seconds to 1 minute)
    to provide near real-time auth status updates.
    """
    from apps.storage.factory.addons import get_addon_service

    # Get all users with pending authorizations
    pending_addons = (
        UserMarketplaceAddons.objects.filter(
            auth_complete=False, config_id__isnull=False
        )
        .values_list("owner_id", flat=True)
        .distinct()
    )

    user_ids = list(pending_addons)
    if not user_ids:
        return "No pending authorizations to check"

    total_updated = 0
    total_checked = 0
    service = get_addon_service()

    for user_id in user_ids:
        try:
            results = service.check_and_update_pending_authorizations(user_id)
            total_checked += len(results)
            total_updated += sum(1 for r in results if r.get("updated"))
        except Exception as e:
            logger.warning(
                f"Failed to check pending authorizations for user {user_id}: {e}"
            )

    return f"Checked {total_checked} addons across {len(user_ids)} users, updated {total_updated}"


@shared_task
def check_single_addon_authorization(user_addon_id: str):
    """
    Check and update authorization status for a single addon.

    This task can be scheduled to run after a user initiates OAuth flow
    to poll for completion more frequently for that specific addon.

    Args:
        user_addon_id: The user addon ID to check
    """
    from django.db import transaction

    from apps.storage.factory.addons import get_addon_service

    try:
        service = get_addon_service()
        addon = service._get_user_addon_object(user_addon_id)

        if addon is None:
            return f"Addon {user_addon_id} not found"

        if addon.auth_complete:
            return f"Addon {user_addon_id} already authorized"

        if not addon.config_id:
            return f"Addon {user_addon_id} has no config_id (auth not initiated)"

        is_active, connection_status = service._check_connection_status(addon.config_id)

        if is_active:
            with transaction.atomic():
                addon.auth_complete = True
                addon.save()
                logger.info(f"Updated addon {user_addon_id} to auth_complete=True")

        return f"Addon {user_addon_id}: status={connection_status}, updated={is_active}"
    except Exception as e:
        logger.error(f"Failed to check addon {user_addon_id}: {e}")
        return f"Error checking addon {user_addon_id}: {e}"


@shared_task
def purge_empty_conversations():
    """Purge conversations with no runs that are older than 15 minutes."""
    try:
        cutoff_time = timezone.now() - timedelta(minutes=15)

        empty_conversations = Conversation.objects.filter(
            date_created__lt=cutoff_time, runs__isnull=True
        )

        count = empty_conversations.count()
        empty_conversations.delete()

        logger.info(f"Successfully purged {count} empty conversations")
        return {"purged_count": count}

    except Exception as e:
        logger.error(f"Error purging empty conversations: {str(e)}")
        raise


@shared_task
def set_title_conversations():
    """Set titles for conversations that have runs but no title yet.

    Derives the title from the first run's task prompt, truncated to 120 chars.
    """
    from apps.storage.models import AgentRun

    try:
        cutoff_time = timezone.now() - timedelta(minutes=15)

        conversations = list(
            Conversation.objects.filter(
                date_created__lt=cutoff_time,
                runs__isnull=False,
                title="",
            ).distinct()
        )

        updated = 0
        for conversation in conversations:
            try:
                first_run = (
                    AgentRun.objects.filter(conversation=conversation)
                    .order_by("created_at")
                    .values_list("task", flat=True)
                    .first()
                )
                if first_run:
                    # Use first line, truncated
                    title = first_run.split("\n", 1)[0].strip()
                    if len(title) > 120:
                        title = title[:117] + "..."
                    if title:
                        conversation.title = title
                        conversation.save(update_fields=["title", "date_updated"])
                        updated += 1
            except Exception as e:
                logger.error(f"Error setting title for {conversation.id}: {e}")

        logger.info(f"Successfully set titles for {updated} conversations")
        return {"updated": updated, "checked": len(conversations)}

    except Exception as e:
        logger.error(f"Error setting conversation titles: {str(e)}")
        raise
