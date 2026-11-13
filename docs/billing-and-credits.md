# Billing & Credit System

This document describes how billing works on the Midsphere / sukuna platform. It replaces the old hard-limit billing (weekly task caps, sandbox-second quotas) with a universal **credit** unit that meters LLM spend, sandbox compute time, tool calls, and integration invocations against the same pool.

This document describes the system as it is today.

---

## 1. Concepts

### 1.1 The credit

- **1 credit ≈ $0.001 USD of gross LLM cost at the default 2.0× markup.**
  - `ceil(provider_cost_usd * 2.0 * 1000)` is the LLM conversion formula.
- Credits are whole integers. All rate calculations use `math.ceil`, so partial credits always round up in the platform's favour.
- Credits never expire *unless* they come from an event/promo grant with an explicit `expires_at`.

### 1.2 Wallets, pools, and priority

Every user has exactly one `CreditWallet` (`apps/billing/models.py:549`). A wallet is a sum of five pools plus any active grants:

| Pool | Source | Resets? | Notes |
|------|--------|---------|-------|
| `monthly_credits_remaining` | Plan grant | On billing cycle | `monthly_credits` is the ceiling the pool refreshes to |
| `addon_credits` | Paid add-on packs | Never | Purchased 1,000-credit packs for $2.50 each |
| `free_credits` | One-time signup bonus | Never | 150 credits on first wallet creation |
| `daily_credits_remaining` | Optional daily allowance | Daily (if used) | Not currently granted to any plan — reserved for experiments |
| `CreditGrant` rows | Events / promos / referrals / campaigns | Expires at `expires_at` | Deducted soonest-expiring first |

**Deduction priority** when consuming credits (`credit_service.py:374` `_do_consume`):

```
event grants (soonest expiry first)
  → daily_credits_remaining
  → monthly_credits_remaining
  → addon_credits
  → free_credits
```

If every pool is empty after a consume attempt, `InsufficientCreditsError` is raised with `needed` and `available` fields.

**`wallet.total_available`** is a computed property (`models.py:588`) that sums all four hard pools plus the remaining balance on every non-expired, non-zero `CreditGrant`. This is the number you see in the UI, and the number that the pre-run enforcement gate checks.

### 1.3 Holds — pre-authorisation per run

Every agent run creates exactly one `CreditHold` row, `OneToOne` with `storage.AgentRun` (`models.py:653`). A hold has four statuses:

- `active` — created at run start, reserving `amount_reserved` credits.
- `settled` — run completed normally. Unused reservation is released.
- `refunded` — run failed/cancelled. Any `amount_consumed` is returned to `monthly_credits_remaining`.
- `expired` — reaper-marked holds from abandoned runs (no live reaper wires this today, reserved for future).

During a run, each LLM / compute / tool / integration consumption writes a negative `CreditTransaction`, decrements the appropriate wallet pool(s), and increments `hold.amount_consumed`. `amount_consumed` is a monotonic watermark; it can exceed `amount_reserved` (the reservation is a soft estimate, not a cap).

### 1.4 The ledger

`CreditTransaction` (`models.py:687`) is an **append-only** ledger. There are no updates or deletes — every movement, positive or negative, appends a row. Each row captures:

- `amount` — positive for credits in, negative for debits.
- `balance_after` — wallet `total_available` *immediately after* this transaction. Gives you replayable balance history without re-summing pools.
- `category` — one of `llm`, `compute`, `integration`, `tool`, `grant`, `refund`, `refresh`, `purchase`, `signup_bonus`.
- `source_type` — free-form string like `openai:gpt-4o`, `e2b:sandbox`, `composio:github`, `mcp:github.create_issue`, `native:shell`, `platform`, `monthly`, `signup`, `addon_pack`.
- `hold` — nullable FK to the `CreditHold` that caused this transaction. `refresh` / `purchase` / `signup_bonus` rows have no hold.
- `metadata` — JSON: always includes `run_id` for hold-linked transactions, plus category-specific fields (`cost_usd`, `call_id`, `tool_name`, `reason` for refunds, `payment_id` for purchases).

