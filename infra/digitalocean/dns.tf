# =============================================================================
# DNS Records
# =============================================================================

# Note: The domain 'midsphere.ai' must already exist in DigitalOcean DNS.
# This is verified via the data source in main.tf

# -----------------------------------------------------------------------------
# API Subdomain (Django Main)
# -----------------------------------------------------------------------------

resource "digitalocean_record" "api" {
  domain = data.digitalocean_domain.main.id
  type   = "A"
  name   = "api"
  value  = digitalocean_loadbalancer.django_main.ip
  ttl    = var.dns_ttl
}

# -----------------------------------------------------------------------------
# Channels Subdomain (Django Channels)
# -----------------------------------------------------------------------------

resource "digitalocean_record" "channels" {
  domain = data.digitalocean_domain.main.id
  type   = "A"
  name   = "channels"
  value  = digitalocean_loadbalancer.django_channels.ip
  ttl    = var.dns_ttl
}

# -----------------------------------------------------------------------------
# Flower Subdomain
# -----------------------------------------------------------------------------

resource "digitalocean_record" "flower" {
  domain = data.digitalocean_domain.main.id
  type   = "A"
  name   = "flower"
  value  = digitalocean_loadbalancer.flower.ip
  ttl    = var.dns_ttl
}
