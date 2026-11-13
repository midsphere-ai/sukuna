"""
Django signals for conversation model changes.

Note: Real-time updates are now handled via SSE polling (see views.py).
The SSE endpoint polls the database directly, so WebSocket broadcasting
has been removed. These signal handlers are kept for logging/debugging
and can be used for future caching or other side-effects if needed.
"""

import logging

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from apps.storage.models import Conversation, ConversationParticipant, ParticipantRole

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Conversation)
def on_conversation_saved(sender, instance: Conversation, created: bool, **kwargs):
    """
    Signal handler for when a conversation is saved.

    Auto-adds the conversation creator as a 'creator' role participant.
    SSE endpoints poll the database directly for real-time updates.
    """
    if created:
        logger.debug(f"Conversation created: {instance.id}")
        if instance.user_id:
            ConversationParticipant.objects.get_or_create(
                conversation=instance,
                user=instance.user,
                defaults={"role": ParticipantRole.CREATOR},
            )
            # Audit log for creator joining
            try:
                from apps.compliance.models import AuditAction, AuditLog

                AuditLog.log(
                    actor_id=instance.user.id,
                    actor_email=instance.user.email,
                    action=AuditAction.PARTICIPANT_JOINED,
                    resource_type="conversation",
                    resource_id=str(instance.id),
                    metadata={"role": ParticipantRole.CREATOR, "auto": True},
                )
            except Exception:
                logger.debug("Audit log skipped (compliance app not ready)")
    else:
        logger.debug(f"Conversation updated: {instance.id}")


@receiver(pre_delete, sender=Conversation)
def on_conversation_deleted(sender, instance: Conversation, **kwargs):
    """
    Signal handler for when a conversation is about to be deleted.

    Note: SSE endpoints detect deletions by comparing current vs known IDs.
    ConversationParticipant records are cascade-deleted automatically.
    """
    logger.debug(f"Conversation deleted: {instance.id}")
