"""Shared test configuration — Django bootstrap for all sandbox tests.

Tests need DATABASE_URL (plus other secrets) in the environment before
`django.setup()` reads settings.py. Mirror the production __main__.py
bootstrap: load `.env.local`, fetch vault secrets, re-apply local
overrides, then initialize Django.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_env_local() -> dict[str, str]:
    env_file = Path(__file__).parent.parent / ".env.local"
    overrides: dict[str, str] = {}
    if not env_file.is_file():
        return overrides
    with env_file.open() as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                overrides[k.strip()] = v.strip()
    for k, v in overrides.items():
        os.environ.setdefault(k, v)
    return overrides


def _load_vault_secrets() -> None:
    addr = os.environ.get("VAULT_ADDR", "").rstrip("/")
    token = os.environ.get("VAULT_TOKEN", "")
    if not addr or not token:
        return
    try:
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(
            f"{addr}/v1/cubbyhole/root",
            headers={"X-Vault-Token": token},
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        for k, v in resp.json().get("data", {}).items():
            os.environ[k.upper()] = str(v)
    except Exception:
        # Tests that need specific secrets will fail; basic import tests still run.
        pass


_local = _load_env_local()
_load_vault_secrets()
for k, v in _local.items():
    if k in ("VAULT_ADDR", "VAULT_TOKEN"):
        continue
    os.environ[k] = v

os.environ["DJANGO_SETTINGS_MODULE"] = "agent_server.settings"

import django  # noqa: E402

django.setup()
