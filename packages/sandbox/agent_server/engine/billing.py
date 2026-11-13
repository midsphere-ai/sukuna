"""Per-tool-call credit billing for the sandbox agent server.

Bills each tool invocation in real-time by writing directly to the backend's
billing tables (CreditWallet, CreditHold, CreditTransaction) using managed=False
Django models.  All operations are fire-and-forget — billing failures never
block agent execution.

Two tool types with different rate cards:
  - **Native exo tools**: category="tool", key="native:default" (1 credit/call)
  - **MCP addon tools**: category="tool", key="mcp:standard" (5 credits/call default)
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from math import ceil
from typing import Any

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from agent_server.models import (
    DjangoAgentRun,
    DjangoCreditHold,
    DjangoCreditRate,
    DjangoCreditTransaction,
    DjangoCreditWallet,
)

log = logging.getLogger("agent_server.billing")

# ── Rate cache ────────────────────────────────────────────────────────────────
# CreditRate rows rarely change; cache them for the process lifetime.

_rate_cache: dict[str, int] = {}
_rate_cache_loaded_at: float = 0.0
_RATE_CACHE_TTL_SECONDS = 300.0  # 5 min

# Fallback rates if CreditRate table is empty or unreachable
_DEFAULT_RATES: dict[str, int] = {
    "native:default": 1,
    "mcp:basic": 2,
    "mcp:standard": 5,
    "mcp:premium": 10,
}

# ── Hold cache (per run_id) ───────────────────────────────────────────────────
# A run has exactly one active CreditHold, created by the backend at run start.
# Cache it to avoid a DB round-trip per tool call.

_hold_cache: dict[str, DjangoCreditHold | None] = {}

# Maximum optimistic lock retries (matches backend credit_service.py)
_MAX_RETRIES = 3


def _load_rates() -> None:
    """Refresh the rate cache from the CreditRate table."""
    global _rate_cache, _rate_cache_loaded_at
    try:
        rows = DjangoCreditRate.objects.filter(category="tool", active=True)
        _rate_cache = {row.key: ceil(float(row.credits_per_unit) * float(row.markup)) for row in rows}
        _rate_cache_loaded_at = time.monotonic()
    except Exception:
        log.debug("Failed to load tool rates from DB, using defaults", exc_info=True)
        _rate_cache = dict(_DEFAULT_RATES)
        _rate_cache_loaded_at = time.monotonic()


def _get_rate(key: str) -> int:
    """Get credits-per-invocation for a tool rate key, with cache."""
    now = time.monotonic()
    if not _rate_cache or (now - _rate_cache_loaded_at) > _RATE_CACHE_TTL_SECONDS:
        _load_rates()
    rate = _rate_cache.get(key)
    if rate is not None:
        return rate
    # Fall back to "native:default" or "mcp:standard" depending on prefix
    prefix = key.split(":")[0] if ":" in key else key
    fallback_key = f"{prefix}:default" if prefix == "native" else f"{prefix}:standard"
    return _rate_cache.get(fallback_key, _DEFAULT_RATES.get(fallback_key, 1))


def _get_hold_for_run(run_id: str) -> DjangoCreditHold | None:
    """Look up the active CreditHold for a run, with caching."""
    if run_id in _hold_cache:
        return _hold_cache[run_id]
    try:
        # The run_id in the hold table is the AgentRun UUID (storage_agentrun.id).
        # The sandbox run_id is stored in storage_agentrun.run_id.
        # We need to look up the hold via the AgentRun's PK.
        from agent_server.models import DjangoAgentRun

        agent_run = (
            DjangoAgentRun.objects.filter(run_id=run_id).order_by("-updated_at").values_list("id", flat=True).first()
        )
        if agent_run is None:
            _hold_cache[run_id] = None
            return None

        hold = DjangoCreditHold.objects.filter(run_id=agent_run, status="active").first()
        _hold_cache[run_id] = hold
        return hold
    except Exception:
        log.debug("Failed to look up CreditHold for run %s", run_id, exc_info=True)
        _hold_cache[run_id] = None
        return None


def clear_hold_cache(run_id: str) -> None:
    """Remove cached hold for a run (call on run completion)."""
    _hold_cache.pop(run_id, None)


@transaction.atomic
def _do_consume_tool(
    hold: DjangoCreditHold,
    credits: int,
    source_type: str,
    description: str,
    metadata: dict[str, Any],
) -> bool:
    """Execute a single tool-call credit deduction with optimistic locking.

    Mirrors the backend's _do_consume() logic: deducts from wallet pools in
    priority order (daily -> monthly -> addon -> free) using the wallet.version
    field for optimistic concurrency control.

    Returns True on success, False on insufficient credits.
    """
    wallet = DjangoCreditWallet.objects.get(pk=hold.wallet_id)
    old_version = wallet.version
    remaining = credits

    # Deduction priority: daily -> monthly -> addon -> free
    # (Skipping event grants for simplicity — they're rare for tool calls)
    daily = wallet.daily_credits_remaining
    monthly = wallet.monthly_credits_remaining
    addon = wallet.addon_credits
    free = wallet.free_credits

    if remaining > 0 and daily > 0:
        take = min(remaining, daily)
        daily -= take
        remaining -= take

    if remaining > 0 and monthly > 0:
        take = min(remaining, monthly)
        monthly -= take
        remaining -= take

    if remaining > 0 and addon > 0:
        take = min(remaining, addon)
        addon -= take
        remaining -= take

    if remaining > 0 and free > 0:
        take = min(remaining, free)
        free -= take
        remaining -= take

    if remaining > 0:
        log.debug("Insufficient credits for tool call (need %d more)", remaining)
        return False

    # Optimistic lock: update only if version hasn't changed
    updated = DjangoCreditWallet.objects.filter(pk=wallet.pk, version=old_version).update(
        version=old_version + 1,
        daily_credits_remaining=daily,
        monthly_credits_remaining=monthly,
        addon_credits=addon,
        free_credits=free,
    )
    if not updated:
        raise _OptimisticLockError()

    # Refresh wallet to get balance_after
    wallet.refresh_from_db()
    balance_after = daily + monthly + addon + free

    # Update hold consumed amount
    DjangoCreditHold.objects.filter(pk=hold.pk).update(amount_consumed=hold.amount_consumed + credits)

    # Create ledger entry
    DjangoCreditTransaction.objects.create(
        id=uuid.uuid4(),
        wallet_id=hold.wallet_id,
        hold_id=hold.pk,
        amount=-credits,
        balance_after=balance_after,
        category="tool",
        source_type=source_type,
        description=description[:200],
        metadata={
            "run_id": str(hold.run_id),
            **metadata,
        },
    )

    return True


class _OptimisticLockError(Exception):
    pass


def _consume_tool_credits(
    hold: DjangoCreditHold,
    credits: int,
    source_type: str,
    description: str,
    metadata: dict[str, Any],
) -> bool:
    """Consume credits with optimistic lock retry."""
    for attempt in range(_MAX_RETRIES):
        try:
            return _do_consume_tool(hold, credits, source_type, description, metadata)
        except _OptimisticLockError:
            if attempt == _MAX_RETRIES - 1:
                log.warning("Optimistic lock failed after %d retries for hold %s", _MAX_RETRIES, hold.pk)
                return False
            continue
    return False


# Regex to detect `exo-mcp tool call <server> <tool>` in shell arguments.
# Captures server_name and tool_name from the command.
_EXO_MCP_CALL_RE = re.compile(r"exo-mcp\s+tool\s+call\s+(\S+)\s+(\S+)", re.IGNORECASE)


def classify_tool_call(
    tool_name: str,
    arguments: str,
    mcp_server_names: set[str] | None,
) -> tuple[str, str, str]:
    """Classify a tool call as native or MCP and extract the real tool identity.

    MCP tools are invoked via the shell tool with `exo-mcp tool call <server> <tool>`
    in the arguments. Native tools show their registered name directly.

    Args:
        tool_name: The tool_name from the streaming event (e.g. "shell", "file").
        arguments: The serialized arguments string from the event payload.
        mcp_server_names: Set of configured MCP server names for this run.

    Returns:
        (tool_type, real_tool_name, matched_server) where:
        - tool_type: "mcp" or "native"
        - real_tool_name: The actual tool being called (e.g. "github.create_issue")
        - matched_server: MCP server name if MCP, empty string for native.
    """
    # Check if this is a shell call invoking exo-mcp
    if tool_name == "shell" and arguments:
        match = _EXO_MCP_CALL_RE.search(arguments)
        if match:
            server_name = match.group(1)
            mcp_tool_name = match.group(2)
            # Verify it's a known MCP server (not some unrelated exo-mcp usage)
            if mcp_server_names and server_name in mcp_server_names:
                return "mcp", f"{server_name}.{mcp_tool_name}", server_name
            # Even if not in our known set, exo-mcp tool call is still an MCP call
            return "mcp", f"{server_name}.{mcp_tool_name}", server_name

    return "native", tool_name, ""


async def bill_tool_call(
    run_id: str,
    tool_name: str,
    is_mcp: bool,
    call_id: str,
    credit_tier: str = "standard",
) -> None:
    """Bill a single tool call invocation.

    Called as a fire-and-forget async task from the event stream.
    All exceptions are caught — billing never blocks agent execution.

    Args:
        run_id: The sandbox run ID (matches DjangoAgentRun.run_id).
        tool_name: Name of the tool being called.
        is_mcp: True if this is an MCP addon tool, False for native exo tool.
        call_id: Unique tool call ID for dedup/tracking.
        credit_tier: MCP billing tier (basic/standard/premium). Ignored for native tools.
    """
    try:
        hold = await sync_to_async(_get_hold_for_run)(run_id)
        if hold is None:
            log.debug("No active hold for run %s, skipping tool billing", run_id)
            return

        if is_mcp:
            rate_key = f"mcp:{credit_tier}"
            source_type = f"mcp:{tool_name}"
        else:
            rate_key = "native:default"
            source_type = f"native:{tool_name}"

        credits = await sync_to_async(_get_rate)(rate_key)
        if credits <= 0:
            return

        description = f"Tool call: {tool_name}"
        metadata = {
            "tool_name": tool_name,
            "call_id": call_id,
            "tool_type": "mcp" if is_mcp else "native",
            "credit_tier": credit_tier if is_mcp else "default",
        }

        success = await sync_to_async(_consume_tool_credits)(hold, credits, source_type, description, metadata)
        if success:
            log.debug(
                "Billed %d credits for tool %s (run=%s, call=%s)",
                credits,
                tool_name,
                run_id,
                call_id,
            )
    except Exception:
        log.debug("Tool billing failed for %s (run=%s)", tool_name, run_id, exc_info=True)


# ═══════════════════════════════════════════════════════════════════════════════
# HOLD LIFECYCLE — ported from backend/apps/billing/credit_service.py
#
# The sandbox now owns the full credit hold lifecycle (previously split: backend
# created, sandbox consumed, backend settled/refunded). These helpers run inside
# the sandbox process against the shared Postgres via shadow ORM.
# ═══════════════════════════════════════════════════════════════════════════════


class InsufficientCreditsError(Exception):
    """Wallet has fewer credits than the requested hold amount."""

    def __init__(self, needed: int, available: int) -> None:
        self.needed = needed
        self.available = available
        super().__init__(f"Insufficient credits: need {needed}, available {available}")


_HOLD_MIN = 20
_HOLD_MAX = 500
_HOLD_DEFAULT = 100
_HOLD_HISTORY_WINDOW = 10


def _wallet_total_available(wallet: DjangoCreditWallet) -> int:
    """Total available credits across all pools (matches backend's CreditWallet.total_available)."""
    return (
        int(getattr(wallet, "daily_credits_remaining", 0))
        + int(getattr(wallet, "monthly_credits_remaining", 0))
        + int(getattr(wallet, "addon_credits", 0))
        + int(getattr(wallet, "free_credits", 0))
    )


def estimate_hold_amount(wallet: DjangoCreditWallet) -> int:
    """Estimate a reasonable hold amount for a new run.

    Ported from backend `CreditService.estimate_hold_amount` — averages the
    last N settled holds' consumed amounts, clamped to [MIN, MAX]. New users
    with no history get the DEFAULT.
    """
    try:
        recent_consumed = list(
            DjangoCreditHold.objects.filter(wallet_id=wallet.pk, status="settled")
            .order_by("-settled_at")
            .values_list("amount_consumed", flat=True)[:_HOLD_HISTORY_WINDOW]
        )
    except Exception:
        log.debug("estimate_hold_amount: failed to load history", exc_info=True)
        return _HOLD_DEFAULT

    if not recent_consumed:
        return _HOLD_DEFAULT

    avg = int(sum(recent_consumed) / len(recent_consumed))
    return max(_HOLD_MIN, min(_HOLD_MAX, avg))


@transaction.atomic
def create_hold(
    *,
    user_id: int,
    agent_run_pk: uuid.UUID,
    estimated_credits: int | None = None,
) -> DjangoCreditHold | None:
    """Create an active CreditHold for a run.

    Resolves the user's wallet, estimates the hold amount if not provided,
    checks balance, then inserts the hold row.

    Returns the created hold on success. Raises InsufficientCreditsError if
    the wallet balance is below the estimated amount. Returns None if the
    user has no wallet (single-user dev or pre-billing accounts).
    """
    wallet = DjangoCreditWallet.objects.filter(user_id=user_id).order_by("-pk").first()
    if wallet is None:
        log.info("No wallet for user %s — skipping hold creation", user_id)
        return None

    amount = estimated_credits if estimated_credits is not None else estimate_hold_amount(wallet)
    available = _wallet_total_available(wallet)
    if available < amount:
        raise InsufficientCreditsError(needed=amount, available=available)

    hold_id = uuid.uuid4()
    now = timezone.now()
    hold = DjangoCreditHold.objects.create(
        id=hold_id,
        wallet_id=wallet.pk,
        run_id=agent_run_pk,
        amount_reserved=amount,
        amount_consumed=0,
        status="active",
        created_at=now,
    )
    log.info(
        "Created CreditHold %s (user=%s, run=%s, reserved=%d)",
        hold_id,
        user_id,
        agent_run_pk,
        amount,
    )
    return hold


@transaction.atomic
def settle_hold_for_run(sandbox_run_id: str) -> None:
    """Settle the active hold for a sandbox run. No-op if already settled."""
    agent_run_pk = (
        DjangoAgentRun.objects.filter(run_id=sandbox_run_id)
        .order_by("-updated_at")
        .values_list("id", flat=True)
        .first()
    )
    if agent_run_pk is None:
        return

    hold = DjangoCreditHold.objects.select_for_update().filter(run_id=agent_run_pk, status="active").first()
    if hold is None:
        return

    hold.status = "settled"
    hold.settled_at = timezone.now()
    hold.save(update_fields=["status", "settled_at"])
    clear_hold_cache(sandbox_run_id)
    log.info(
        "Settled hold %s: consumed %d / reserved %d",
        hold.pk,
        hold.amount_consumed,
        hold.amount_reserved,
    )


@transaction.atomic
def refund_hold_for_run(sandbox_run_id: str, reason: str = "") -> None:
    """Refund consumed credits on the active hold and mark it refunded.

    Used when a run fails or is cancelled — returns the credits the agent
    actually consumed back to the wallet's monthly pool and records a refund
    ledger entry.
    """
    agent_run_pk = (
        DjangoAgentRun.objects.filter(run_id=sandbox_run_id)
        .order_by("-updated_at")
        .values_list("id", flat=True)
        .first()
    )
    if agent_run_pk is None:
        return

    hold = DjangoCreditHold.objects.select_for_update().filter(run_id=agent_run_pk, status="active").first()
    if hold is None:
        return

    refund_amount = int(hold.amount_consumed or 0)
    if refund_amount > 0:
        wallet = DjangoCreditWallet.objects.select_for_update().get(pk=hold.wallet_id)
        wallet.monthly_credits_remaining += refund_amount
        wallet.save(update_fields=["monthly_credits_remaining", "updated_at"])
        balance_after = _wallet_total_available(wallet)
        DjangoCreditTransaction.objects.create(
            id=uuid.uuid4(),
            wallet_id=wallet.pk,
            hold_id=hold.pk,
            amount=refund_amount,
            balance_after=balance_after,
            category="refund",
            source_type="platform",
            description=(f"Refund: {reason[:150]}" if reason else "Credit refund"),
            metadata={"run_id": str(sandbox_run_id), "reason": reason},
        )

    hold.status = "refunded"
    hold.settled_at = timezone.now()
    hold.save(update_fields=["status", "settled_at"])
    clear_hold_cache(sandbox_run_id)
    log.info("Refunded hold %s: %d credits returned", hold.pk, refund_amount)
