"""Credit system service layer.

Handles all credit operations: wallet management, holds, consumption,
settlement, refunds, and credit calculations.
"""

import logging
from math import ceil

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .errors import InsufficientCreditsError, OptimisticLockError
from .models import (
    CreditGrant,
    CreditHold,
    CreditRate,
    CreditTransaction,
    CreditWallet,
    SubscriptionPlan,
)

logger = logging.getLogger(__name__)

# Default credit grants per plan tier
PLAN_CREDITS = {
    "free": 300,
    "basic": 3500,
    "premium": 12000,
}

SIGNUP_BONUS = 150

# Fallback rates if CreditRate table is empty
DEFAULT_LLM_MARKUP = 2.0
DEFAULT_COMPUTE_CREDITS_PER_MINUTE = 8
DEFAULT_INTEGRATION_TIERS = {
    "basic": 2,
    "standard": 5,
    "premium": 10,
}

MAX_OPTIMISTIC_RETRIES = 3


class CreditService:
    """Service for all credit wallet operations."""

    # ── Wallet Management ──────────────────────────────────────────────────

    @staticmethod
    def get_or_create_wallet(user) -> CreditWallet:
        """Get existing wallet or create one with signup bonus and plan grant."""
        wallet, created = CreditWallet.objects.get_or_create(
            user=user,
            defaults=_wallet_defaults_for_user(user),
        )
        if created:
            _record_signup_bonus(wallet)
            logger.info("Created credit wallet for user %s", user.email)
        return wallet

    @staticmethod
    def sync_wallet_to_plan(wallet: CreditWallet, plan: SubscriptionPlan) -> None:
        """Update wallet monthly credits when plan changes."""
        credits = plan.monthly_credits or PLAN_CREDITS.get(plan.tier, 0)
        wallet.monthly_credits = credits
        wallet.monthly_credits_remaining = credits
        wallet.last_monthly_refresh = timezone.now()
        wallet.save(
            update_fields=[
                "monthly_credits",
                "monthly_credits_remaining",
                "last_monthly_refresh",
                "updated_at",
            ]
        )

    # ── Hold Lifecycle ─────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def create_hold(wallet: CreditWallet, run, estimated_credits: int) -> CreditHold:
        """Reserve credits for an upcoming agent run.

        Args:
            wallet: The user's credit wallet.
            run: The AgentRun instance.
            estimated_credits: Maximum credits to reserve.

        Returns:
            The created CreditHold.

        Raises:
            InsufficientCreditsError: If wallet balance < estimated_credits.
        """
        wallet = CreditWallet.objects.select_for_update().get(pk=wallet.pk)
        available = wallet.total_available
        if available < estimated_credits:
            raise InsufficientCreditsError(
                needed=estimated_credits, available=available
            )
        return CreditHold.objects.create(
            wallet=wallet,
            run=run,
            amount_reserved=estimated_credits,
            amount_consumed=0,
            status="active",
        )

    @staticmethod
    @transaction.atomic
    def settle(hold: CreditHold) -> None:
        """Settle a hold after task completion. Releases unused reservation."""
        hold = CreditHold.objects.select_for_update().get(pk=hold.pk)
        if hold.status != "active":
            logger.warning(
                "Attempted to settle non-active hold %s (status=%s)",
                hold.pk,
                hold.status,
            )
            return
        hold.status = "settled"
        hold.settled_at = timezone.now()
        hold.save(update_fields=["status", "settled_at"])
        logger.info(
            "Settled hold %s: consumed %d / reserved %d",
            hold.pk,
            hold.amount_consumed,
            hold.amount_reserved,
        )

    @staticmethod
    @transaction.atomic
    def refund(hold: CreditHold, reason: str = "") -> CreditTransaction | None:
        """Refund all consumed credits for a hold (platform failure / cancellation)."""
        hold = CreditHold.objects.select_for_update().get(pk=hold.pk)
        if hold.status != "active":
            logger.warning(
                "Attempted to refund non-active hold %s (status=%s)",
                hold.pk,
                hold.status,
            )
            return None
        refund_amount = hold.amount_consumed
        if refund_amount > 0:
            wallet = CreditWallet.objects.select_for_update().get(pk=hold.wallet_id)
            wallet.monthly_credits_remaining += refund_amount
            wallet.save(update_fields=["monthly_credits_remaining", "updated_at"])
            tx = CreditTransaction.objects.create(
                wallet=wallet,
                hold=hold,
                amount=refund_amount,
                balance_after=wallet.total_available,
                category="refund",
                source_type="platform",
                description=f"Refund: {reason[:150]}" if reason else "Credit refund",
                metadata={"run_id": str(hold.run_id), "reason": reason},
            )
        else:
            tx = None
        hold.status = "refunded"
        hold.settled_at = timezone.now()
        hold.save(update_fields=["status", "settled_at"])
        logger.info("Refunded hold %s: %d credits returned", hold.pk, refund_amount)
        return tx

    # ── Credit Consumption ─────────────────────────────────────────────────

    @staticmethod
    def consume(
        hold: CreditHold,
        category: str,
        amount: int,
        source_type: str = "",
        description: str = "",
        metadata: dict | None = None,
    ) -> CreditTransaction | None:
        """Deduct credits from wallet in priority order.

        Uses optimistic locking on wallet.version to handle concurrent
        deductions without pessimistic locks on the hot path.

        Returns the CreditTransaction, or None if amount is 0.
        """
        if amount <= 0:
            return None
        if hold.status != "active":
            logger.warning("Consume on non-active hold %s, skipping", hold.pk)
            return None

        for attempt in range(MAX_OPTIMISTIC_RETRIES):
            try:
                return _do_consume(
                    hold, category, amount, source_type, description, metadata or {}
                )
            except OptimisticLockError:
                if attempt == MAX_OPTIMISTIC_RETRIES - 1:
                    logger.error(
                        "Optimistic lock failed after %d retries for wallet %s",
                        MAX_OPTIMISTIC_RETRIES,
                        hold.wallet_id,
                    )
                    raise
                continue
        return None

    # ── Monthly Refresh ────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def refresh_monthly(wallet: CreditWallet) -> CreditTransaction:
        """Reset monthly credits to plan grant amount."""
        wallet = CreditWallet.objects.select_for_update().get(pk=wallet.pk)
        wallet.monthly_credits_remaining = wallet.monthly_credits
        wallet.last_monthly_refresh = timezone.now()
        wallet.save(
            update_fields=[
                "monthly_credits_remaining",
                "last_monthly_refresh",
                "updated_at",
            ]
        )
        return CreditTransaction.objects.create(
            wallet=wallet,
            amount=wallet.monthly_credits,
            balance_after=wallet.total_available,
            category="refresh",
            source_type="monthly",
            description=f"Monthly credit refresh: {wallet.monthly_credits} credits",
        )

    # ── Add-on Purchase ────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def purchase_addon_pack(
        wallet: CreditWallet, amount_credits: int, payment_metadata: dict | None = None
    ) -> CreditTransaction:
        """Add purchased credits to the wallet's addon pool."""
        wallet = CreditWallet.objects.select_for_update().get(pk=wallet.pk)
        wallet.addon_credits += amount_credits
        wallet.save(update_fields=["addon_credits", "updated_at"])
        return CreditTransaction.objects.create(
            wallet=wallet,
            amount=amount_credits,
            balance_after=wallet.total_available,
            category="purchase",
            source_type="addon_pack",
            description=f"Purchased {amount_credits} credits",
            metadata=payment_metadata or {},
        )

    # ── Credit Calculation Helpers ─────────────────────────────────────────

    @staticmethod
    def calculate_llm_credits(cost_usd: float, is_byom: bool = False) -> int:
        """Convert LLM provider cost to credits.

        Formula: ceil(cost_usd * markup * 1000)
        BYOM users pay 0 LLM credits.
        """
        if is_byom or cost_usd <= 0:
            return 0
        rate = _get_rate("llm", "default")
        if rate:
            return rate.calculate(cost_usd)
        return ceil(cost_usd * DEFAULT_LLM_MARKUP * 1000)

    @staticmethod
    def calculate_compute_credits(duration_seconds: float) -> int:
        """Convert sandbox compute time to credits.

        Formula: ceil(minutes * 8)
        """
        if duration_seconds <= 0:
            return 0
        minutes = duration_seconds / 60
        rate = _get_rate("compute", "e2b:default")
        if rate:
            return rate.calculate(minutes)
        return ceil(minutes * DEFAULT_COMPUTE_CREDITS_PER_MINUTE)

    @staticmethod
    def calculate_integration_credits(credit_tier: str = "standard") -> int:
        """Get credits for a single integration invocation by tier."""
        rate = _get_rate("integration", f"composio:{credit_tier}")
        if rate:
            return int(rate.credits_per_unit)
        return DEFAULT_INTEGRATION_TIERS.get(credit_tier, 5)

    @staticmethod
    def calculate_tool_credits(tool_type: str = "native", tier: str = "default") -> int:
        """Get credits for a single tool call invocation.

        Args:
            tool_type: "native" for exo CLI tools, "mcp" for MCP addon tools.
            tier: For MCP tools: "basic" (2), "standard" (5), "premium" (10).
                  Ignored for native tools.
        """
        key = f"{tool_type}:{tier}"
        rate = _get_rate("tool", key)
        if rate:
            return rate.calculate(1)
        # Fallback defaults
        defaults = {
            "native:default": 1,
            "mcp:basic": 2,
            "mcp:standard": 5,
            "mcp:premium": 10,
        }
        return defaults.get(key, 1)

    # ── Query Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def get_hold_for_run(run) -> CreditHold | None:
        """Get the active credit hold for a run, if any."""
        return CreditHold.objects.filter(run=run, status="active").first()

    @staticmethod
    def estimate_hold_amount(wallet: CreditWallet) -> int:
        """Estimate hold credits based on the user's last 10 settled holds.

        Returns the average consumption rounded up, with a floor of 20 and
        a cap of 500.  Falls back to 100 if no history exists.
        """
        recent_holds = (
            CreditHold.objects.filter(
                wallet=wallet,
                status="settled",
                amount_consumed__gt=0,
            )
            .order_by("-settled_at")[:10]
            .values_list("amount_consumed", flat=True)
        )
        consumed = list(recent_holds)
        if not consumed:
            return 100  # default for new users
        avg = ceil(sum(consumed) / len(consumed))
        return max(20, min(avg, 500))

    @staticmethod
    def get_usage_summary(wallet: CreditWallet, days: int = 30) -> dict:
        """Aggregate credit usage by category over the last N days."""
        since = timezone.now() - timezone.timedelta(days=days)
        rows = (
            CreditTransaction.objects.filter(
                wallet=wallet,
                amount__lt=0,
                created_at__gte=since,
            )
            .values("category")
            .annotate(total=Sum("amount"))
        )
        return {row["category"]: abs(row["total"]) for row in rows}


