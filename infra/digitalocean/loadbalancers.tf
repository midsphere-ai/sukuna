# =============================================================================
# Load Balancer Configurations
# =============================================================================

# -----------------------------------------------------------------------------
# Django Main Load Balancer
# -----------------------------------------------------------------------------

resource "digitalocean_loadbalancer" "django_main" {
  name   = "${local.name_prefix}-lb-django-main"
  region = var.region

  vpc_uuid = digitalocean_vpc.main.id

  # HTTPS forwarding rule
  forwarding_rule {
    entry_port     = 443
    entry_protocol = "https"

    target_port     = var.django_main_port
    target_protocol = "http"

    certificate_name = digitalocean_certificate.main.name
  }

  # HTTP to HTTPS redirect
  forwarding_rule {
    entry_port     = 80
    entry_protocol = "http"

    target_port     = var.django_main_port
    target_protocol = "http"
  }

  # Health check
  healthcheck {
    port                   = var.django_main_port
    protocol               = "http"
    path                   = "/health/"
    check_interval_seconds = 10
    response_timeout_seconds = 5
    healthy_threshold      = 3
    unhealthy_threshold    = 3
  }

  # Attach Django main droplets
  droplet_ids = digitalocean_droplet.django_main[*].id

  # Enable HTTP/2
  enable_proxy_protocol = false

  # Redirect HTTP to HTTPS
  redirect_http_to_https = true

  depends_on = [
    digitalocean_droplet.django_main,
  ]
}

# -----------------------------------------------------------------------------
# Django Channels Load Balancer (WebSocket)
# -----------------------------------------------------------------------------

resource "digitalocean_loadbalancer" "django_channels" {
  name   = "${local.name_prefix}-lb-django-channels"
  region = var.region

  vpc_uuid = digitalocean_vpc.main.id

  # HTTPS forwarding rule
  forwarding_rule {
    entry_port     = 443
    entry_protocol = "https"

    target_port     = var.django_channels_port
    target_protocol = "http"

    certificate_name = digitalocean_certificate.channels.name
  }

  # HTTP to HTTPS redirect
  forwarding_rule {
    entry_port     = 80
    entry_protocol = "http"

    target_port     = var.django_channels_port
    target_protocol = "http"
  }

  # Health check
  healthcheck {
    port                   = var.django_channels_port
    protocol               = "http"
    path                   = "/ws-health/"
    check_interval_seconds = 10
    response_timeout_seconds = 5
    healthy_threshold      = 3
    unhealthy_threshold    = 3
  }

  # Attach Django channels droplets
  droplet_ids = digitalocean_droplet.django_channels[*].id

  # Enable sticky sessions for WebSocket connections
  sticky_sessions {
    type               = "cookies"
    cookie_name        = "DO-LB-SESSION"
    cookie_ttl_seconds = 300
  }

  # Redirect HTTP to HTTPS
  redirect_http_to_https = true

  depends_on = [
    digitalocean_droplet.django_channels,
  ]
}

# -----------------------------------------------------------------------------
# Flower Load Balancer
# -----------------------------------------------------------------------------

resource "digitalocean_loadbalancer" "flower" {
  name   = "${local.name_prefix}-lb-flower"
  region = var.region

  vpc_uuid = digitalocean_vpc.main.id

  # HTTPS forwarding rule
  forwarding_rule {
    entry_port     = 443
    entry_protocol = "https"

    target_port     = var.flower_port
    target_protocol = "http"

    certificate_name = digitalocean_certificate.flower.name
  }

  # HTTP to HTTPS redirect
  forwarding_rule {
    entry_port     = 80
    entry_protocol = "http"

    target_port     = var.flower_port
    target_protocol = "http"
  }

  # Health check
  healthcheck {
    port                   = var.flower_port
    protocol               = "http"
    path                   = "/"
    check_interval_seconds = 10
    response_timeout_seconds = 5
    healthy_threshold      = 3
    unhealthy_threshold    = 3
  }

  # Attach Flower droplet
  droplet_ids = [digitalocean_droplet.flower.id]

  # Redirect HTTP to HTTPS
  redirect_http_to_https = true

  depends_on = [
    digitalocean_droplet.flower,
  ]
}

# =============================================================================
# SSL Certificates (Let's Encrypt)
# =============================================================================
# NOTE: These certificates are protected from destruction to avoid Let's Encrypt
# rate limits. To force recreation, remove from state first:
# terraform state rm digitalocean_certificate.main
# terraform state rm digitalocean_certificate.channels
# terraform state rm digitalocean_certificate.flower

resource "digitalocean_certificate" "main" {
  name    = "${local.name_prefix}-cert-api"
  type    = "lets_encrypt"
  domains = [local.domains.api]

  lifecycle {
    create_before_destroy = true
    prevent_destroy       = true
  }
}

resource "digitalocean_certificate" "channels" {
  name    = "${local.name_prefix}-cert-channels"
  type    = "lets_encrypt"
  domains = [local.domains.channels]

  lifecycle {
    create_before_destroy = true
    prevent_destroy       = true
  }
}

resource "digitalocean_certificate" "flower" {
  name    = "${local.name_prefix}-cert-flower"
  type    = "lets_encrypt"
  domains = [local.domains.flower]

  lifecycle {
    create_before_destroy = true
    prevent_destroy       = true
  }
}
