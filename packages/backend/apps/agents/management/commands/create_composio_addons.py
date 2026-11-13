"""Management command to sync Composio-managed OAuth2 toolkits into the MarketplaceAddon table."""

import logging

from composio_client import Composio
from django.core.management.base import BaseCommand

from apps.storage.models import MarketplaceAddon

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Fetch Composio-managed toolkits and upsert them as MarketplaceAddon records."""

    help = "Sync Composio OAuth2 toolkits into the MarketplaceAddon table"

    def handle(self, *args, **options):
        """Execute the command: fetch toolkits from Composio API and create/update addons."""
        composio = Composio()
        params = {"limit": 1000, "managed_by": "composio"}
        logger.info(
            "[composio] Building marketplace with managed toolkits from composio"
        )
        toolkits = composio.toolkits.list(**params).items
        verified_toolkits = []
        for tool in toolkits:
            tool = tool.to_dict()
            auth_schemes = tool.get("auth_schemes", [])
            composio_managed_auth_schemes = tool.get(
                "composio_managed_auth_schemes", []
            )

            if (
                "OAUTH2" not in auth_schemes
                or "OAUTH2" not in composio_managed_auth_schemes
            ):
                continue

            name = tool["name"]
            link = tool["meta"]["app_url"]
            enum = tool["slug"]

            logo_url = None
            meta = tool.get("meta", {})
            if isinstance(meta, dict):
                logo_url = meta.get("logo")
            elif hasattr(meta, "__dict__"):
                logo_url = meta.__dict__.get("logo")

            if not logo_url:
                logo_url = tool.get("logo")

            description = None
            if isinstance(meta, dict):
                description = meta.get("description")
            elif hasattr(meta, "__dict__"):
                description = meta.__dict__.get("description")

            if not description:
                description = tool.get("description")

            tags = []
            categories = []
            if isinstance(meta, dict) and "categories" in meta:
                category_list = meta.get("categories", [])
                for cat in category_list:
                    if isinstance(cat, dict):
                        cat_name = cat.get("name", "")
                        cat_id = cat.get("id", "")
                        tags.append(cat_name)
                        categories.append(cat_id)
                    elif hasattr(cat, "__dict__"):
                        cat_name = cat.__dict__.get("name", "")
                        cat_id = cat.__dict__.get("id", "")
                        tags.append(cat_name)
                        categories.append(cat_id)

            object, status = MarketplaceAddon.objects.get_or_create(
                name=name,
                description=description,
                logo=logo_url,
                link=link,
                enum=enum,
                tags=tags,
                categories=categories,
            )

            # Auto-classify billing tier from categories/tags
            tier = object.classify_credit_tier()
            if object.credit_tier != tier:
                object.credit_tier = tier
                object.save(update_fields=["credit_tier"])

            verified_toolkits.append(object)

        logger.info(f"Total toolkits available: {len(toolkits)}")
        logger.info(f"Total verified toolkits: {len(verified_toolkits)}")
        logger.info(f"Marketplace count: {MarketplaceAddon.objects.count()}")
