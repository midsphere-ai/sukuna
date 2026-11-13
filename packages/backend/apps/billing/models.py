"""Django models for the billing app.

Defines subscription plans, user subscriptions, payments, trials, coupons,
webhook events, usage tracking, credit system, and customer support tickets.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from math import ceil

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.users.models import User


class SubscriptionPlanManager(models.Manager):
    """Custom manager for SubscriptionPlan queries."""

    def active(self):
        """Return all active subscription plans."""
        return self.filter(is_active=True)


class UserSubscriptionManager(models.Manager):
    """Custom manager for UserSubscription queries."""

    def by_dodo_id(self, dodo_id):
        """Look up a subscription by its Dodo subscription ID (with select_for_update)."""
        return self.select_for_update().filter(dodo_subscription_id=dodo_id).first()


class PaymentManager(models.Manager):
    """Custom manager for Payment queries."""

    def for_user(self, user):
        """Return all payments for a user, most recent first."""
        return self.filter(user=user).order_by("-created_at")


class SubscriptionHistoryManager(models.Manager):
    """Custom manager for SubscriptionHistory queries."""

    def for_user(self, user):
        """Return subscription history for a user with related plans."""
        return (
            self.filter(user=user)
            .select_related("old_plan", "new_plan")
            .order_by("-created_at")
        )


class SubscriptionHistory(models.Model):
    """Track all subscription changes"""

    ACTION_CHOICES = [
        ("created", "Created"),
        ("upgraded", "Upgraded"),
        ("downgraded", "Downgraded"),
        ("cancelled", "Cancelled"),
        ("reactivated", "Reactivated"),
        ("expired", "Expired"),
        ("payment_failed", "Payment Failed"),
        ("synced", "Synced"),
    ]

    subscription = models.ForeignKey(
        "UserSubscription", on_delete=models.SET_NULL, related_name="history", null=True
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="subscription_history_direct",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    old_plan = models.ForeignKey(
        "SubscriptionPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="old_subscriptions",
    )
    new_plan = models.ForeignKey(
        "SubscriptionPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="new_subscriptions",
    )
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SubscriptionHistoryManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Subscription Histories"

    def __str__(self):
        return f"{self.subscription.user.email} - {self.action} at {self.created_at}"


class FailedPayment(models.Model):
    """Track failed payment attempts for retry logic"""

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    subscription = models.ForeignKey(
        "UserSubscription", on_delete=models.SET_NULL, null=True
    )
    dodo_payment_id = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    error_code = models.CharField(max_length=50, blank=True)
    error_description = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    last_retry_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - Failed {self.amount} (Retries: {self.retry_count})"


class SubscriptionPause(models.Model):
    """Track subscription pauses"""

    subscription = models.ForeignKey(
        "UserSubscription", on_delete=models.SET_NULL, related_name="pauses", null=True
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="subscription_pauses"
    )
    paused_at = models.DateTimeField(auto_now_add=True)
    resumed_at = models.DateTimeField(null=True, blank=True)
    pause_reason = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        email = self.user.email if self.user else "Unknown"
        return f"{email} - Paused at {self.paused_at}"


# 4. PROMO CODES / COUPONS
class PromoCoupon(models.Model):
    """Discount coupons for subscriptions"""

    DISCOUNT_TYPE_CHOICES = [
        ("percentage", "Percentage"),
        ("fixed", "Fixed Amount"),
    ]

    code = models.CharField(max_length=50, unique=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    max_uses = models.IntegerField(null=True, blank=True)
    used_count = models.IntegerField(default=0)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    applicable_plans = models.ManyToManyField("SubscriptionPlan", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        """Check whether this coupon is currently valid for use.

        Returns:
            bool: True if the coupon is active, within its validity window,
                and has not exceeded its maximum usage count.
        """
        now = timezone.now()
        if not self.is_active:
            return False
        if now < self.valid_from or now > self.valid_until:
            return False
        if self.max_uses and self.used_count >= self.max_uses:
            return False
        return True

    def __str__(self):
        return f"{self.code} - {self.discount_value}{'%' if self.discount_type == 'percentage' else 'USD'}"


# 5. COUPON USAGE TRACKING
class CouponUsage(models.Model):
    """Track who used which coupons"""

    coupon = models.ForeignKey(
        PromoCoupon, on_delete=models.CASCADE, related_name="usages"
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    subscription = models.ForeignKey(
        "UserSubscription", on_delete=models.SET_NULL, null=True
    )
    discount_applied = models.DecimalField(max_digits=10, decimal_places=2)
    used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["coupon", "user"]

    def __str__(self):
        return f"{self.user.email} used {self.coupon.code}"


# 6. WEBHOOK EVENT LOG
class WebhookEvent(models.Model):
    """Log all webhook events for debugging"""

    event_id = models.CharField(max_length=100, unique=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} - {self.created_at}"


# 7. USAGE TRACKING (for metered billing if needed)
class UsageRecord(models.Model):
    """Track usage for potential metered billing"""

    subscription = models.ForeignKey(
        "UserSubscription",
        on_delete=models.SET_NULL,
        related_name="usage_records",
        null=True,
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="usage_records_direct"
    )
    metric_name = models.CharField(max_length=100)  # e.g., 'api_calls', 'storage_gb'
    quantity = models.DecimalField(max_digits=15, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["subscription", "metric_name", "timestamp"]),
        ]

    def __str__(self):
        email = self.user.email if self.user else "Unknown"
        return f"{email} - {self.metric_name}: {self.quantity}"


class TrialPeriod(models.Model):
    """Track trial periods for subscriptions"""

    subscription = models.OneToOneField(
        "UserSubscription", on_delete=models.SET_NULL, related_name="trial", null=True
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="trial_periods"
    )
    trial_start = models.DateTimeField(auto_now_add=True)
    trial_end = models.DateTimeField()
    converted_to_paid = models.BooleanField(default=False)
    converted_at = models.DateTimeField(null=True, blank=True)

    def is_active(self):
        """Check whether this trial period is still active.

        Returns:
            bool: True if the trial has not ended and has not been converted to paid.
        """
        return timezone.now() < self.trial_end and not self.converted_to_paid

    def __str__(self):
        email = self.user.email if self.user else "Unknown"
        return f"{email} - Trial until {self.trial_end}"


class SubscriptionPlan(models.Model):
    """A subscription plan with tier, pricing, features, and optional Dodo Payments product link."""

    id = models.UUIDField(
        editable=False, default=uuid.uuid4, unique=True, primary_key=True
    )
    TIER_CHOICES = [
        ("free", "Free"),
        ("basic", "Basic"),
        ("premium", "Premium"),
    ]

    name = models.CharField(max_length=100)
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, unique=True)
    price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    dodo_product_id = models.CharField(max_length=100, blank=True, null=True)
    features = models.JSONField(default=dict)
    monthly_credits = models.IntegerField(
        default=0, help_text="Number of credits granted each billing cycle"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SubscriptionPlanManager()

    def clean(self):
        """Validate that feature keys are strings and values are allowed types.

        Raises:
            ValidationError: If feature keys are not strings or values are not
                int, float, bool, or str.
        """
        super().clean()
        if self.features:
            allowed_types = (int, float, bool, str)
            for key, value in self.features.items():
                if not isinstance(key, str):
                    raise ValidationError(
                        {
                            "features": f"Feature key must be a string, got {type(key).__name__}"
                        }
                    )
                if not isinstance(value, allowed_types):
                    raise ValidationError(
                        {
                            "features": f"Feature '{key}' has invalid type {type(value).__name__}. "
                            f"Allowed types: int, float, bool, str."
                        }
                    )

    def __str__(self):
        return f"{self.name} - ${self.price}"


class UserSubscription(models.Model):
    """A user's subscription linking them to a plan with Dodo Payments billing state."""

    id = models.UUIDField(
        editable=False, default=uuid.uuid4, unique=True, primary_key=True
    )
    STATUS_CHOICES = [
        ("active", "Active"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
        ("pending", "Pending"),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True)
    dodo_subscription_id = models.CharField(max_length=100, blank=True, null=True)
    dodo_customer_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancellation_reason = models.TextField(blank=True, null=True)
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    last_payment_failed_at = models.DateTimeField(null=True, blank=True)
    payment_retry_count = models.IntegerField(default=0)
    grace_period_end = models.DateTimeField(null=True, blank=True)
    paused = models.BooleanField(default=False)
    paused_at = models.DateTimeField(null=True, blank=True)
    scheduled_plan_change = models.ForeignKey(
        "SubscriptionPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scheduled_changes",
    )
    scheduled_change_date = models.DateTimeField(null=True, blank=True)

    objects = UserSubscriptionManager()

    def in_grace_period(self):
        """Check if subscription is in grace period"""
        if self.grace_period_end:
            return timezone.now() < self.grace_period_end
        return False

    def __str__(self):
        return f"{self.user.email} - {self.plan.name if self.plan else 'No Plan'}"

    def is_active(self):
        """Check whether this subscription is currently active.

        Returns:
            bool: True if status is active and end_date has not passed.
        """
        if self.status == "active" and self.end_date:
            return timezone.now() < self.end_date
        return self.status == "active"

    def get_weekly_task_limit(self):
        """Get the weekly task limit from the plan features"""
        if not self.plan or not self.plan.features:
            return 0
        value = self.plan.features.get("weekly_tasks", 0)
        return value[0] if isinstance(value, (list, tuple)) else value

    def get_feature_info(self, name):
        """Get the value of a named feature from the subscription plan.

        Args:
            name: The feature key to look up in plan features.

        Returns:
            The feature value (unwrapped from tuple/list if needed), or None if not found.
        """
        if not self.plan or not self.plan.features:
            return None
        value = self.plan.features.get(name)
        if value is None:
            return None
        return value[0] if isinstance(value, (list, tuple)) else value

    def get_tasks_used_this_week(self):
        """Count tasks used in the current week (reserved + completed)."""
        week_start = timezone.now() - timedelta(days=timezone.now().weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        return self.usage_records.filter(
            metric_name="agent_task",
            metadata__status__in=["reserved", "completed"],
            timestamp__gte=week_start,
        ).count()

    def get_sandbox_time(self):
        """Count sandbox used in the current month"""
        from django.db.models import Sum

        thirty_days_ago = timezone.now() - timedelta(days=30)
        return (
            self.usage_records.filter(
                metric_name="sandbox_time", timestamp__gte=thirty_days_ago
            ).aggregate(total=Sum("quantity"))["total"]
            or 0
        )

    def can_run_task(self):
        """Check if user can run another task this week"""
        limit = self.get_weekly_task_limit()
        used = self.get_tasks_used_this_week()
        return used < limit

    def check_sandbox_available(self):
        """Check if sandbox time is still available for this subscription.

        Returns:
            bool: True if remaining sandbox time is available, False otherwise.
        """
        available = self.get_feature_info("max_sandbox_time")
        if available is None:
            return False
        current = self.get_sandbox_time()
        return available > current

    def get_remaining_tasks(self):
        """Get number of tasks remaining this week"""
        limit = self.get_weekly_task_limit()
        used = self.get_tasks_used_this_week()
        return max(0, limit - used)

    def finalize_task_usage(self, run_id):
        """Mark a reserved task usage record as completed."""
        self.usage_records.filter(
            metric_name="agent_task",
            metadata__run_id=str(run_id),
            metadata__status="reserved",
        ).update(metadata={"run_id": str(run_id), "status": "completed"})

    def void_task_usage(self, run_id):
        """Void a reserved task usage record (task failed before execution)."""
        self.usage_records.filter(
            metric_name="agent_task",
            metadata__run_id=str(run_id),
            metadata__status="reserved",
        ).update(metadata={"run_id": str(run_id), "status": "voided"})

    def record_task_usage(self, metadata=None):
        """Record a task execution"""
        UsageRecord.objects.create(
            subscription=self,
            user=self.user,
            metric_name="agent_task",
            quantity=1,
            metadata=metadata or {},
        )

    def record_feature_usage(self, metric_name, quantity, metadata=None):
        """Record a metric execution"""
        UsageRecord.objects.create(
            subscription=self,
            user=self.user,
            metric_name=metric_name,
            quantity=quantity,
            metadata=metadata or {},
        )


class Payment(models.Model):
    """A payment record tracking Dodo Payments transactions for a subscription."""

    PAYMENT_STATUS = [
        ("created", "Created"),
        ("authorized", "Authorized"),
        ("captured", "Captured"),
        ("refund_pending", "Refund Pending"),
        ("refunded", "Refunded"),
        ("failed", "Failed"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    subscription = models.ForeignKey(
        UserSubscription, on_delete=models.SET_NULL, null=True
    )
    dodo_payment_id = models.CharField(max_length=100, blank=True, null=True)
    dodo_refund_id = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default="created")
    payment_method = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(default=dict)

    objects = PaymentManager()

    def __str__(self):
        return f"{self.user.email} - {self.amount} {self.currency}"


# ── Credit System ──────────────────────────────────────────────────────────────


class CreditWallet(models.Model):
    """Per-user credit balance with multiple pools consumed in priority order."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="credit_wallet"
    )

    # Plan-granted credits (refresh each billing cycle)
    monthly_credits = models.IntegerField(
        default=0, help_text="Total monthly grant from plan"
    )
    monthly_credits_remaining = models.IntegerField(default=0)

    # Purchased add-on credits (never expire)
    addon_credits = models.IntegerField(default=0)

    # One-time signup bonus (never expire)
    free_credits = models.IntegerField(default=0)

    # Optional daily allowance
    daily_credits = models.IntegerField(default=0)
    daily_credits_remaining = models.IntegerField(default=0)

    # Optimistic concurrency control
    version = models.IntegerField(default=0)

    last_monthly_refresh = models.DateTimeField(null=True, blank=True)
    last_daily_refresh = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["user"])]

    def __str__(self):
        return f"{self.user.email} — {self.total_available} credits"

    @property
    def total_available(self) -> int:
        """Sum of all non-expired credit pools plus active grants."""
        base = (
            self.daily_credits_remaining
            + self.monthly_credits_remaining
            + self.addon_credits
            + self.free_credits
        )
        grant_sum = (
            self.grants.filter(
                remaining__gt=0,
            )
            .exclude(
                expires_at__isnull=False,
                expires_at__lt=timezone.now(),
            )
            .aggregate(total=models.Sum("remaining"))["total"]
            or 0
        )
        return base + grant_sum


class CreditGrant(models.Model):
    """Time-limited credit grants from events, promos, or referrals."""

    GRANT_TYPES = [
        ("event", "Event"),
        ("promo", "Promo"),
        ("referral", "Referral"),
        ("campaign", "Campaign"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(
        CreditWallet, on_delete=models.CASCADE, related_name="grants"
    )
    grant_type = models.CharField(max_length=20, choices=GRANT_TYPES)
    amount = models.IntegerField(help_text="Original grant amount")
    remaining = models.IntegerField(help_text="Credits still available")
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="Null means never expires"
    )
    source = models.CharField(
        max_length=100, blank=True, help_text="e.g. 'welcome_event_2026'"
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["wallet", "expires_at"]),
            models.Index(fields=["grant_type"]),
        ]
        ordering = ["expires_at"]

    def __str__(self):
        return f"{self.grant_type}: {self.remaining}/{self.amount}"

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return timezone.now() >= self.expires_at


class CreditHold(models.Model):
    """Pre-authorization hold on credits for an active agent run."""

    HOLD_STATUSES = [
        ("active", "Active"),
        ("settled", "Settled"),
        ("refunded", "Refunded"),
        ("expired", "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(
        CreditWallet, on_delete=models.CASCADE, related_name="holds"
    )
    run = models.OneToOneField(
        "storage.AgentRun", on_delete=models.CASCADE, related_name="credit_hold"
    )
    amount_reserved = models.IntegerField(help_text="Max credits reserved for this run")
    amount_consumed = models.IntegerField(default=0, help_text="Credits actually used")
    status = models.CharField(max_length=20, choices=HOLD_STATUSES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["wallet", "status"]),
            models.Index(fields=["run"]),
        ]

    def __str__(self):
        return f"Hold {self.id!s:.8} — {self.amount_consumed}/{self.amount_reserved} ({self.status})"


class CreditTransaction(models.Model):
    """Immutable ledger entry for every credit movement."""

    CATEGORIES = [
        ("llm", "LLM"),
        ("compute", "Compute"),
        ("integration", "Integration"),
        ("tool", "Tool"),
        ("grant", "Grant"),
        ("refund", "Refund"),
        ("refresh", "Refresh"),
        ("purchase", "Purchase"),
        ("signup_bonus", "Signup Bonus"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(
        CreditWallet, on_delete=models.CASCADE, related_name="transactions"
    )
    hold = models.ForeignKey(
        CreditHold,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    amount = models.IntegerField(help_text="Positive = credit, negative = debit")
    balance_after = models.IntegerField(
        help_text="Wallet total_available after this tx"
    )
    category = models.CharField(max_length=20, choices=CATEGORIES)
    source_type = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. 'openai:gpt-4o', 'e2b:sandbox', 'composio:github'",
    )
    description = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["wallet", "created_at"]),
            models.Index(fields=["category", "created_at"]),
            models.Index(fields=["hold"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        sign = "+" if self.amount >= 0 else ""
        return f"{sign}{self.amount} ({self.category}) — {self.description[:40]}"


class CreditRate(models.Model):
    """Admin-editable rate card for credit pricing."""

    RATE_CATEGORIES = [
        ("llm", "LLM"),
        ("compute", "Compute"),
        ("integration", "Integration"),
        ("tool", "Tool"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=20, choices=RATE_CATEGORIES)
    key = models.CharField(
        max_length=100,
        help_text="e.g. 'default', 'e2b:default', 'composio:standard'",
    )
    credits_per_unit = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        help_text="Credits charged per unit",
    )
    unit = models.CharField(
        max_length=50,
        help_text="'usd' for LLM, 'minute' for compute, 'invocation' for integration",
    )
    markup = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("1.00")
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["category", "key"],
                condition=models.Q(active=True),
                name="unique_active_rate_per_category_key",
            )
        ]

    def __str__(self):
        return (
            f"{self.category}:{self.key} — {self.credits_per_unit} credits/{self.unit}"
        )

    def calculate(self, quantity: float) -> int:
        """Calculate credits for a given quantity of the rated unit."""
        return ceil(float(self.credits_per_unit) * float(self.markup) * quantity)


class CustomerSupportTicket(models.Model):
    """Customer support tickets for user inquiries and issues"""

    STATUS_CHOICES = [
        ("open", "Open"),
        ("in_progress", "In Progress"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]

    id = models.UUIDField(
        editable=False, default=uuid.uuid4, unique=True, primary_key=True
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="support_tickets"
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Customer Support Ticket"
        verbose_name_plural = "Customer Support Tickets"

    def __str__(self):
        return f"{self.user.email} - {self.title} ({self.status})"
