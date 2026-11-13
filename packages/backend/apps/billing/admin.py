"""Django admin configuration for billing models.

Registers all billing-related models with the Unfold admin interface,
including subscription plans, payments, coupons, webhooks, credits, and support tickets.
"""

from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.decorators import display

from .models import (
    CouponUsage,
    CreditGrant,
    CreditHold,
    CreditRate,
    CreditTransaction,
    CreditWallet,
    CustomerSupportTicket,
    FailedPayment,
    Payment,
    PromoCoupon,
    SubscriptionHistory,
    SubscriptionPause,
    SubscriptionPlan,
    TrialPeriod,
    UsageRecord,
    UserSubscription,
    WebhookEvent,
)


@admin.register(SubscriptionHistory)
class SubscriptionHistoryAdmin(ModelAdmin):
    """Admin interface for viewing and filtering subscription history records."""

    list_display = ("subscription", "action", "old_plan", "new_plan", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("subscription__user__email", "notes")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(FailedPayment)
class FailedPaymentAdmin(ModelAdmin):
    """Admin interface for tracking and managing failed payment attempts."""

    list_display = (
        "user",
        "subscription",
        "amount",
        "error_code",
        "retry_count",
        "resolved",
        "created_at",
    )
    list_filter = ("resolved", "created_at", "retry_count")
    search_fields = (
        "user__email",
        "dodo_payment_id",
        "error_code",
        "error_description",
    )
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(SubscriptionPause)
class SubscriptionPauseAdmin(ModelAdmin):
    """Admin interface for viewing subscription pause and resume events."""

    list_display = ("subscription", "paused_at", "resumed_at", "is_active")
    list_filter = ("is_active", "paused_at", "resumed_at")
    search_fields = ("subscription__user__email", "pause_reason")
    readonly_fields = ("paused_at",)
    ordering = ("-paused_at",)


@admin.register(PromoCoupon)
class PromoCouponAdmin(ModelAdmin):
    """Admin interface for managing promotional coupons and discount codes."""

    list_display = (
        "code",
        "discount_type",
        "discount_value",
        "used_count",
        "max_uses",
        "is_active",
        "valid_from",
        "valid_until",
    )
    list_filter = ("is_active", "discount_type", "valid_from", "valid_until")
    search_fields = ("code",)
    readonly_fields = ("created_at", "used_count")
    ordering = ("-created_at",)
    filter_horizontal = ("applicable_plans",)
    fieldsets = (
        ("Coupon Details", {"fields": ("code", "discount_type", "discount_value")}),
        ("Usage Limits", {"fields": ("max_uses", "used_count")}),
        ("Validity", {"fields": ("valid_from", "valid_until", "is_active")}),
        ("Applicable Plans", {"fields": ("applicable_plans",)}),
        ("Timestamps", {"fields": ("created_at",)}),
    )


@admin.register(CouponUsage)
class CouponUsageAdmin(ModelAdmin):
    """Admin interface for tracking coupon usage by users."""

    list_display = ("coupon", "user", "subscription", "discount_applied", "used_at")
    list_filter = ("used_at",)
    search_fields = ("coupon__code", "user__email")
    readonly_fields = ("used_at",)
    ordering = ("-used_at",)


@admin.register(WebhookEvent)
class WebhookEventAdmin(ModelAdmin):
    """Admin interface for viewing and debugging Dodo Payments webhook events."""

    list_display = ("event_id", "event_type", "processed", "retry_count", "created_at")
    list_filter = ("processed", "event_type", "created_at")
    search_fields = ("event_id", "event_type", "error_message")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    fieldsets = (
        ("Event Details", {"fields": ("event_id", "event_type", "payload")}),
        (
            "Processing Status",
            {"fields": ("processed", "processed_at", "retry_count", "error_message")},
        ),
        ("Timestamps", {"fields": ("created_at",)}),
    )


@admin.register(UsageRecord)
class UsageRecordAdmin(ModelAdmin):
    """Admin interface for viewing metered usage records."""

    list_display = ("subscription", "metric_name", "quantity", "timestamp")
    list_filter = ("metric_name", "timestamp")
    search_fields = ("subscription__user__email", "metric_name")
    readonly_fields = ("timestamp",)
    ordering = ("-timestamp",)


@admin.register(TrialPeriod)
class TrialPeriodAdmin(ModelAdmin):
    """Admin interface for managing trial period records."""

    list_display = (
        "subscription",
        "trial_start",
        "trial_end",
        "converted_to_paid",
        "converted_at",
    )
    list_filter = ("converted_to_paid", "trial_start", "trial_end")
    search_fields = ("subscription__user__email",)
    readonly_fields = ("trial_start",)
    ordering = ("-trial_start",)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(ModelAdmin):
    """Admin interface for creating and managing subscription plans."""

    list_display = ("id", "name", "tier", "price", "is_active", "created_at")
    list_filter = ("is_active", "tier", "created_at")
    search_fields = ("name", "dodo_product_id")
    readonly_fields = ("id", "created_at")
    ordering = ("-created_at",)
    fieldsets = (
        ("Plan Details", {"fields": ("name", "tier", "price")}),
        ("Dodo Payments", {"fields": ("dodo_product_id",)}),
        ("Features", {"fields": ("features",)}),
        ("Credits", {"fields": ("monthly_credits",)}),
        ("Status", {"fields": ("is_active",)}),
        ("Timestamps", {"fields": ("created_at",)}),
    )


@admin.register(UserSubscription)
class UserSubscriptionAdmin(ModelAdmin):
    """Admin interface for managing user subscriptions and their Dodo Payments links."""

    list_display = (
        "id",
        "user",
        "plan",
        "status",
        "start_date",
        "end_date",
        "auto_renew",
        "paused",
    )
    list_filter = ("status", "auto_renew", "paused", "created_at")
    search_fields = ("user__email", "dodo_subscription_id", "dodo_customer_id")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-created_at",)
    fieldsets = (
        ("User & Plan", {"fields": ("user", "plan")}),
        ("Status", {"fields": ("status", "auto_renew", "paused", "paused_at")}),
        ("Dates", {"fields": ("start_date", "end_date")}),
        ("Dodo Payments", {"fields": ("dodo_subscription_id", "dodo_customer_id")}),
        (
            "Cancellation",
            {"fields": ("cancellation_reason", "cancellation_requested_at")},
        ),
        (
            "Payment Handling",
            {
                "fields": (
                    "last_payment_failed_at",
                    "payment_retry_count",
                    "grace_period_end",
                )
            },
        ),
        (
            "Scheduled Changes",
            {"fields": ("scheduled_plan_change", "scheduled_change_date")},
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    """Admin interface for viewing payment records and Dodo Payments details."""

    list_display = (
        "id",
        "user",
        "subscription",
        "amount",
        "currency",
        "status",
        "created_at",
    )
    list_filter = ("status", "currency", "created_at")
    search_fields = (
        "user__email",
        "dodo_payment_id",
    )
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
    fieldsets = (
        ("User & Subscription", {"fields": ("user", "subscription")}),
        (
            "Payment Details",
            {"fields": ("amount", "currency", "status", "payment_method")},
        ),
        (
            "Dodo Payments",
            {
                "fields": (
                    "dodo_payment_id",
                    "dodo_refund_id",
                )
            },
        ),
        ("Metadata", {"fields": ("metadata",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


# ── Credit System Admin ─────────────────────────────────────────────────────


@admin.register(CreditWallet)
class CreditWalletAdmin(ModelAdmin):
    """Admin interface for viewing user credit wallets."""

    list_display = (
        "user",
        "monthly_credits_remaining",
        "addon_credits",
        "free_credits",
        "version",
        "last_monthly_refresh",
    )
    list_filter = ("last_monthly_refresh",)
    search_fields = ("user__email",)
    readonly_fields = ("id", "created_at", "updated_at", "version")
    ordering = ("-updated_at",)
    fieldsets = (
        ("User", {"fields": ("id", "user")}),
        (
            "Monthly Credits",
            {
                "fields": (
                    "monthly_credits",
                    "monthly_credits_remaining",
                    "last_monthly_refresh",
                )
            },
        ),
        ("Other Pools", {"fields": ("addon_credits", "free_credits")}),
        (
            "Daily Credits",
            {
                "fields": (
                    "daily_credits",
                    "daily_credits_remaining",
                    "last_daily_refresh",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Internal",
            {
                "fields": ("version", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(CreditGrant)
class CreditGrantAdmin(ModelAdmin):
    """Admin interface for managing time-limited credit grants."""

    list_display = (
        "wallet",
        "grant_type",
        "remaining",
        "amount",
        "expires_at",
        "created_at",
    )
    list_filter = ("grant_type", "expires_at")
    search_fields = ("wallet__user__email", "source")
    readonly_fields = ("id", "created_at")
    ordering = ("-created_at",)


@admin.register(CreditHold)
class CreditHoldAdmin(ModelAdmin):
    """Admin interface for viewing credit holds on agent runs."""

    list_display = (
        "id",
        "wallet",
        "run",
        "amount_consumed",
        "amount_reserved",
        "status",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("wallet__user__email", "run__id")
    readonly_fields = ("id", "created_at", "settled_at")
    ordering = ("-created_at",)


@admin.register(CreditTransaction)
class CreditTransactionAdmin(ModelAdmin):
    """Admin interface for the immutable credit transaction ledger (read-only)."""

    list_display = (
        "wallet",
        "amount",
        "category",
        "source_type",
        "balance_after",
        "created_at",
    )
    list_filter = ("category", "created_at")
    search_fields = ("wallet__user__email", "source_type", "description")
    readonly_fields = (
        "id",
        "wallet",
        "hold",
        "amount",
        "balance_after",
        "category",
        "source_type",
        "description",
        "metadata",
        "created_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CreditRate)
class CreditRateAdmin(ModelAdmin):
    """Admin interface for editing credit pricing rates."""

    list_display = ("category", "key", "credits_per_unit", "unit", "markup", "active")
    list_filter = ("category", "active")
    search_fields = ("key",)
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("category", "key")
    list_editable = ("credits_per_unit", "markup", "active")


@admin.register(CustomerSupportTicket)
class CustomerSupportTicketAdmin(ModelAdmin):
    """Admin interface for managing customer support tickets with status workflow."""

    list_display = ("id", "user", "title", "display_status", "created_at", "updated_at")
    list_filter = ("status", "created_at", "updated_at")
    search_fields = ("user__email", "user__username", "title", "message")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-created_at",)
    list_per_page = 25
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Ticket Information",
            {
                "fields": ("id", "user", "title", "message"),
                "classes": ("wide",),
            },
        ),
        (
            "Status",
            {
                "fields": ("status",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    actions = [
        "mark_as_open",
        "mark_as_in_progress",
        "mark_as_resolved",
        "mark_as_closed",
    ]

    @display(
        description="Status",
        label={
            "open": "warning",
            "in_progress": "info",
            "resolved": "success",
            "closed": "secondary",
        },
    )
    def display_status(self, obj):
        """Return the ticket status for display with color-coded labels.

        Args:
            obj: The CustomerSupportTicket instance.

        Returns:
            str: The ticket status string.
        """
        return obj.status

    @admin.action(description="Mark selected tickets as Open")
    def mark_as_open(self, request, queryset):
        """Bulk action to mark selected tickets as Open.

        Args:
            request: The current HTTP request.
            queryset: The selected CustomerSupportTicket queryset.
        """
        updated = queryset.update(status="open")
        self.message_user(request, f"{updated} ticket(s) marked as Open.")

    @admin.action(description="Mark selected tickets as In Progress")
    def mark_as_in_progress(self, request, queryset):
        """Bulk action to mark selected tickets as In Progress.

        Args:
            request: The current HTTP request.
            queryset: The selected CustomerSupportTicket queryset.
        """
        updated = queryset.update(status="in_progress")
        self.message_user(request, f"{updated} ticket(s) marked as In Progress.")

    @admin.action(description="Mark selected tickets as Resolved")
    def mark_as_resolved(self, request, queryset):
        """Bulk action to mark selected tickets as Resolved.

        Args:
            request: The current HTTP request.
            queryset: The selected CustomerSupportTicket queryset.
        """
        updated = queryset.update(status="resolved")
        self.message_user(request, f"{updated} ticket(s) marked as Resolved.")

    @admin.action(description="Mark selected tickets as Closed")
    def mark_as_closed(self, request, queryset):
        """Bulk action to mark selected tickets as Closed.

        Args:
            request: The current HTTP request.
            queryset: The selected CustomerSupportTicket queryset.
        """
        updated = queryset.update(status="closed")
        self.message_user(request, f"{updated} ticket(s) marked as Closed.")
