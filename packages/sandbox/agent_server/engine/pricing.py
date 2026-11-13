"""Per-model price table and cost-derivation helpers.

The exo runtime reports token counts in its ``UsageEvent``s but does **not**
populate ``cost_usd`` — every provider would have to publish its own price
sheet for that to work. We bridge the gap here: given a model identifier
and per-step token counts, ``derive_cost()`` returns a USD estimate that
the billing pipeline (``CreditService.calculate_llm_credits``) can charge.

Used by:
    - ``infra.state.update_usage_totals`` — fills in ``cost_usd`` whenever
      the upstream event lacks it.
    - ``engine.hooks.make_usage_estimate_hook`` — pairs token-estimation
      with cost-derivation when a provider returns zero usage.

Setting your own prices
-----------------------

Three ways, in priority order (last write wins, all applied at import):

1. **Pricing file** (recommended for real-life rates) — set
   ``MODEL_PRICING_FILE`` to a JSON path. Default search order if unset:

       $MODEL_PRICING_FILE                               (explicit)
       $XDG_CONFIG_HOME/sukuna/pricing.json              (XDG)
       ~/.config/sukuna/pricing.json                     (XDG fallback)
       <sandbox_workspace>/.sukuna/pricing.json          (per-sandbox)

   File format::

       [
         {"pattern": "claude-opus-4",      "input_per_1k": 0.015,  "output_per_1k": 0.075},
         {"pattern": "anthropic:.*sonnet", "input_per_1k": 0.003,  "output_per_1k": 0.015},
         {"pattern": "ollama:",            "input_per_1k": 0.0,    "output_per_1k": 0.0}
       ]

2. **Inline env override** — ``MODEL_PRICING_JSON`` accepts the same
   schema as a single env var (handy for one-off Docker / CI tweaks).

3. **Programmatic** — call :func:`register_pricing` from application code
   (e.g. an admin endpoint that re-applies rates from a database).

All three sources prepend to the table, so user-supplied entries always
win over the built-in defaults shipped below.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from threading import Lock
from typing import Iterable

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Pricing definition for a model name pattern.

    ``pattern`` is matched against the model identifier with ``re.search``.
    Costs are USD per 1 000 tokens.
    """

    pattern: str
    input_per_1k: float
    output_per_1k: float


# ---------------------------------------------------------------------------
# Built-in defaults (USD per 1 000 tokens)
#
# Order matters — first match wins. Put the more specific patterns first.
# Numbers are public list prices; tweak via ``MODEL_PRICING_JSON`` for
# negotiated rates or BYOM accounting.
# ---------------------------------------------------------------------------

_DEFAULT_PRICING: tuple[ModelPricing, ...] = (
    # ── Anthropic Claude 4.x ───────────────────────────────────────────
    ModelPricing(r"claude-opus-4", input_per_1k=0.015, output_per_1k=0.075),
    ModelPricing(r"claude-sonnet-4", input_per_1k=0.003, output_per_1k=0.015),
    ModelPricing(r"claude-haiku-4", input_per_1k=0.001, output_per_1k=0.005),
    # ── Anthropic Claude 3.x (legacy) ──────────────────────────────────
    ModelPricing(r"claude-3-5-sonnet", input_per_1k=0.003, output_per_1k=0.015),
    ModelPricing(r"claude-3-5-haiku", input_per_1k=0.0008, output_per_1k=0.004),
    ModelPricing(r"claude-3-opus", input_per_1k=0.015, output_per_1k=0.075),
    # ── OpenAI GPT-4 family ────────────────────────────────────────────
    ModelPricing(r"gpt-4o-mini", input_per_1k=0.00015, output_per_1k=0.0006),
    ModelPricing(r"gpt-4o", input_per_1k=0.0025, output_per_1k=0.01),
    ModelPricing(r"gpt-4-turbo", input_per_1k=0.01, output_per_1k=0.03),
    ModelPricing(r"gpt-4\b", input_per_1k=0.03, output_per_1k=0.06),
    ModelPricing(r"gpt-3\.5-turbo", input_per_1k=0.0005, output_per_1k=0.0015),
    ModelPricing(r"o1-mini", input_per_1k=0.003, output_per_1k=0.012),
    ModelPricing(r"o1", input_per_1k=0.015, output_per_1k=0.06),
    # ── Google Gemini ──────────────────────────────────────────────────
    ModelPricing(r"gemini-2\.5-pro", input_per_1k=0.00125, output_per_1k=0.005),
    ModelPricing(r"gemini-2\.0-flash", input_per_1k=0.0001, output_per_1k=0.0004),
    ModelPricing(r"gemini-1\.5-pro", input_per_1k=0.00125, output_per_1k=0.005),
    ModelPricing(r"gemini-1\.5-flash", input_per_1k=0.000075, output_per_1k=0.0003),
    # ── Open / hosted-OSS approximations ──────────────────────────────
    # Costs vary by host; these are reasonable averages for shared
    # inference. Override per-deployment via MODEL_PRICING_JSON.
    ModelPricing(r"glm-5", input_per_1k=0.0006, output_per_1k=0.0022),
    ModelPricing(r"glm-4", input_per_1k=0.0005, output_per_1k=0.0015),
    ModelPricing(r"llama-3\.\d+-405b", input_per_1k=0.0035, output_per_1k=0.0035),
    ModelPricing(r"llama-3\.\d+-70b", input_per_1k=0.0009, output_per_1k=0.0009),
    ModelPricing(r"llama-3\.\d+-8b", input_per_1k=0.0002, output_per_1k=0.0002),
    ModelPricing(r"qwen-?2\.5-72b", input_per_1k=0.0009, output_per_1k=0.0009),
    ModelPricing(r"deepseek", input_per_1k=0.00027, output_per_1k=0.0011),
    # ── Local / self-hosted (effectively free for billing) ────────────
    # Match Ollama's "ollama:<model>" style strings + bare local hints.
    ModelPricing(r"^ollama:", input_per_1k=0.0, output_per_1k=0.0),
    ModelPricing(r":local$|^local:", input_per_1k=0.0, output_per_1k=0.0),
    ModelPricing(r"vllm", input_per_1k=0.0, output_per_1k=0.0),
)


