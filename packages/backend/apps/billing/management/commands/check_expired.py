"""Management command to check and expire overdue subscriptions."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.billing.models import SubscriptionPlan, UserSubscription


class Command(BaseCommand):
    """Management command to find expired subscriptions and downgrade them to the free plan."""

    help = "Check and update expired subscriptions"

    def handle(self, *args, **options):
        """Execute the command to expire overdue subscriptions.

        Finds active subscriptions past their end date with auto_renew disabled,
        marks them as expired, and downgrades them to the free plan.

        Args:
            *args: Positional arguments (unused).
            **options: Command options (unused).
        """
        now = timezone.now()

        # Find expired subscriptions
        expired = UserSubscription.objects.filter(
            status="active", end_date__lt=now, auto_renew=False
        )

        for subscription in expired:
            subscription.status = "expired"
            subscription.save()

            # Optionally downgrade to free plan
            free_plan = SubscriptionPlan.objects.filter(tier="free").first()
            if free_plan:
                subscription.plan = free_plan
                subscription.dodo_subscription_id = None
                subscription.end_date = None
                subscription.save()

        self.stdout.write(
            self.style.SUCCESS(f"Updated {expired.count()} expired subscriptions")
        )
