"""Management command to seed the CreditRate table with default rates."""

from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.billing.models import CreditRate

RATES = [
    # LLM: 2000 credits per $1 USD of provider cost, 2x markup
    {
        "category": "llm",
        "key": "default",
        "credits_per_unit": Decimal("2000.0000"),
        "unit": "usd",
        "markup": Decimal("2.00"),
    },
    # Compute: 8 credits per minute of active sandbox
    {
        "category": "compute",
        "key": "e2b:default",
        "credits_per_unit": Decimal("8.0000"),
        "unit": "minute",
        "markup": Decimal("1.00"),
    },
    # Integration tiers
    {
        "category": "integration",
        "key": "composio:basic",
        "credits_per_unit": Decimal("2.0000"),
        "unit": "invocation",
        "markup": Decimal("1.00"),
    },
    {
        "category": "integration",
        "key": "composio:standard",
        "credits_per_unit": Decimal("5.0000"),
        "unit": "invocation",
        "markup": Decimal("1.00"),
    },
    {
        "category": "integration",
        "key": "composio:premium",
        "credits_per_unit": Decimal("10.0000"),
        "unit": "invocation",
        "markup": Decimal("1.00"),
    },
    # Tool call rates: native exo tools
    {
        "category": "tool",
        "key": "native:default",
        "credits_per_unit": Decimal("1.0000"),
        "unit": "invocation",
        "markup": Decimal("1.00"),
    },
    # Tool call rates: MCP addon tools (tiered)
    {
        "category": "tool",
        "key": "mcp:basic",
        "credits_per_unit": Decimal("2.0000"),
        "unit": "invocation",
        "markup": Decimal("1.00"),
    },
    {
        "category": "tool",
        "key": "mcp:standard",
        "credits_per_unit": Decimal("5.0000"),
        "unit": "invocation",
        "markup": Decimal("1.00"),
    },
    {
        "category": "tool",
        "key": "mcp:premium",
        "credits_per_unit": Decimal("10.0000"),
        "unit": "invocation",
        "markup": Decimal("1.00"),
    },
]


class Command(BaseCommand):
    """Seed the CreditRate table with default credit pricing rates."""

    help = "Seed default credit rates for LLM, compute, and integration pricing"

    def handle(self, *args, **options):
        for rate_data in RATES:
            obj, created = CreditRate.objects.update_or_create(
                category=rate_data["category"],
                key=rate_data["key"],
                defaults={
                    "credits_per_unit": rate_data["credits_per_unit"],
                    "unit": rate_data["unit"],
                    "markup": rate_data["markup"],
                    "active": True,
                },
            )
            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action} rate: {obj}"))

        self.stdout.write(self.style.SUCCESS("All credit rates seeded."))
