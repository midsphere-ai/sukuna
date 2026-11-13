"""Management command to create or update subscription plans in the database.

Products must be created in the Dodo Payments dashboard first.
The dodo_product_id values should be set via environment variables or updated
manually after dashboard setup.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.billing.models import SubscriptionPlan


class Command(BaseCommand):
    """Create or update subscription plans (Free, Lite, Pro) in the local database."""

    help = "Create subscription plans in database"

    def handle(self, *args, **options):
        """Execute the command to provision all subscription plans."""

        plans_config = [
            {
                "name": "Jatayu Free",
                "tier": "free",
                "price": 0.00,
                "dodo_product_id": "",
                "features": {
                    "max_concurrent_tasks": (1, "Run 1 task at a time"),
                    "use_custom_llm": (False, "Bring your own LLM"),
                    "use_custom_e2b": (False, "Custom sandbox environment"),
                    "use_custom_mcp": (False, "Custom MCP servers"),
                    "can_schedule_tasks": (False, "Scheduled tasks"),
                },
                "monthly_credits": 300,
            },
            {
                "name": "Jatayu Lite",
                "tier": "basic",
                "price": 5.00,
                "dodo_product_id": getattr(settings, "DODO_LITE_PLAN_PRODUCT_ID", ""),
                "features": {
                    "max_concurrent_tasks": (3, "Run up to 3 tasks at once"),
                    "use_custom_llm": (True, "Bring your own LLM"),
                    "use_custom_e2b": (False, "Custom sandbox environment"),
                    "use_custom_mcp": (True, "Custom MCP servers"),
                    "can_schedule_tasks": (True, "Scheduled tasks"),
                },
                "monthly_credits": 3500,
            },
            {
                "name": "Jatayu Pro",
                "tier": "premium",
                "price": 19.00,
                "dodo_product_id": getattr(settings, "DODO_PRO_PLAN_PRODUCT_ID", ""),
                "features": {
                    "max_concurrent_tasks": (3, "Run up to 3 tasks at once"),
                    "use_custom_llm": (True, "Bring your own LLM"),
                    "use_custom_e2b": (True, "Custom sandbox environment"),
                    "use_custom_mcp": (True, "Custom MCP servers"),
                    "can_schedule_tasks": (True, "Scheduled tasks"),
                },
                "monthly_credits": 12000,
            },
        ]

        for plan_config in plans_config:
            plan, created = SubscriptionPlan.objects.update_or_create(
                tier=plan_config["tier"],
                defaults={
                    "name": plan_config["name"],
                    "price": plan_config["price"],
                    "dodo_product_id": plan_config["dodo_product_id"],
                    "features": plan_config["features"],
                    "monthly_credits": plan_config.get("monthly_credits", 0),
                    "is_active": True,
                },
            )

            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action} {plan.name} in database"))

        self.stdout.write(self.style.SUCCESS("All plans processed successfully!"))
