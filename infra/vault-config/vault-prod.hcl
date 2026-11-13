# Vault Server Configuration — PRODUCTION
#
# TLS is enabled. Requires valid certificate and key files.
# Mount certs at /vault/config/tls/ in the container.

# Enable the web UI
ui = true

# Disable mlock (set to false if running with --cap-add=IPC_LOCK)
disable_mlock = true

# File storage backend (for single-node; use Consul/Raft for HA)
storage "file" {
  path = "/vault/data"
}

# TCP listener configuration — TLS enabled for production
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 0

  tls_cert_file = "/vault/config/tls/vault.crt"
  tls_key_file  = "/vault/config/tls/vault.key"

  # Optionally require client certificates:
  # tls_client_ca_file = "/vault/config/tls/ca.crt"
  # tls_require_and_verify_client_cert = true
}

# API address (for redirects) — use HTTPS in production
api_addr = "https://0.0.0.0:8200"

# Cluster address (for HA mode)
cluster_addr = "https://0.0.0.0:8201"

# Telemetry configuration (optional)
telemetry {
  disable_hostname = true
}
