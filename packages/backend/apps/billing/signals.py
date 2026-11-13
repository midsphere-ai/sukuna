"""Signals for the billing app.

Auto-provisions credit wallets when subscriptions are created or updated.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserSubscription

logger = logging.getLogger(__name__)


@receiver(post_save, sender=UserSubscription)
def provision_credit_wallet(sender, instance, created, **kwargs):
    """Create or update credit wallet when subscription changes."""
    from .credit_service import CreditService

    try:
        wallet = CreditService.get_or_create_wallet(instance.user)
        if instance.plan and not created:
            CreditService.sync_wallet_to_plan(wallet, instance.plan)
    except Exception:
        logger.exception(
            "Failed to provision credit wallet for user %s", instance.user_id
        )