Indexes on `(wallet, created_at)`, `(category, created_at)`, and `hold` support the billing-page history view and admin reporting.

---

## 2. The rate card

Pricing is a database table (`CreditRate`, `models.py:738`) so product can edit rates without a deploy. Every row is `(category, key, credits_per_unit, unit, markup, active)` with a unique constraint on `(category, key)` where `active=True`.

Lookups fall back to `key="default"` within the same category if the exact key isn't found (`credit_service.py:473`). Seeded by `apps/billing/management/commands/seed_credit_rates.py`:

| Category      | Key                  | Rate | Unit         | Formula                                  |
|---------------|----------------------|------|--------------|------------------------------------------|
| `llm`         | `default`            | 2000 | `usd`        | `ceil(cost_usd * 2.0 * 1000)` credits    |
| `compute`     | `e2b:default`        | 8    | `minute`     | `ceil(minutes * 8)` credits              |
| `integration` | `composio:basic`     | 2    | `invocation` | Per Composio call at basic tier          |
| `integration` | `composio:standard`  | 5    | `invocation` | Default Composio tier                    |
| `integration` | `composio:premium`   | 10   | `invocation` | Premium-tier addon                       |
| `tool`        | `native:default`     | 1    | `invocation` | Exo-native tool calls (shell, file, …)   |
| `tool`        | `mcp:basic`          | 2    | `invocation` | Basic-tier MCP addon tool                |
| `tool`        | `mcp:standard`       | 5    | `invocation` | Default MCP addon tool tier              |
| `tool`        | `mcp:premium`        | 10   | `invocation` | Premium-tier MCP addon tool              |

**BYOM** (bring-your-own-model) users — detected via `UserProviderConfig` — pay **0** LLM credits. They still pay compute and tool credits.

**Tier resolution** for tool calls: when a run is provisioned, each installed addon carries a `credit_tier` (from `MarketplaceAddon` / `UserMarketplaceAddons`). The sandbox reads `addon_credit_tiers` from run metadata, so a `github` MCP server tagged `premium` bills at 10 credits/call while a `slack` MCP server tagged `basic` bills at 2.

If the rate table is somehow empty or unreachable, calculation falls through to hard-coded defaults (`credit_service.py:36-42` and `engine/billing.py:44-49`) — the code never crashes on missing rates.

### 2.1 Plan grants

```python
# credit_service.py:27-33
PLAN_CREDITS = {
    "free":    300,
    "basic":   3500,
    "premium": 12000,
}
SIGNUP_BONUS = 150
```

`SubscriptionPlan.monthly_credits` on the row, if set, overrides the hard-coded dict. This lets support grant bespoke plans through the admin without a code change.

Add-on pack: **1,000 credits for $2.50**, never expire, deposited to `addon_credits`.

---

## 3. The hold lifecycle

### 3.1 Creation — sandbox owns this

Since the backend purge, **hold creation runs inside the sandbox**, not the Django backend. Flow:

1. Frontend calls `POST /api/v1/chat/sandbox/acquire` on Django. Django provisions an E2B sandbox, mints a JWT, returns `{sandbox_host, jwt}`.
2. Frontend calls `POST /runs/start` directly on the sandbox with bearer JWT.
3. Sandbox (`packages/sandbox/agent_server/api/runs.py:start_run`) resolves the toolkit, DLP-scans the task, then calls `engine.billing.create_hold(user_id, agent_run_pk, estimated_credits=None)` (`engine/billing.py:400`).
4. `create_hold`:
   - Loads the user's wallet via the shadow ORM (`DjangoCreditWallet`, `managed=False`, same Postgres).
   - If the user has no wallet (legacy / dev single-user), logs and returns `None` — the run proceeds unmetered.
   - Calls `estimate_hold_amount(wallet)` if the caller didn't override.
   - If `available < amount`, raises `InsufficientCreditsError`. The route handler returns **HTTP 402** with a message the frontend maps to its "Credits exhausted" modal.
   - Otherwise inserts a `DjangoCreditHold` row with `status="active"` and `amount_reserved=amount`.