# ── Private Helpers ────────────────────────────────────────────────────────────


def _wallet_defaults_for_user(user) -> dict:
    """Build default field values for a new CreditWallet."""
    plan_credits = 0
    try:
        subscription = user.subscription
        if subscription and subscription.plan:
            plan_credits = subscription.plan.monthly_credits or PLAN_CREDITS.get(
                subscription.plan.tier, 0
            )
    except Exception:
        pass
    return {
        "monthly_credits": plan_credits,
        "monthly_credits_remaining": plan_credits,
        "free_credits": SIGNUP_BONUS,
        "last_monthly_refresh": timezone.now(),
    }


def _record_signup_bonus(wallet: CreditWallet) -> None:
    """Record the signup bonus as a transaction."""
    if wallet.free_credits > 0:
        CreditTransaction.objects.create(
            wallet=wallet,
            amount=wallet.free_credits,
            balance_after=wallet.total_available,
            category="signup_bonus",
            source_type="signup",
            description=f"Signup bonus: {wallet.free_credits} credits",
        )


@transaction.atomic
def _do_consume(
    hold: CreditHold,
    category: str,
    amount: int,
    source_type: str,
    description: str,
    metadata: dict,
) -> CreditTransaction:
    """Execute a single credit deduction with optimistic locking.

    Deduction priority: event grants -> daily -> monthly -> addon -> free.
    """
    wallet = CreditWallet.objects.get(pk=hold.wallet_id)
    old_version = wallet.version
    remaining = amount

    # 1. Event grants (expiring soonest first)
    if remaining > 0:
        grants = (
            CreditGrant.objects.select_for_update()
            .filter(
                wallet=wallet,
                remaining__gt=0,
                expires_at__isnull=False,
                expires_at__gt=timezone.now(),
            )
            .order_by("expires_at")
        )
        for grant in grants:
            if remaining <= 0:
                break
            take = min(remaining, grant.remaining)
            grant.remaining -= take
            grant.save(update_fields=["remaining"])
            remaining -= take

    # 2. Daily credits
    if remaining > 0 and wallet.daily_credits_remaining > 0:
        take = min(remaining, wallet.daily_credits_remaining)
        wallet.daily_credits_remaining -= take
        remaining -= take

    # 3. Monthly credits
    if remaining > 0 and wallet.monthly_credits_remaining > 0:
        take = min(remaining, wallet.monthly_credits_remaining)
        wallet.monthly_credits_remaining -= take
        remaining -= take

    # 4. Add-on credits (purchased, never expire)
    if remaining > 0 and wallet.addon_credits > 0:
        take = min(remaining, wallet.addon_credits)
        wallet.addon_credits -= take
        remaining -= take

    # 5. Free credits (signup bonus, never expire)
    if remaining > 0 and wallet.free_credits > 0:
        take = min(remaining, wallet.free_credits)
        wallet.free_credits -= take
        remaining -= take

    if remaining > 0:
        raise InsufficientCreditsError(needed=amount, available=amount - remaining)

    # Optimistic lock: update only if version hasn't changed
    updated = CreditWallet.objects.filter(pk=wallet.pk, version=old_version).update(
        version=old_version + 1,
        daily_credits_remaining=wallet.daily_credits_remaining,
        monthly_credits_remaining=wallet.monthly_credits_remaining,
        addon_credits=wallet.addon_credits,
        free_credits=wallet.free_credits,
    )
    if not updated:
        raise OptimisticLockError()

    # Refresh wallet to get updated version for balance_after
    wallet.refresh_from_db()

    # Update hold consumed amount
    CreditHold.objects.filter(pk=hold.pk).update(
        amount_consumed=hold.amount_consumed + amount
    )
    hold.amount_consumed += amount

    return CreditTransaction.objects.create(
        wallet=wallet,
        hold=hold,
        amount=-amount,
        balance_after=wallet.total_available,
        category=category,
        source_type=source_type,
        description=description,
        metadata={
            "run_id": str(hold.run_id),
            **metadata,
        },
    )


def _get_rate(category: str, key: str) -> CreditRate | None:
    """Look up an active rate card entry, with fallback to 'default' key."""
    rate = CreditRate.objects.filter(category=category, key=key, active=True).first()
    if rate is None and key != "default":
        rate = CreditRate.objects.filter(
            category=category, key="default", active=True
        ).first()
    return rate
