# =============================================================================
# DigitalOcean Infrastructure Variables
# =============================================================================

# -----------------------------------------------------------------------------
# Provider Configuration
# -----------------------------------------------------------------------------

variable "do_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Project Configuration
# -----------------------------------------------------------------------------

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "midsphere"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.project_name))
    error_message = "Project name must start with a letter and contain only lowercase letters, numbers, and hyphens."
  }
}

variable "environment" {
  description = "Environment name (production, staging, development)"
  type        = string
  default     = "production"

  validation {
    condition     = contains(["production", "staging", "development"], var.environment)
    error_message = "Environment must be one of: production, staging, development."
  }
}

variable "region" {
  description = "DigitalOcean region"
  type        = string
  default     = "blr1"

  validation {
    condition     = contains(["blr1", "nyc1", "nyc3", "sfo3", "ams3", "sgp1", "lon1", "fra1", "tor1", "syd1"], var.region)
    error_message = "Region must be a valid DigitalOcean region."
  }
}

# -----------------------------------------------------------------------------
# Domain Configuration
# -----------------------------------------------------------------------------

variable "domain" {
  description = "Base domain for all services"
  type        = string
  default     = "midsphere.ai"
}

variable "dns_ttl" {
  description = "TTL for DNS records in seconds"
  type        = number
  default     = 300
}

# -----------------------------------------------------------------------------
# Container Registry
# -----------------------------------------------------------------------------

variable "registry_name" {
  description = "DigitalOcean Container Registry name"
  type        = string
  default     = "midsphere-production"
}

# -----------------------------------------------------------------------------
# VPC Configuration
# -----------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

# -----------------------------------------------------------------------------
# Django Main Configuration
# -----------------------------------------------------------------------------

variable "django_main_count" {
  description = "Number of Django main instances"
  type        = number
  default     = 2

  validation {
    condition     = var.django_main_count >= 1 && var.django_main_count <= 10
    error_message = "Django main count must be between 1 and 10."
  }
}

variable "django_main_size" {
  description = "Droplet size for Django main instances"
  type        = string
  default     = "s-2vcpu-4gb"
}

variable "django_main_port" {
  description = "Port for Django main service"
  type        = number
  default     = 8000
}

# -----------------------------------------------------------------------------
# Django Channels Configuration
# -----------------------------------------------------------------------------

variable "django_channels_count" {
  description = "Number of Django Channels instances"
  type        = number
  default     = 1

  validation {
    condition     = var.django_channels_count >= 1 && var.django_channels_count <= 5
    error_message = "Django channels count must be between 1 and 5."
  }
}

variable "django_channels_size" {
  description = "Droplet size for Django Channels instances"
  type        = string
  default     = "s-1vcpu-2gb"
}

variable "django_channels_port" {
  description = "Port for Django Channels service"
  type        = number
  default     = 8001
}

# -----------------------------------------------------------------------------
# Celery Beat Configuration
# -----------------------------------------------------------------------------

variable "celery_beat_size" {
  description = "Droplet size for Celery Beat instance"
  type        = string
  default     = "s-1vcpu-1gb"
}

# -----------------------------------------------------------------------------
# Celery Worker Configuration
# -----------------------------------------------------------------------------

variable "celery_worker_count" {
  description = "Number of Celery worker instances"
  type        = number
  default     = 2

  validation {
    condition     = var.celery_worker_count >= 1 && var.celery_worker_count <= 10
    error_message = "Celery worker count must be between 1 and 10."
  }
}

variable "celery_worker_size" {
  description = "Droplet size for Celery worker instances"
  type        = string
  default     = "s-1vcpu-2gb"
}

variable "celery_worker_concurrency" {
  description = "Celery worker concurrency"
  type        = number
  default     = 4
}

# -----------------------------------------------------------------------------
# Flower Configuration
# -----------------------------------------------------------------------------

variable "flower_size" {
  description = "Droplet size for Flower instance"
  type        = string
  default     = "s-1vcpu-1gb"
}

variable "flower_port" {
  description = "Port for Flower service"
  type        = number
  default     = 5555
}

variable "flower_user" {
  description = "Flower basic auth username"
  type        = string
  sensitive   = true
}

variable "flower_password" {
  description = "Flower basic auth password"
  type        = string
  sensitive   = true
}

variable "flower_allowed_ips" {
  description = "List of IP addresses allowed to access Flower"
  type        = list(string)
  default     = []
}

# -----------------------------------------------------------------------------
# Kubernetes / ARQ Configuration
# -----------------------------------------------------------------------------

variable "k8s_version" {
  description = "Kubernetes version prefix (DO will select latest matching version)"
  type        = string
  default     = "1.29"
}

variable "k8s_node_size" {
  description = "Droplet size for Kubernetes nodes"
  type        = string
  default     = "s-4vcpu-8gb"
}

variable "k8s_node_min" {
  description = "Minimum number of Kubernetes nodes"
  type        = number
  default     = 1
}

variable "k8s_node_max" {
  description = "Maximum number of Kubernetes nodes"
  type        = number
  default     = 3
}

variable "arq_replicas" {
  description = "Number of ARQ worker replicas"
  type        = number
  default     = 2
}

variable "arq_min_replicas" {
  description = "Minimum ARQ worker replicas (for KEDA)"
  type        = number
  default     = 5
}

variable "arq_max_replicas" {
  description = "Maximum ARQ worker replicas (for KEDA)"
  type        = number
  default     = 36
}

variable "arq_memory_request" {
  description = "Memory request for ARQ pods"
  type        = string
  default     = "400Mi"
}

variable "arq_memory_limit" {
  description = "Memory limit for ARQ pods"
  type        = string
  default     = "512Mi"
}

variable "arq_cpu_request" {
  description = "CPU request for ARQ pods"
  type        = string
  default     = "200m"
}

variable "arq_cpu_limit" {
  description = "CPU limit for ARQ pods"
  type        = string
  default     = "500m"
}

# -----------------------------------------------------------------------------
# Monitoring Configuration
# -----------------------------------------------------------------------------

variable "alert_emails" {
  description = "List of email addresses for alerts"
  type        = list(string)
  default     = []
}

variable "cpu_alert_threshold" {
  description = "CPU usage percentage threshold for alerts"
  type        = number
  default     = 80
}

variable "memory_alert_threshold" {
  description = "Memory usage percentage threshold for alerts"
  type        = number
  default     = 85
}

variable "disk_alert_threshold" {
  description = "Disk usage percentage threshold for alerts"
  type        = number
  default     = 90
}

# -----------------------------------------------------------------------------
# SSH Configuration
# -----------------------------------------------------------------------------

variable "ssh_keys" {
  description = "List of SSH key IDs or fingerprints for droplet access"
  type        = list(string)
  default     = []
}

# -----------------------------------------------------------------------------
# Vault Configuration (for reference in cloud-init)
# -----------------------------------------------------------------------------

variable "vault_addr" {
  description = "Vault/OpenBao server address"
  type        = string
  default     = ""
}

variable "vault_token" {
  description = "Vault/OpenBao authentication token"
  type        = string
  sensitive   = true
  default     = ""
}

# -----------------------------------------------------------------------------
# Tags
# -----------------------------------------------------------------------------

variable "common_tags" {
  description = "Common tags to apply to all resources"
  type        = list(string)
  default     = []
}