### 3.2 Smart estimation

`estimate_hold_amount` (`engine/billing.py:374`, mirrored at `credit_service.py:300`):

- Reads the `amount_consumed` of the user's last 10 `settled` holds, ordered by `settled_at DESC`.
- Returns `max(20, min(500, ceil(avg)))`.
- Returns **100** (the `_HOLD_DEFAULT`) if the user has no settled-hold history.

The [20, 500] clamp keeps reservations sensible: a new user can't be blocked by an outlier, and a runaway hold on one user doesn't starve another request.

### 3.3 Consumption during the run

Holds are consumed asynchronously, fire-and-forget, from four code paths:

**LLM** (`apps/agents/streaming.py:_consume_llm_credits`):
- The sandbox streams SSE events that include `usage` events carrying `cost_usd` cumulatively.
- The backend's proxy used to sit here — post-purge, the sandbox consumes directly as the run loop emits usage events.
- Cost delta since last tick → `CreditService.calculate_llm_credits(delta, is_byom)` → `CreditService.consume(hold, "llm", credits, source_type="openai:gpt-4o", ...)`.
- Fire-and-forget via `asyncio.create_task`. Billing failure → warning log → execution continues.

**Compute** (`apps/agents/models.py:E2bSandbox._record_billing_usage`):
- The E2B sandbox tracks wall-clock seconds of the user's active sandbox session.
- On teardown, `duration_seconds` → `CreditService.calculate_compute_credits(duration_seconds)` → `consume(hold, "compute", credits, source_type="e2b:sandbox")`.

**Tool calls** (`packages/sandbox/agent_server/engine/billing.py:bill_tool_call`, 285):
- Run loop (`engine/run.py:565`) forwards each `tool_call` / `tool_result` event into `bill_tool_call(run_id, tool_name, is_mcp, call_id, credit_tier)`.
- `classify_tool_call` (`engine/billing.py:249`) inspects the arguments. If the tool is `shell` and the arguments match `exo-mcp tool call <server> <tool>`, the call is classified as `mcp` and the real tool name is extracted — this is how MCP addon tools get billed even though they're invoked *through* the shell tool.
- Native tools hit `native:default` (1 credit). MCP tools hit `mcp:{tier}` (2/5/10). The hold + rate lookup are cached per-process for 5 minutes to avoid DB round-trips on every tool call.

**Integrations** (Composio): deferred in Phase 2. Currently covered indirectly by the `mcp:*` path when the integration is exposed as an MCP server.

Consumption uses **optimistic concurrency** (`credit_service.py:_do_consume`, `engine/billing.py:_do_consume_tool`):

1. Read `wallet.version`.
2. Walk the five pools in priority order, computing new values in memory.
3. `UPDATE credit_wallet SET version = version + 1, <new pool values> WHERE pk = ? AND version = <old>` — if zero rows affected, another consumer beat us; retry up to 3 times.
4. On success, append the `CreditTransaction` and bump `hold.amount_consumed`.

Wallet reads under `SELECT … FOR UPDATE` are used only on the slow paths (hold creation, settlement, refund) where contention is low and correctness matters more than latency. The hot path (per-tool-call billing) stays lock-free.

### 3.4 Settlement and refund — sandbox owns these too

`infra/sync.py` observes run terminal state events:

- `sync_run_completed` → `engine/billing.py:settle_hold_for_run(sandbox_run_id)` (`engine/billing.py:449`). Marks hold `settled`, records `settled_at = now()`, clears the per-run cache. **No refund on success**: consumed credits stay consumed; unused reservation is simply released.
- `sync_run_failed` / `sync_run_cancelled` → `refund_hold_for_run(sandbox_run_id, reason)` (`engine/billing.py:481`). Any `amount_consumed > 0` is returned to `monthly_credits_remaining` via a single wallet update + a positive-amount `CreditTransaction` with `category="refund"`, `source_type="platform"`. Hold status → `refunded`.

