# =============================================================================
# Terraform Outputs
# =============================================================================

# -----------------------------------------------------------------------------
# VPC Information
# -----------------------------------------------------------------------------

output "vpc_id" {
  description = "VPC ID"
  value       = digitalocean_vpc.main.id
}

output "vpc_urn" {
  description = "VPC URN"
  value       = digitalocean_vpc.main.urn
}

# -----------------------------------------------------------------------------
# Container Registry
# -----------------------------------------------------------------------------

output "registry_endpoint" {
  description = "Container registry endpoint"
  value       = "registry.digitalocean.com/${var.registry_name}"
}

output "registry_name" {
  description = "Container registry name"
  value       = var.registry_name
}

# -----------------------------------------------------------------------------
# Load Balancer IPs
# -----------------------------------------------------------------------------

output "lb_django_main_ip" {
  description = "Django Main Load Balancer IP"
  value       = digitalocean_loadbalancer.django_main.ip
}

output "lb_django_channels_ip" {
  description = "Django Channels Load Balancer IP"
  value       = digitalocean_loadbalancer.django_channels.ip
}

output "lb_flower_ip" {
  description = "Flower Load Balancer IP"
  value       = digitalocean_loadbalancer.flower.ip
}

# -----------------------------------------------------------------------------
# Domain URLs
# -----------------------------------------------------------------------------

output "api_url" {
  description = "API URL (Django Main)"
  value       = "https://${local.domains.api}"
}

output "channels_url" {
  description = "Channels URL (WebSocket)"
  value       = "wss://${local.domains.channels}"
}

output "flower_url" {
  description = "Flower Dashboard URL"
  value       = "https://${local.domains.flower}"
}

# -----------------------------------------------------------------------------
# Droplet Information
# -----------------------------------------------------------------------------

output "django_main_droplets" {
  description = "Django Main droplet details"
  value = [
    for d in digitalocean_droplet.django_main : {
      id         = d.id
      name       = d.name
      ipv4       = d.ipv4_address
      private_ip = d.ipv4_address_private
      status     = d.status
    }
  ]
}

output "django_channels_droplets" {
  description = "Django Channels droplet details"
  value = [
    for d in digitalocean_droplet.django_channels : {
      id         = d.id
      name       = d.name
      ipv4       = d.ipv4_address
      private_ip = d.ipv4_address_private
      status     = d.status
    }
  ]
}

output "celery_beat_droplet" {
  description = "Celery Beat droplet details"
  value = {
    id         = digitalocean_droplet.celery_beat.id
    name       = digitalocean_droplet.celery_beat.name
    ipv4       = digitalocean_droplet.celery_beat.ipv4_address
    private_ip = digitalocean_droplet.celery_beat.ipv4_address_private
    status     = digitalocean_droplet.celery_beat.status
  }
}

output "celery_worker_droplets" {
  description = "Celery Worker droplet details"
  value = [
    for d in digitalocean_droplet.celery_worker : {
      id         = d.id
      name       = d.name
      ipv4       = d.ipv4_address
      private_ip = d.ipv4_address_private
      status     = d.status
    }
  ]
}

output "flower_droplet" {
  description = "Flower droplet details"
  value = {
    id         = digitalocean_droplet.flower.id
    name       = digitalocean_droplet.flower.name
    ipv4       = digitalocean_droplet.flower.ipv4_address
    private_ip = digitalocean_droplet.flower.ipv4_address_private
    status     = digitalocean_droplet.flower.status
  }
}

# -----------------------------------------------------------------------------
# Kubernetes Cluster
# -----------------------------------------------------------------------------

output "k8s_cluster_id" {
  description = "Kubernetes cluster ID"
  value       = digitalocean_kubernetes_cluster.arq_cluster.id
}

output "k8s_cluster_endpoint" {
  description = "Kubernetes cluster API endpoint"
  value       = digitalocean_kubernetes_cluster.arq_cluster.endpoint
}

output "k8s_cluster_version" {
  description = "Kubernetes cluster version"
  value       = digitalocean_kubernetes_cluster.arq_cluster.version
}

output "k8s_cluster_status" {
  description = "Kubernetes cluster status"
  value       = digitalocean_kubernetes_cluster.arq_cluster.status
}

output "kubeconfig_path" {
  description = "Path to kubeconfig file"
  value       = local_file.kubeconfig.filename
}

# -----------------------------------------------------------------------------
# Summary Table
# -----------------------------------------------------------------------------

output "deployment_summary" {
  description = "Summary of all deployed resources"
  value       = <<-EOT

    ================================================================================
    MIDSPHERE PRODUCTION DEPLOYMENT SUMMARY
    ================================================================================

    VPC:
      - ID: ${digitalocean_vpc.main.id}
      - Region: ${var.region}
      - CIDR: ${var.vpc_cidr}

    Container Registry:
      - Endpoint: registry.digitalocean.com/${var.registry_name}

    -------------------------------------------------------------------------------
    DROPLETS
    -------------------------------------------------------------------------------

    Django Main (${var.django_main_count} instances):
    %{for d in digitalocean_droplet.django_main~}
      - ${d.name}: ${d.ipv4_address} (private: ${d.ipv4_address_private})
    %{endfor~}

    Django Channels (${var.django_channels_count} instances):
    %{for d in digitalocean_droplet.django_channels~}
      - ${d.name}: ${d.ipv4_address} (private: ${d.ipv4_address_private})
    %{endfor~}

    Celery Beat:
      - ${digitalocean_droplet.celery_beat.name}: ${digitalocean_droplet.celery_beat.ipv4_address} (private: ${digitalocean_droplet.celery_beat.ipv4_address_private})

    Celery Workers (${var.celery_worker_count} instances):
    %{for d in digitalocean_droplet.celery_worker~}
      - ${d.name}: ${d.ipv4_address} (private: ${d.ipv4_address_private})
    %{endfor~}

    Flower:
      - ${digitalocean_droplet.flower.name}: ${digitalocean_droplet.flower.ipv4_address} (private: ${digitalocean_droplet.flower.ipv4_address_private})

    -------------------------------------------------------------------------------
    LOAD BALANCERS & URLs
    -------------------------------------------------------------------------------

    Django Main:
      - LB IP: ${digitalocean_loadbalancer.django_main.ip}
      - URL: https://${local.domains.api}

    Django Channels:
      - LB IP: ${digitalocean_loadbalancer.django_channels.ip}
      - URL: wss://${local.domains.channels}

    Flower:
      - LB IP: ${digitalocean_loadbalancer.flower.ip}
      - URL: https://${local.domains.flower}

    -------------------------------------------------------------------------------
    KUBERNETES CLUSTER (ARQ Workers)
    -------------------------------------------------------------------------------

    Cluster:
      - ID: ${digitalocean_kubernetes_cluster.arq_cluster.id}
      - Version: ${digitalocean_kubernetes_cluster.arq_cluster.version}
      - Endpoint: ${digitalocean_kubernetes_cluster.arq_cluster.endpoint}
      - ARQ Replicas: ${var.arq_replicas}
      - KEDA Min/Max: ${var.arq_min_replicas}/${var.arq_max_replicas}

    Kubeconfig:
      - Path: ${local_file.kubeconfig.filename}

    ================================================================================

  EOT
}