_pricing_lock = Lock()
_pricing: list[ModelPricing] = list(_DEFAULT_PRICING)
_pattern_cache: dict[str, ModelPricing | None] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_pricing(pattern: str, input_per_1k: float, output_per_1k: float) -> None:
    """Add a pricing entry; new patterns take priority over older ones."""
    entry = ModelPricing(
        pattern=pattern,
        input_per_1k=float(input_per_1k),
        output_per_1k=float(output_per_1k),
    )
    with _pricing_lock:
        _pricing.insert(0, entry)
        _pattern_cache.clear()


def find_pricing(model: str) -> ModelPricing | None:
    """Return the first pricing entry whose pattern matches *model*."""
    if not model:
        return None
    cached = _pattern_cache.get(model)
    if cached is not None or model in _pattern_cache:
        return cached
    with _pricing_lock:
        for entry in _pricing:
            try:
                if re.search(entry.pattern, model):
                    _pattern_cache[model] = entry
                    return entry
            except re.error:
                continue
        _pattern_cache[model] = None
        return None


def derive_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost for a single LLM step. Returns 0.0 when unknown.

    Strips common provider prefixes (``openai:``, ``anthropic:``, etc.)
    before matching so callers can pass the raw exo model string.
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return 0.0
    name = (model or "").strip()
    pricing = find_pricing(name) or find_pricing(_strip_provider_prefix(name))
    if pricing is None:
        return 0.0
    return (max(input_tokens, 0) / 1000.0) * pricing.input_per_1k + (
        max(output_tokens, 0) / 1000.0
    ) * pricing.output_per_1k


def _strip_provider_prefix(model: str) -> str:
    # exo formats models as "<provider>:<model>" — strip the provider so
    # patterns like ``r"claude-sonnet-4"`` still match
    # ``"anthropic:claude-sonnet-4-6"``.
    if ":" in model:
        return model.split(":", 1)[1]
    return model


def all_pricing() -> tuple[ModelPricing, ...]:
    """Snapshot of the current pricing table (for diagnostics / tests)."""
    with _pricing_lock:
        return tuple(_pricing)


# ---------------------------------------------------------------------------
# User-supplied overrides — file, inline env var, or programmatic API
# ---------------------------------------------------------------------------


def _apply_entries(entries: Any, *, source: str) -> int:
    """Validate and ``register_pricing()`` a list of pricing dicts."""
    if not isinstance(entries, Iterable):
        log.warning("%s must contain a JSON array of pricing dicts", source)
        return 0
    count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pattern = entry.get("pattern")
        try:
            in_1k = float(entry["input_per_1k"])
            out_1k = float(entry["output_per_1k"])
        except (KeyError, TypeError, ValueError):
            log.warning("%s: skipping malformed entry %r", source, entry)
            continue
        if not isinstance(pattern, str) or not pattern:
            continue
        register_pricing(pattern, in_1k, out_1k)
        count += 1
    return count


def load_pricing_file(path: str) -> int:
    """Read a JSON pricing file from *path* and register every entry.

    Returns the number of entries registered.  Public so an admin
    endpoint or a CLI command can re-apply rates without restarting.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return 0
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("pricing file %s could not be loaded: %s", path, exc)
        return 0
    count = _apply_entries(data, source=f"pricing file {path!r}")
    if count:
        log.info("pricing: loaded %d entries from %s", count, path)
    return count


def _candidate_pricing_files() -> list[str]:
    """Search-path order for the pricing file (first hit wins)."""
    explicit = os.environ.get("MODEL_PRICING_FILE")
    if explicit:
        return [os.path.expanduser(explicit)]

    candidates: list[str] = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        candidates.append(os.path.join(xdg, "sukuna", "pricing.json"))
    home = os.path.expanduser("~")
    if home and home != "~":
        candidates.append(os.path.join(home, ".config", "sukuna", "pricing.json"))
    workspace = os.environ.get("SANDBOX_WORKSPACE_ROOT") or os.environ.get("WORKSPACE")
    if workspace:
        candidates.append(os.path.join(workspace, ".sukuna", "pricing.json"))
    return candidates


def _load_env_overrides() -> None:
    # 1. File first — it's the user's persisted real-life sheet.
    for path in _candidate_pricing_files():
        if path and os.path.exists(path):
            load_pricing_file(path)
            break

    # 2. Inline env var — last so it wins over file entries.
    raw = os.environ.get("MODEL_PRICING_JSON")
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("MODEL_PRICING_JSON is not valid JSON; ignoring overrides")
        return
    count = _apply_entries(data, source="MODEL_PRICING_JSON")
    if count:
        log.info("pricing: loaded %d override(s) from MODEL_PRICING_JSON", count)


_load_env_overrides()