Refund policy: **all consumed credits** are returned when the platform is at fault (crash, cancellation, timeout). The user pays nothing for a run they didn't get to keep. This is blunter than the actual-usage-only model some vendors use, but it avoids arguing with users about partial results and is economically cheap at our volumes.

---

## 4. Enforcement

### 4.1 The pre-run gate

This is the **only hard enforcement** on the platform today.

In the sandbox's `create_hold`:

```
available = wallet.daily_rem + wallet.monthly_rem + wallet.addon + wallet.free
if available < amount:
    raise InsufficientCreditsError(needed=amount, available=available)
```

The start-run route handler translates that into `HTTP 402`. The frontend (`lib/stores/usageLimit.ts`) pattern-matches `/insufficient credits/i` and opens `UsageLimitModal` with the "Credits exhausted" variant and a **Buy Credits** CTA deep-linking to `/billing`.

**Legacy accounts without a wallet are never blocked.** In dev / single-user mode the wallet is simply absent and `create_hold` returns `None`; the run proceeds unmetered. In production every user gets a wallet via the signup signal (`signals.py:16`), so this branch is reserved for database-seeded demo accounts and migrations.

### 4.2 No mid-run kill

Because consumption is fire-and-forget and wrapped in try/except, a run that exceeds its reservation **is not killed**. The hold's `amount_consumed` simply goes above `amount_reserved`, and the wallet deducts down through its pools until one of them is empty. At that point consume raises `InsufficientCreditsError` which is swallowed — subsequent tool calls stop costing credits but the agent keeps running. This is deliberate: a half-finished run with no billing is worse than a billable overrun.

### 4.3 No post-hoc overdraft recovery

If a user's wallet goes to zero mid-run, we eat the difference. There is no "negative balance" state and no collections path. The gate runs once, at run start.

---

## 5. Subscriptions & plans

`SubscriptionPlan` (`models.py:289`) defines three tiers:

- **Free** — `$0/mo`, 300 credits/mo.
- **Basic / Lite** — `$5/mo`, 3,500 credits/mo.
- **Premium / Pro** — `$19/mo`, 12,000 credits/mo.

Each row carries `dodo_product_id` pointing at a Dodo Payments product.

`UserSubscription` (`models.py:345`) is `OneToOne` with `User` and holds:

- `dodo_subscription_id`, `dodo_customer_id` — links to Dodo.
- `status` — `active`, `cancelled`, `expired`, `pending`.
- `start_date`, `end_date` — current billing cycle boundaries.
- `auto_renew`, `grace_period_end` — retry behaviour on failed charges.
- `scheduled_plan_change`, `scheduled_change_date` — queued downgrade/upgrade, applied by a Celery task at the scheduled time.

### 5.1 Wallet synchronisation

A `post_save` signal on `UserSubscription` (`signals.py:16`):

1. Calls `CreditService.get_or_create_wallet(user)` — idempotent; creates wallet + records signup bonus transaction on first save.
2. If the row wasn't just created but the plan changed, calls `CreditService.sync_wallet_to_plan(wallet, plan)` — updates `monthly_credits` and `monthly_credits_remaining` to the new plan's amount.

This means: subscribing to Pro immediately bumps the user's monthly pool to 12,000 and refreshes `last_monthly_refresh`. Downgrading does the same in reverse (and can leave a user with `monthly_credits_remaining > monthly_credits`, which is fine — they keep what they already had).

### 5.2 Monthly refresh

The `CreditService.refresh_monthly(wallet)` method (`credit_service.py:198`) resets `monthly_credits_remaining` to `monthly_credits` and logs a `category="refresh"` transaction. It is **not currently bound to a Celery Beat schedule** — the old billing `CLAUDE.md` references four credit Celery tasks (`refresh_monthly_credits`, `expire_credit_grants`, `settle_orphaned_holds`, `credit_usage_alerts`), but none of those exist in `tasks.py` today. In practice, the refresh happens through the subscription renewal path: the `subscription.charged` webhook extends `end_date` by 30 days and, if the signal logic is expanded to call `refresh_monthly`, resets the pool.

