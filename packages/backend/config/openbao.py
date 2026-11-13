"""OpenBao/Vault integration for loading secrets into environment variables.

Provides the ``OpenBaoEnvLoader`` class and a convenience ``load_env_from_vault``
function used at process startup to populate ``os.environ`` with secrets
stored in an OpenBao (HashiCorp Vault-compatible) server.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)


class OpenBaoEnvLoader:
    def __init__(self, vault_addr: str, token: str, verify_ssl: bool = True):
        """
        Initialize OpenBao client.

        Args:
            vault_addr: OpenBao server address (e.g., 'https://vault.example.com:8200')
            token: Authentication token
            verify_ssl: Whether to verify SSL certificates (set False for self-signed certs)
        """
        self.version = 1.0
        self.vault_addr = vault_addr.rstrip("/")
        self.token = token
        self.verify_ssl = verify_ssl
        self.headers = {"X-Vault-Token": token}

        # Disable SSL warnings if verify_ssl is False
        if not verify_ssl:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def load_secrets(self, secret_path: str, mount_point: str = "secret") -> dict:
        """
        Load secrets from OpenBao.

        Args:
            secret_path: Path to the secret (e.g., 'myapp/config')
            mount_point: Mount point (default: 'secret')

        Returns:
            Dictionary of secret key-value pairs
        """
        # Cubbyhole uses KV v1 format (no /data/ in path)
        if mount_point == "cubbyhole":
            url = f"{self.vault_addr}/v1/{mount_point}/{secret_path}"
        else:
            # For KV v2 (default for 'secret' mount), use /data/ in the path
            url = f"{self.vault_addr}/v1/{mount_point}/data/{secret_path}"

        try:
            response = requests.get(url, headers=self.headers, verify=self.verify_ssl)
            response.raise_for_status()

            data = response.json()
            # Cubbyhole (KV v1) stores secrets directly under 'data'
            if mount_point == "cubbyhole":
                return data.get("data", {})
            else:
                # KV v2 stores secrets under 'data' -> 'data'
                return data.get("data", {}).get("data", {})

        except requests.exceptions.RequestException as e:
            logger.error(f"Error loading secrets from OpenBao: {e}")
            return {}

    def load_to_env(
        self,
        secret_path: str,
        mount_point: str = "secret",
        prefix: str = "",
        overwrite: bool = False,
    ) -> int:
        """
        Load secrets from OpenBao and set them as environment variables.

        Args:
            secret_path: Path to the secret in OpenBao
            mount_point: Mount point (default: 'secret')
            prefix: Optional prefix for environment variable names
            overwrite: Whether to overwrite existing environment variables

        Returns:
            Number of variables loaded
        """
        secrets = self.load_secrets(secret_path, mount_point)
        count = 0

        logger.debug(f"Loaded {len(secrets)} secrets from vault")
        for key, value in secrets.items():
            env_key = f"{prefix}{key}".upper()

            if not overwrite and env_key in os.environ:
                continue

            os.environ[env_key] = str(value)
            count += 1

        return count


def load_env_from_vault(
    env_file: str = None,
    secret_path: str = "root",
    mount_point: str = "cubbyhole",
    overwrite: bool = False,
) -> int:
    """
    Load environment variables from OpenBao/Vault.

    This function:
    1. Optionally loads .env file to get VAULT_ADDR and VAULT_TOKEN (for local dev)
    2. Falls back to environment variables (for Docker/production)
    3. Connects to Vault and loads all secrets into environment

    Args:
        env_file: Path to .env file. If None, searches for .env in parent directories.
        secret_path: Path to secrets in Vault (default: 'root')
        mount_point: Vault mount point (default: 'cubbyhole')
        overwrite: Whether to overwrite existing env vars (default: False)

    Returns:
        Number of environment variables loaded from Vault
    """
    logger.info("_" * 80)
    logger.info((" " * 35) + "OpenBao Loader " + (" " * 35))
    logger.info("_" * 80)
    from pathlib import Path

    # Try to find .env file (for local development)
    if env_file is None:
        # Search upward from current file's location
        current = Path(__file__).parent
        while current != current.parent:
            env_path = current / ".env"
            if env_path.exists():
                env_file = str(env_path)
                break
            current = current.parent

    # Load .env file if found (for local dev - in Docker, env vars are already set)
    if env_file and Path(env_file).exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(env_file)
            logger.info(f"Loaded .env file from: {env_file}")
        except ImportError:
            logger.warning(
                "python-dotenv not installed, relying on environment variables"
            )
    else:
        logger.info(
            "No .env file found, using environment variables directly (Docker mode)"
        )

    # Get Vault connection details from environment
    vault_addr = os.getenv("VAULT_ADDR")
    vault_token = os.getenv("VAULT_TOKEN")

    if not vault_addr or not vault_token:
        logger.warning("VAULT_ADDR or VAULT_TOKEN not set. Skipping Vault loading.")
        logger.warning(f"VAULT_ADDR: {'set' if vault_addr else 'NOT SET'}")
        logger.warning(f"VAULT_TOKEN: {'set' if vault_token else 'NOT SET'}")
        return 0

    logger.info(f"Connecting to Vault at: {vault_addr}")

    # Load secrets from Vault
    verify_ssl = os.getenv("VAULT_VERIFY_SSL", "false").lower() not in (
        "false",
        "0",
        "no",
    )
    loader = OpenBaoEnvLoader(vault_addr, vault_token, verify_ssl=verify_ssl)
    count = loader.load_to_env(
        secret_path=secret_path, mount_point=mount_point, prefix="", overwrite=overwrite
    )

    logger.info(f"Loaded {count} environment variables from Vault")
    return count
