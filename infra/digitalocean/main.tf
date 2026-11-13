# =============================================================================
# Local Values
# =============================================================================

locals {
  # Common naming prefix
  name_prefix = "${var.project_name}-${var.environment}"

  # Common tags for all resources
  default_tags = concat([
    var.environment,
    var.project_name,
    "terraform-managed"
  ], var.common_tags)

  # Container registry URL
  registry_url = "registry.digitalocean.com/${var.registry_name}"

  # Image URLs
  images = {
    main     = "${local.registry_url}/platform-main:latest"
    channels = "${local.registry_url}/platform-channels:latest"
    celery   = "${local.registry_url}/platform-celery:latest"
    workers  = "${local.registry_url}/platform-workers:latest"
  }

  # Service domains
  domains = {
    api      = "api.${var.domain}"
    channels = "channels.${var.domain}"
    flower   = "flower.${var.domain}"
  }
}

# =============================================================================
# Data Sources
# =============================================================================

# Verify domain exists in DigitalOcean DNS
data "digitalocean_domain" "main" {
  name = var.domain
}

# Get available Kubernetes versions
data "digitalocean_kubernetes_versions" "available" {}