> **Known gap.** If you're debugging why a user's monthly pool didn't refresh, check that the webhook path or a manual admin action called `refresh_monthly`. This is scheduled to be automated in a follow-up.

### 5.3 Add-on pack purchases

`POST /billing/credits/purchase` (`views.py:531`) with `{ packs: N }` where `N ∈ [1, 10]`:

1. Builds a Dodo Payments checkout session for `DODO_ADDON_PACK_PRODUCT_ID × N`.
2. Returns `checkout_url` to the frontend, which launches the Dodo-hosted checkout.
3. On webhook `payment.succeeded`, the backend calls `CreditService.purchase_addon_pack(wallet, N × 1000, payment_metadata)` which:
   - Adds `N × 1000` to `addon_credits`.
   - Appends a `category="purchase"`, `source_type="addon_pack"` transaction with the Dodo `payment_id` in metadata.

Add-on credits **never expire** and are consumed *after* monthly credits — i.e., they're the strategic reserve, not the first-spent pool.

---

## 6. Dodo Payments integration

All third-party payment state lives behind Dodo. The client is constructed lazily (`tasks.py:27`, `service.py:54`) so settings aren't required at import time, which matters for tests.

### 6.1 Subscription creation

`apps/billing/service.py:create_subscription_with_checks`:

- **Free plan**: creates the `UserSubscription` locally with `status="active"`, no Dodo call.
- **Paid plan**:
  1. `dodo_client.customers.create()` → Dodo customer ID.
  2. `dodo_client.checkout_sessions.create()` with `product_id = plan.dodo_product_id` → checkout URL.
  3. Returns `{ checkout_url, subscription_id }`. Frontend redirects the user.
  4. On `subscription.activated` webhook, status flips from `pending` → `active`, `end_date` set to `now + 30 days`.

### 6.2 Webhook handler

`POST /billing/webhook` is the single endpoint Dodo calls. The handler:

1. Verifies the signature via `dodo_client.webhooks.unwrap(payload, headers)` (HMAC-SHA256 over the raw body).
2. Idempotency: inserts the event ID into `WebhookEvent`. If it already exists, returns 200 without processing.
3. Dispatches by event type:

| Event | Action |
|-------|--------|
| `subscription.activated` | Set `status="active"`, stamp `start_date`, `end_date = now + 30d` |
| `subscription.charged` | Extend `end_date` by 30 days (renewal) |
| `subscription.cancelled` | Set `status="cancelled"` |
| `subscription.completed` | Set `status="expired"` |
| `payment.failed` | Insert `FailedPayment`, set `grace_period_end` |
| `payment.succeeded` (addon pack) | Call `CreditService.purchase_addon_pack` |
| `refund.processed` | Set `status="refunded"`, cascade to subscription cancel |

### 6.3 Retries and grace periods

`tasks.py:retry_failed_payments` and `tasks.py:end_grace_periods` (hourly Celery Beat) walk `FailedPayment` rows, retry via Dodo up to `MAX_RETRY_ATTEMPTS`, and expire the subscription when the grace window closes.

---

## 7. Frontend surfaces

### 7.1 Stores

`packages/frontend/src/lib/stores/credits.ts`:

- `creditBalance` — writable Svelte store, hydrated from localStorage.
- `ensureCreditBalance()` — re-fetches if the 60-second freshness window has passed.
- `invalidateCreditBalance()` — clears the cache; called after purchases and on terminal SSE events.
- `creditBurn` — cumulative credits consumed during an active run. Updated by the SSE listener (`services/sse.ts`) as `usage` events arrive: `burn += Math.ceil(cost_usd * 2.0 * 1000)`. Reset on every terminal event.

### 7.2 Widgets

