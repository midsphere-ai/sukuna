# =============================================================================
# Firewall Rules
# =============================================================================

# -----------------------------------------------------------------------------
# VPC Internal Traffic Firewall
# -----------------------------------------------------------------------------

resource "digitalocean_firewall" "vpc_internal" {
  name = "${local.name_prefix}-vpc-internal"

  tags = [
    digitalocean_tag.production.id,
  ]

  # Allow all inbound traffic from within the VPC
  inbound_rule {
    protocol         = "tcp"
    port_range       = "1-65535"
    source_addresses = [var.vpc_cidr]
  }

  inbound_rule {
    protocol         = "udp"
    port_range       = "1-65535"
    source_addresses = [var.vpc_cidr]
  }

  inbound_rule {
    protocol         = "icmp"
    source_addresses = [var.vpc_cidr]
  }

  # Allow all outbound traffic
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  depends_on = [
    digitalocean_tag.production,
    digitalocean_vpc.main
  ]
}

# -----------------------------------------------------------------------------
# Load Balancer Firewall (HTTP/HTTPS)
# -----------------------------------------------------------------------------

resource "digitalocean_firewall" "load_balancer" {
  name = "${local.name_prefix}-lb-public"

  tags = [
    digitalocean_tag.django_main.id,
    digitalocean_tag.django_channels.id,
  ]

  # Allow HTTP
  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  # Allow HTTPS
  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  # Allow SSH (for management - restrict in production)
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0"]
  }

  # Allow all outbound
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  depends_on = [
    digitalocean_tag.django_main,
    digitalocean_tag.django_channels,
  ]
}

# -----------------------------------------------------------------------------
# Flower Firewall (IP Whitelisted)
# -----------------------------------------------------------------------------

resource "digitalocean_firewall" "flower" {
  name = "${local.name_prefix}-flower"

  tags = [
    digitalocean_tag.flower.id,
  ]

  # Allow HTTPS from whitelisted IPs only
  dynamic "inbound_rule" {
    for_each = length(var.flower_allowed_ips) > 0 ? [1] : []
    content {
      protocol         = "tcp"
      port_range       = "443"
      source_addresses = var.flower_allowed_ips
    }
  }

  # Allow port 5555 from whitelisted IPs
  dynamic "inbound_rule" {
    for_each = length(var.flower_allowed_ips) > 0 ? [1] : []
    content {
      protocol         = "tcp"
      port_range       = "5555"
      source_addresses = var.flower_allowed_ips
    }
  }

  # If no whitelist, allow from anywhere (with basic auth protection)
  dynamic "inbound_rule" {
    for_each = length(var.flower_allowed_ips) == 0 ? [1] : []
    content {
      protocol         = "tcp"
      port_range       = "443"
      source_addresses = ["0.0.0.0/0", "::/0"]
    }
  }

  dynamic "inbound_rule" {
    for_each = length(var.flower_allowed_ips) == 0 ? [1] : []
    content {
      protocol         = "tcp"
      port_range       = "5555"
      source_addresses = ["0.0.0.0/0", "::/0"]
    }
  }

  # Allow SSH
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0"]
  }

  # Allow all outbound
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  depends_on = [digitalocean_tag.flower]
}

# -----------------------------------------------------------------------------
# Private Services Firewall (Celery Beat/Workers - no public access)
# -----------------------------------------------------------------------------

resource "digitalocean_firewall" "private_services" {
  name = "${local.name_prefix}-private"

  tags = [
    digitalocean_tag.celery_beat.id,
    digitalocean_tag.celery_worker.id,
  ]

  # Only allow SSH for management
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0"]
  }

  # Allow all outbound
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  depends_on = [
    digitalocean_tag.celery_beat,
    digitalocean_tag.celery_worker,
  ]
}

# =============================================================================
# Tags for Resource Organization
# =============================================================================

resource "digitalocean_tag" "production" {
  name = "production"
}

resource "digitalocean_tag" "django_main" {
  name = "django-main"
}

resource "digitalocean_tag" "django_channels" {
  name = "django-channels"
}

resource "digitalocean_tag" "celery_beat" {
  name = "celery-beat"
}

resource "digitalocean_tag" "celery_worker" {
  name = "celery-worker"
}

resource "digitalocean_tag" "flower" {
  name = "flower"
}

resource "digitalocean_tag" "arq_workers" {
  name = "arq-workers"
}
