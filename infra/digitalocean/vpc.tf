# =============================================================================
# VPC Configuration
# =============================================================================

resource "digitalocean_vpc" "main" {
  name        = "${local.name_prefix}-vpc"
  region      = var.region
  ip_range    = var.vpc_cidr
  description = "VPC for ${var.project_name} ${var.environment} infrastructure"
}

# =============================================================================
# Container Registry Docker Credentials
# =============================================================================

# Note: The container registry must be created beforehand via DigitalOcean console
# or CLI: doctl registry create <registry-name> --subscription-tier professional

resource "digitalocean_container_registry_docker_credentials" "main" {
  registry_name  = var.registry_name
  write          = true
  expiry_seconds = 31536000  # 1 year
}

