"""Django Unfold admin theme configuration for Jatayu AI.

Defines the UNFOLD settings dict controlling sidebar navigation, color
palette, tabs, and dashboard callback used by the admin interface.
Aligned with the Jatayu design system (dark-mode-first, monochrome).
"""

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

UNFOLD = {
    "SITE_TITLE": "Jatayu AI",
    "SITE_HEADER": "Jatayu AI",
    "SITE_SUBHEADER": "Agent execution platform",
    "SITE_URL": "/",
    "SITE_ICON": {
        "light": lambda request: "/static/images/logo.png",
        "dark": lambda request: "/static/images/logo-dark.png",
    },
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "SHOW_BACK_BUTTON": True,
    "THEME": "dark",
    "BORDER_RADIUS": "6px",
    "DASHBOARD_CALLBACK": "config.dashboard.dashboard_callback",
    "STYLES": [
        "/static/css/project.css",
    ],
    "COLORS": {
        # Monochrome neutrals — Jatayu base scale.
        "base": {
            "50": "245 245 247",  # #F5F5F7 — text-primary (light-mode)
            "100": "236 238 241",  # #ECEEF1 — surface-2 (light-mode)
            "200": "209 209 214",  # #D1D1D6
            "300": "154 154 160",  # #9A9AA0 — text-secondary (light) / text-tertiary (dark)
            "400": "122 122 128",  # #7A7A80
            "500": "90 90 96",  # #5A5A60 — text-tertiary (dark)
            "600": "58 58 64",  # #3A3A40
            "700": "42 42 46",  # #2A2A2E
            "800": "26 26 28",  # #1A1A1C — accent (light)
            "900": "21 21 23",  # #151517 — surface-2 (dark)
            "950": "11 11 12",  # #0B0B0C — bg (dark)
        },
        # Primary — monochrome accent (near-white in dark, near-black in light).
        "primary": {
            "50": "245 245 247",
            "100": "236 238 241",
            "200": "209 209 214",
            "300": "176 176 184",
            "400": "154 154 160",
            "500": "237 237 237",  # #EDEDED — dark-mode accent
            "600": "208 208 208",
            "700": "160 160 160",
            "800": "90 90 96",
            "900": "42 42 46",
            "950": "26 26 28",  # #1A1A1C — light-mode accent
        },
        "font": {
            "subtle-light": "154 154 160",  # #9A9AA0 — text-tertiary (light)
            "subtle-dark": "90 90 96",  # #5A5A60 — text-tertiary (dark)
            "default-light": "95 99 104",  # #5F6368 — text-secondary (light)
            "default-dark": "154 154 160",  # #9A9AA0 — text-secondary (dark)
            "important-light": "32 33 36",  # #202124 — text-primary (light)
            "important-dark": "245 245 247",  # #F5F5F7 — text-primary (dark)
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "command_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "title": _("Dashboard"),
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                ],
            },
            {
                "title": _("User Management"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "person",
                        "link": reverse_lazy("admin:users_user_changelist"),
                    },
                    {
                        "title": _("Groups"),
                        "icon": "group",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                ],
            },
            {
                "title": _("Agents & AI"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("MCP Configs"),
                        "icon": "settings_input_component",
                        "link": reverse_lazy(
                            "admin:agents_usercustommcpconfig_changelist"
                        ),
                    },
                    {
                        "title": _("E2B Sandboxes"),
                        "icon": "terminal",
                        "link": reverse_lazy("admin:agents_e2bsandbox_changelist"),
                    },
                ],
            },
            {
                "title": _("Storage"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Conversations"),
                        "icon": "forum",
                        "link": reverse_lazy("admin:storage_conversation_changelist"),
                    },
                    {
                        "title": _("Tasks"),
                        "icon": "task_alt",
                        "link": reverse_lazy("admin:storage_agentrun_changelist"),
                    },
                    {
                        "title": _("Stored Files"),
                        "icon": "folder",
                        "link": reverse_lazy("admin:storage_storedfile_changelist"),
                    },
                    {
                        "title": _("System Memory"),
                        "icon": "psychology",
                        "link": reverse_lazy(
                            "admin:storage_systemwidememory_changelist"
                        ),
                    },
                ],
            },
            {
                "title": _("Marketplace"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Addons"),
                        "icon": "extension",
                        "link": reverse_lazy(
                            "admin:storage_marketplaceaddon_changelist"
                        ),
                    },
                    {
                        "title": _("User Addons"),
                        "icon": "add_circle",
                        "link": reverse_lazy(
                            "admin:storage_usermarketplaceaddons_changelist"
                        ),
                    },
                ],
            },
            {
                "title": _("Projects"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Projects"),
                        "icon": "workspaces",
                        "link": reverse_lazy("admin:spaces_project_changelist"),
                    },
                    {
                        "title": _("Project Files"),
                        "icon": "attach_file",
                        "link": reverse_lazy("admin:spaces_projectfile_changelist"),
                    },
                ],
            },
            {
                "title": _("Billing"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Subscription Plans"),
                        "icon": "loyalty",
                        "link": reverse_lazy(
                            "admin:billing_subscriptionplan_changelist"
                        ),
                    },
                    {
                        "title": _("User Subscriptions"),
                        "icon": "card_membership",
                        "link": reverse_lazy(
                            "admin:billing_usersubscription_changelist"
                        ),
                    },
                    {
                        "title": _("Payments"),
                        "icon": "payments",
                        "link": reverse_lazy("admin:billing_payment_changelist"),
                    },
                    {
                        "title": _("Failed Payments"),
                        "icon": "credit_card_off",
                        "link": reverse_lazy("admin:billing_failedpayment_changelist"),
                    },
                    {
                        "title": _("Usage Records"),
                        "icon": "analytics",
                        "link": reverse_lazy("admin:billing_usagerecord_changelist"),
                    },
                    {
                        "title": _("Trials"),
                        "icon": "hourglass_empty",
                        "link": reverse_lazy("admin:billing_trialperiod_changelist"),
                    },
                ],
            },
            {
                "title": _("Promotions"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Promo Coupons"),
                        "icon": "local_offer",
                        "link": reverse_lazy("admin:billing_promocoupon_changelist"),
                    },
                    {
                        "title": _("Coupon Usage"),
                        "icon": "redeem",
                        "link": reverse_lazy("admin:billing_couponusage_changelist"),
                    },
                ],
            },
            {
                "title": _("Customer Support"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("All Tickets"),
                        "icon": "support_agent",
                        "link": reverse_lazy(
                            "admin:billing_customersupportticket_changelist"
                        ),
                    },
                    {
                        "title": _("Open Tickets"),
                        "icon": "pending",
                        "link": lambda request: "/admin/billing/customersupportticket/?status__exact=open",
                    },
                    {
                        "title": _("In Progress"),
                        "icon": "hourglass_top",
                        "link": lambda request: "/admin/billing/customersupportticket/?status__exact=in_progress",
                    },
                    {
                        "title": _("Resolved"),
                        "icon": "check_circle",
                        "link": lambda request: "/admin/billing/customersupportticket/?status__exact=resolved",
                    },
                ],
            },
            {
                "title": _("System"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Subscription History"),
                        "icon": "history",
                        "link": reverse_lazy(
                            "admin:billing_subscriptionhistory_changelist"
                        ),
                    },
                    {
                        "title": _("Subscription Pauses"),
                        "icon": "pause_circle",
                        "link": reverse_lazy(
                            "admin:billing_subscriptionpause_changelist"
                        ),
                    },
                    {
                        "title": _("Webhook Events"),
                        "icon": "webhook",
                        "link": reverse_lazy("admin:billing_webhookevent_changelist"),
                    },
                ],
            },
            {
                "title": _("Content"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Blogs"),
                        "icon": "article",
                        "link": reverse_lazy("admin:blogs_tutorialblog_changelist"),
                    },
                    {
                        "title": _("Announcements"),
                        "icon": "campaign",
                        "link": reverse_lazy("admin:blogs_announcements_changelist"),
                    },
                    {
                        "title": _("Change Logs"),
                        "icon": "update",
                        "link": reverse_lazy("admin:blogs_changelog_changelist"),
                    },
                    {
                        "title": _("Plan Footers"),
                        "icon": "description",
                        "link": reverse_lazy("admin:blogs_planfooter_changelist"),
                    },
                ],
            },
        ],
    },
    "TABS": [
        {
            "models": [
                "agents.usercustommcpconfig",
            ],
            "items": [
                {
                    "title": _("MCP Configs"),
                    "link": reverse_lazy("admin:agents_usercustommcpconfig_changelist"),
                },
            ],
        },
        {
            "models": [
                "storage.conversation",
                "storage.agentrun",
            ],
            "items": [
                {
                    "title": _("Conversations"),
                    "link": reverse_lazy("admin:storage_conversation_changelist"),
                },
                {
                    "title": _("Tasks"),
                    "link": reverse_lazy("admin:storage_agentrun_changelist"),
                },
            ],
        },
        {
            "models": [
                "billing.subscriptionplan",
                "billing.usersubscription",
                "billing.payment",
            ],
            "items": [
                {
                    "title": _("Plans"),
                    "link": reverse_lazy("admin:billing_subscriptionplan_changelist"),
                },
                {
                    "title": _("Subscriptions"),
                    "link": reverse_lazy("admin:billing_usersubscription_changelist"),
                },
                {
                    "title": _("Payments"),
                    "link": reverse_lazy("admin:billing_payment_changelist"),
                },
            ],
        },
    ],
}


def dashboard_callback(request, context):
    """
    Callback to prepare custom variables for index template which is used as dashboard
    template. It can be overridden in application by creating custom admin/index.html.
    """
    context.update(
        {
            "site_title": "Jatayu AI Dashboard",
        }
    )
    return context
