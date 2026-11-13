#!/usr/bin/env python
"""Django management utility for the sandbox agent server.

Loads .env.local and fetches secrets from vault before starting Django,
mirroring the bootstrap done by ``python -m agent_server``.
"""

import os
import sys

import requests


def _bootstrap_env() -> None:
    # Step 1: .env.local (pre-vault defaults + overrides)
    env_local = os.path.join(os.path.dirname(__file__), ".env.local")
    local_overrides: dict[str, str] = {}
    if os.path.isfile(env_local):
        with open(env_local) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    local_overrides[k.strip()] = v.strip()
        for k, v in local_overrides.items():
            os.environ.setdefault(k, v)

    # Step 2: fetch secrets from vault
    vault_addr = os.environ.get("VAULT_ADDR", "").rstrip("/")
    vault_token = os.environ.get("VAULT_TOKEN", "")
    if not vault_addr or not vault_token:
        missing = [v for v in ("VAULT_ADDR", "VAULT_TOKEN") if not os.environ.get(v)]
        raise RuntimeError(
            f"Required environment variable(s) not set: {', '.join(missing)}. "
            "Provide VAULT_ADDR and VAULT_TOKEN in .env.local or the environment."
        )
    resp = requests.get(
        f"{vault_addr}/v1/cubbyhole/root",
        headers={"X-Vault-Token": vault_token},
        verify=False,
    )
    resp.raise_for_status()
    for key, value in resp.json().get("data", {}).items():
        os.environ[key.upper()] = str(value)

    # Step 3: re-apply local overrides so they win over vault
    for k, v in local_overrides.items():
        if k in ("VAULT_ADDR", "VAULT_TOKEN"):
            continue
        os.environ[k] = v


def main():
    _bootstrap_env()
    os.environ["DJANGO_SETTINGS_MODULE"] = "agent_server.settings"
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
