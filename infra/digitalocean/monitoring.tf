# =============================================================================
# Monitoring & Alert Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# Alert Policies
# -----------------------------------------------------------------------------

# CPU Usage Alert
resource "digitalocean_monitor_alert" "cpu_alert" {
  count = length(var.alert_emails) > 0 ? 1 : 0

  alerts {
    email = var.alert_emails
  }

  window      = "5m"
  type        = "v1/insights/droplet/cpu"
  compare     = "GreaterThan"
  value       = var.cpu_alert_threshold
  enabled     = true
  description = "CPU usage exceeds ${var.cpu_alert_threshold}% for 5 minutes"

  entities = concat(
    digitalocean_droplet.django_main[*].id,
    digitalocean_droplet.django_channels[*].id,
    [digitalocean_droplet.celery_beat.id],
    digitalocean_droplet.celery_worker[*].id,
    [digitalocean_droplet.flower.id]
  )

  depends_on = [
    digitalocean_droplet.django_main,
    digitalocean_droplet.django_channels,
    digitalocean_droplet.celery_beat,
    digitalocean_droplet.celery_worker,
    digitalocean_droplet.flower,
  ]
}

# Memory Usage Alert
resource "digitalocean_monitor_alert" "memory_alert" {
  count = length(var.alert_emails) > 0 ? 1 : 0

  alerts {
    email = var.alert_emails
  }

  window      = "5m"
  type        = "v1/insights/droplet/memory_utilization_percent"
  compare     = "GreaterThan"
  value       = var.memory_alert_threshold
  enabled     = true
  description = "Memory usage exceeds ${var.memory_alert_threshold}% for 5 minutes"

  entities = concat(
    digitalocean_droplet.django_main[*].id,
    digitalocean_droplet.django_channels[*].id,
    [digitalocean_droplet.celery_beat.id],
    digitalocean_droplet.celery_worker[*].id,
    [digitalocean_droplet.flower.id]
  )

  depends_on = [
    digitalocean_droplet.django_main,
    digitalocean_droplet.django_channels,
    digitalocean_droplet.celery_beat,
    digitalocean_droplet.celery_worker,
    digitalocean_droplet.flower,
  ]
}

# Disk Usage Alert
resource "digitalocean_monitor_alert" "disk_alert" {
  count = length(var.alert_emails) > 0 ? 1 : 0

  alerts {
    email = var.alert_emails
  }

  window      = "5m"
  type        = "v1/insights/droplet/disk_utilization_percent"
  compare     = "GreaterThan"
  value       = var.disk_alert_threshold
  enabled     = true
  description = "Disk usage exceeds ${var.disk_alert_threshold}%"

  entities = concat(
    digitalocean_droplet.django_main[*].id,
    digitalocean_droplet.django_channels[*].id,
    [digitalocean_droplet.celery_beat.id],
    digitalocean_droplet.celery_worker[*].id,
    [digitalocean_droplet.flower.id]
  )

  depends_on = [
    digitalocean_droplet.django_main,
    digitalocean_droplet.django_channels,
    digitalocean_droplet.celery_beat,
    digitalocean_droplet.celery_worker,
    digitalocean_droplet.flower,
  ]
}

# Load Balancer Down Alert
resource "digitalocean_monitor_alert" "lb_django_main_down" {
  count = length(var.alert_emails) > 0 ? 1 : 0

  alerts {
    email = var.alert_emails
  }

  window      = "5m"
  type        = "v1/insights/lbaas/droplet_health"
  compare     = "LessThan"
  value       = 1
  enabled     = true
  description = "Django Main Load Balancer has no healthy backends"

  entities = [digitalocean_loadbalancer.django_main.id]

  depends_on = [digitalocean_loadbalancer.django_main]
}

resource "digitalocean_monitor_alert" "lb_channels_down" {
  count = length(var.alert_emails) > 0 ? 1 : 0

  alerts {
    email = var.alert_emails
  }

  window      = "5m"
  type        = "v1/insights/lbaas/droplet_health"
  compare     = "LessThan"
  value       = 1
  enabled     = true
  description = "Django Channels Load Balancer has no healthy backends"

  entities = [digitalocean_loadbalancer.django_channels.id]

  depends_on = [digitalocean_loadbalancer.django_channels]
}

resource "digitalocean_monitor_alert" "lb_flower_down" {
  count = length(var.alert_emails) > 0 ? 1 : 0

  alerts {
    email = var.alert_emails
  }

  window      = "5m"
  type        = "v1/insights/lbaas/droplet_health"
  compare     = "LessThan"
  value       = 1
  enabled     = true
  description = "Flower Load Balancer has no healthy backends"

  entities = [digitalocean_loadbalancer.flower.id]

  depends_on = [digitalocean_loadbalancer.flower]
}

# Note: Kubernetes node status monitoring is handled via DOKS built-in monitoring
# and Kubernetes-native tools (kubectl, metrics-server, etc.) rather than
# DigitalOcean monitor alerts, which don't support DOKS node status.
