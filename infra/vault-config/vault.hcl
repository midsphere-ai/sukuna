# Vault Server Configuration — LOCAL DEVELOPMENT ONLY
#
# WARNING: TLS is disabled in this config. Do NOT use in production.
# For production deployments, use vault-prod.hcl instead.

# Enable the web UI
ui = true

# Disable mlock (required for Docker without --cap-add=IPC_LOCK)
disable_mlock = true

# File storage backend (simplest option for single-node deployment)
storage "file" {
  path = "/vault/data"
}

# TCP listener configuration — TLS disabled for local development
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1
}

# API address (for redirects)
api_addr = "http://0.0.0.0:8200"

# Cluster address (for HA mode)
cluster_addr = "http://0.0.0.0:8201"

# Telemetry configuration (optional)
telemetry {
  disable_hostname = true
}