- **`CreditBadge.svelte`** — sidebar badge. Colour threshold: green above 50% of `monthly_credits`, amber 20–50%, red below 20%. Links to `/billing`.
- **`ChatHeader.svelte`** — shows `~N credits` while a run is active, sourced from `creditBurn`.
- **`UsageLimitModal.svelte`** — the "Credits exhausted" modal. Triggered by `detectLimitError()` in `ActiveChatInput.svelte` when start-run returns 402.

### 7.3 `/billing` page

`packages/frontend/src/routes/(app)/billing/+page.svelte`:

- **Credit Balance Card**: big total, pool breakdown (monthly used/total with progress bar, addon, free, active grants), **Buy Credits** button.
- **Credit Transaction History**: paginated, filterable by category (All / LLM / Compute / Integration / Purchase / Refund / Grant). Each row shows signed amount, category chip, description, timestamp.
- **Purchase Credits Dialog**: pack selector 1–10, total display, launches Dodo checkout.

`/billing/plans` shows the three tiers with monthly credit allocation in a green chip on each card.

### 7.4 API client

`packages/frontend/src/lib/api/billing.ts`:

- `getCreditBalance()` → `GET /billing/credits/balance`
- `getCreditTransactions(page, category)` → `GET /billing/credits/transactions`
- `getCreditUsageSummary(days)` → `GET /billing/credits/usage`
- `purchaseCredits(packs)` → `POST /billing/credits/purchase`

---

## 8. Budget controls

The credit system is per-user by design. Per-project / per-team budgets are **not implemented** today — the platform is single-user oriented by default, and enterprise workspace budgets live in the separate `apps/workspace` cost-control suite (`test_cost_controls.py`) which is independent of the credit wallet.

A monthly project-budget reset task *does* exist — `apps.workspace.tasks.reset_project_budgets_monthly`, scheduled via Celery Beat in `config/settings/base.py`. That task resets per-project spend counters on `Project` rows; it does **not** touch credit wallets.

If you need per-project credit ceilings, the clean place to add them is a new `ProjectBudget` model with a `monthly_credit_cap`, plus an extra check in the sandbox's `create_hold` that compares the project's month-to-date consumption (from `CreditTransaction` metadata keyed on `project_id`) against the cap.

---

## 9. Schema & migrations

Primary credit schema is in three migrations:

- `apps/billing/migrations/0001_initial.py` — first billing schema pass (plans, subscriptions, payments).
- `apps/billing/migrations/0002_initial.py` — introduces `CreditWallet`, `CreditGrant`, `CreditHold`, `CreditTransaction`, `CreditRate`, adds `monthly_credits` to `SubscriptionPlan`, and wires up FK constraints. `CreditHold.run` is `OneToOneField(to="storage.AgentRun")`.
- `apps/billing/migrations/0003_alter_creditrate_category_and_more.py` — adds `tool` to `CreditRate.category` choices and extends `CreditTransaction.category` with `tool`, `grant`, `refund`, `refresh`, `purchase`, `signup_bonus`.

Key indexes (all on `CreditTransaction` unless noted):
- `CreditWallet(user)` — lookup by user.
- `CreditGrant(wallet, expires_at)`, `CreditGrant(grant_type)` — priority-expiry ordering.
- `CreditHold(wallet, status)`, `CreditHold(run)` — active-hold lookup by run.
- `CreditTransaction(wallet, created_at)`, `(category, created_at)`, `(hold)` — billing-page history views.

### 9.1 Shadow ORM in the sandbox

`packages/sandbox/agent_server/models.py` defines `DjangoCreditWallet`, `DjangoCreditHold`, `DjangoCreditTransaction`, `DjangoCreditRate`, `DjangoAgentRun` with `Meta.managed = False`. All point at the same Postgres tables the backend owns. The sandbox reads and writes them directly via `asgiref.sync.sync_to_async`, which is why hold creation, settlement, refund, and per-tool-call billing now live in the sandbox process rather than behind a backend HTTP boundary.

---

## 10. End-to-end flow

A complete run, start to finish, with credits:

```
USER                  FRONTEND              BACKEND                         SANDBOX
 │                       │                     │                                │
 │ submit task           │                     │                                │
 ├──────────────────────>│                     │                                │
 │                       │ POST /sandbox/acquire                                │
 │                       ├────────────────────>│                                │
 │                       │                     │ provision E2B, mint JWT        │
 │                       │<────{host, jwt}─────┤                                │
 │                       │                     │                                │
 │                       │ POST /runs/start (bearer JWT, direct to sandbox)    │
 │                       ├────────────────────────────────────────────────────>│
 │                       │                     │                                │ DLP scan
 │                       │                     │                                │ toolkit resolve
 │                       │                     │                                │ create_hold
 │                       │                     │                                │   - estimate_hold_amount: 120
 │                       │                     │                                │   - check: available ≥ 120 ✓
 │                       │                     │                                │   - INSERT DjangoCreditHold active
 │                       │                     │                                │ spawn agent
 │                       │<──────SSE (run_id, events)─────────────────────────┤
 │                       │                     │                                │ … run events …
 │                       │                     │                                │ tool_call event
 │                       │                     │                                │   → bill_tool_call
 │                       │                     │                                │     - classify native/mcp
 │                       │                     │                                │     - consume 1–10 credits
 │                       │                     │                                │     - INSERT CreditTransaction -5
 │                       │                     │                                │ usage event (cost_usd)
 │                       │                     │                                │   → _consume_llm_credits
 │                       │                     │                                │     - INSERT CreditTransaction -23
 │                       │                     │                                │ … more events …
 │                       │                     │                                │ run_completed
 │                       │                     │                                │   → settle_hold_for_run
 │                       │                     │                                │     - hold.status = "settled"
 │                       │                     │                                │ compute-time accounting on teardown
 │                       │                     │                                │   → consume compute credits
 │                       │<──────SSE terminal event───────────────────────────┤
 │                       │ invalidate + refetch credit balance                  │
 │<──────────────────────┤                     │                                │
```

If the gate fires at `create_hold`, the sandbox returns 402 before the run starts. The frontend opens `UsageLimitModal`. The user either buys credits (Dodo checkout → webhook → `purchase_addon_pack`), upgrades their plan (Dodo checkout → `subscription.activated` webhook → `sync_wallet_to_plan`), or abandons the task.

---

## 11. Operational notes

**Testing.** The main credit test suites are:
- `apps/billing/tests/test_credit_models.py` — model invariants, wallet arithmetic.
- `apps/billing/tests/test_credit_service.py` — service logic including priority deduction, optimistic locking retries, hold estimation.
- `apps/billing/tests/test_credit_integration.py` — historical shadow-mode integration tests; parts of it were removed during the backend purge when the hold-creation code moved into the sandbox. Current equivalents live in `packages/sandbox/tests/`.

Run the billing suite with:

```bash
cd packages/backend
uv run pytest apps/billing/tests/ -v
```

**Admin.** Five models are registered in Django admin (`apps/billing/admin.py`): `CreditWallet`, `CreditGrant`, `CreditHold`, `CreditTransaction` (read-only), `CreditRate` (with `list_editable` on `credits_per_unit`, `markup`, `active` for live rate changes).

**Seeding.**
```bash
uv run python manage.py seed_credit_rates           # rate card
uv run python manage.py migrate_users_to_credits    # backfill wallets (--dry-run supported)
uv run python manage.py create_subscriptions        # plans with monthly_credits
```

**Debugging.** If a user is seeing "Credits exhausted" and shouldn't be:
1. Inspect `CreditWallet` in admin — verify `total_available`.
2. Tail `CreditTransaction` for the wallet ordered by `created_at DESC` — the `balance_after` column replays the balance trajectory.
3. Check for an active `CreditHold` with `amount_reserved` ≈ the blocking amount — the user might have a leaked active hold from a sandbox that crashed without emitting a terminal event. Manually settling or refunding the hold in admin unsticks them.

**Known gap.** Monthly refresh isn't on Beat today (see §5.2). In the meantime, admin can call `CreditService.refresh_monthly(wallet)` from a shell, or the plan-change signal will refresh on any subscription row save.
