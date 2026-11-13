"""Entry point: python -m agent_server

Startup sequence:
  1. Read VAULT_ADDR + VAULT_TOKEN from the environment.
  2. Fetch all secrets from vault and inject them into os.environ.
  3. Configure DJANGO_SETTINGS_MODULE and call django.setup().
  4. Run Django migrations for sandbox-owned tables (fast, idempotent).
  5. Import and start the Django/uvicorn server.

Only VAULT_ADDR and VAULT_TOKEN need to be present in the environment;
every other configuration value (DATABASE_URL, AGENT_MODEL, API_KEY, …)
is loaded from vault before any application module is imported.
"""

import logging
import os

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

# Pin the agent_server logger with its own handler so it is immune to
# root-logger reconfiguration by tool-module imports (browse.py, search.py
# call basicConfig(force=True, level=WARNING) at import time).
_as_logger = logging.getLogger("agent_server")
_as_logger.setLevel(logging.INFO)
_as_handler = logging.StreamHandler()
_as_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
_as_logger.addHandler(_as_handler)
_as_logger.propagate = False

log = _as_logger

# Enable exo debug logging when EXO_DEBUG is set
if os.environ.get("EXO_DEBUG", "").lower() in ("1", "true", "yes"):
    from exo.observability.logging import configure_logging as _exo_configure_logging

    _exo_configure_logging(level="DEBUG")
    log.info("Exo debug logging enabled")

# Enable verbose agent logging when AGENT_VERBOSE is set
if os.environ.get("AGENT_VERBOSE", "").lower() in ("1", "true", "yes"):
    _verbose_logger = logging.getLogger("agent_server.verbose")
    _verbose_logger.setLevel(logging.DEBUG)
    _verbose_handler = logging.StreamHandler()
    # Bare formatter — verbose.py handles its own ANSI formatting
    _verbose_handler.setFormatter(logging.Formatter("%(message)s"))
    _verbose_logger.addHandler(_verbose_handler)
    _verbose_logger.propagate = False
    log.info("Verbose agent logging enabled (AGENT_VERBOSE=1)")

# ── Load configuration BEFORE importing server.py ──────────────────────────────
# server.py has module-level code that reads env vars (MANAGED_* → OPENAI_*, etc.)
# so all config must be in os.environ before that module is imported.

# ── Step 1: Load .env.local (pre-vault defaults + overrides) ─────────────────
# .env.local provides vault creds (VAULT_ADDR, VAULT_TOKEN) and any local
# overrides (LLM config, port, workspace root).  Values here are stored and
# re-applied AFTER vault so they take precedence over vault secrets.
_env_local_file = os.path.join(os.path.dirname(__file__), "..", ".env.local")
_local_overrides: dict[str, str] = {}
if os.path.isfile(_env_local_file):
    with open(_env_local_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _local_overrides[_k.strip()] = _v.strip()
    # Set as defaults first so VAULT_ADDR/VAULT_TOKEN are available for vault fetch
    for _k, _v in _local_overrides.items():
        os.environ.setdefault(_k, _v)
    log.info("Loaded %d var(s) from .env.local", len(_local_overrides))

# ── Step 2: Fetch secrets from vault ─────────────────────────────────────────
vault_addr = os.environ.get("VAULT_ADDR", "").rstrip("/")
vault_token = os.environ.get("VAULT_TOKEN", "")

if not vault_addr or not vault_token:
    missing = [v for v in ("VAULT_ADDR", "VAULT_TOKEN") if not os.environ.get(v)]
    raise RuntimeError(
        f"Required environment variable(s) not set: {', '.join(missing)}. "
        "Provide VAULT_ADDR and VAULT_TOKEN in .env.local or the environment."
    )

log.info("Connecting to vault at: %s", vault_addr)
resp = requests.get(
    f"{vault_addr}/v1/cubbyhole/root",
    headers={"X-Vault-Token": vault_token},
    verify=False,
)
resp.raise_for_status()
secrets = resp.json().get("data", {})
for key, value in secrets.items():
    os.environ[key.upper()] = str(value)
log.info("Loaded %d secret(s) from vault", len(secrets))

# ── Step 3: Re-apply .env.local overrides (win over vault) ───────────────────
# Skip VAULT_ADDR/VAULT_TOKEN since they were only needed for the fetch.
_n_overrides = 0
for _k, _v in _local_overrides.items():
    if _k in ("VAULT_ADDR", "VAULT_TOKEN"):
        continue
    if os.environ.get(_k) != _v:
        os.environ[_k] = _v
        _n_overrides += 1
if _n_overrides:
    log.info("Applied %d local override(s) over vault", _n_overrides)

# ── Initialize Django BEFORE importing server.py ─────────────────────────────
# server.py imports Django models at module level, so django.setup() must run
# first.  Vault secrets (especially DATABASE_URL) must already be in os.environ
# before django.setup() reads them, which is why this comes after vault loading.

# Force-set (not setdefault) because vault may inject the backend's settings module.
os.environ["DJANGO_SETTINGS_MODULE"] = "agent_server.settings"

import django  # noqa: E402

django.setup()

# ── Run migrations for sandbox-owned tables ──────────────────────────────────
# Fast and idempotent — no-op if already applied.  Only migrates the
# agent_server app (SandboxRun, SandboxEvent, HitlRequest); backend-owned
# tables (managed=False) are left alone.
try:
    from django.core.management import call_command

    call_command("migrate", "agent_server", "--fake-initial", verbosity=0)
    log.info("Django migrations applied successfully")
except Exception as exc:
    log.warning("Django migrations failed (non-fatal): %s", exc)

# Now import server.py — its module-level env mapping will see the vault secrets
# and Django's ORM / app registry will already be configured.
from .server import _cli  # noqa: E402

_cli()
