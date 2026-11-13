"""Management command to create credit wallets for all existing users."""

from django.core.management.base import BaseCommand

from apps.billing.credit_service import PLAN_CREDITS, SIGNUP_BONUS, CreditService
from apps.billing.models import CreditWallet, UserSubscription


class Command(BaseCommand):
    """Create CreditWallet records for all users with subscriptions."""

    help = "Migrate existing users to the credit system by creating wallets"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to the database",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        created_count = 0
        skipped_count = 0

        subscriptions = (
            UserSubscription.objects.select_related("user", "plan")
            .filter(user__isnull=False)
            .iterator()
        )

        for sub in subscriptions:
            if CreditWallet.objects.filter(user=sub.user).exists():
                skipped_count += 1
                continue

            plan_credits = 0
            if sub.plan:
                plan_credits = sub.plan.monthly_credits or PLAN_CREDITS.get(
                    sub.plan.tier, 0
                )

            if dry_run:
                self.stdout.write(
                    f"[DRY RUN] Would create wallet for {sub.user.email}: "
                    f"{plan_credits} monthly + {SIGNUP_BONUS} bonus"
                )
            else:
                CreditService.get_or_create_wallet(sub.user)

            created_count += 1

        verb = "Would create" if dry_run else "Created"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {created_count} wallets, skipped {skipped_count} existing."
            )
        )
