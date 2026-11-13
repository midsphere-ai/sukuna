# =============================================================================
# Droplet Configurations
# =============================================================================

# -----------------------------------------------------------------------------
# Cloud-Init Template for Docker Setup
# -----------------------------------------------------------------------------

locals {
  # Docker config JSON - write directly without base64 decode
  docker_config_json = digitalocean_container_registry_docker_credentials.main.docker_credentials

  # Base cloud-init script for all droplets
  cloud_init_base = <<-EOF
    #cloud-config
    package_update: true
    package_upgrade: true

    packages:
      - apt-transport-https
      - ca-certificates
      - curl
      - gnupg
      - lsb-release

    write_files:
      - path: /root/.docker/config.json
        permissions: '0600'
        content: |
          ${local.docker_config_json}

    runcmd:
      # Install Docker
      - curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
      - echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
      - apt-get update
      - apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
      - systemctl enable docker
      - systemctl start docker
  EOF

  # Common environment variables for all containers
  common_env_vars = <<-EOF
          -e VAULT_ADDR=${var.vault_addr} \
          -e VAULT_TOKEN=${var.vault_token} \
          -e DJANGO_SETTINGS_MODULE=config.settings.production
  EOF

  # Django Main cloud-init
  cloud_init_django_main = <<-EOF
    ${local.cloud_init_base}
      # Pull and run Django Main container
      - docker pull ${local.images.main}
      - |
        docker run -d \
          --name django-main \
          --restart unless-stopped \
          -p ${var.django_main_port}:${var.django_main_port} \
          -e VAULT_ADDR=${var.vault_addr} \
          -e VAULT_TOKEN=${var.vault_token} \
          -e DJANGO_SETTINGS_MODULE=config.settings.production \
          ${local.images.main} \
          uv run uvicorn config.asgi:application --host 0.0.0.0 --port ${var.django_main_port} --workers 4
  EOF

  # Django Channels cloud-init
  cloud_init_django_channels = <<-EOF
    ${local.cloud_init_base}
      # Pull and run Django Channels container
      - docker pull ${local.images.channels}
      - |
        docker run -d \
          --name django-channels \
          --restart unless-stopped \
          -p ${var.django_channels_port}:${var.django_channels_port} \
          -e VAULT_ADDR=${var.vault_addr} \
          -e VAULT_TOKEN=${var.vault_token} \
          -e DJANGO_SETTINGS_MODULE=config.settings.production \
          ${local.images.channels} \
          uv run daphne -b 0.0.0.0 -p ${var.django_channels_port} config.asgi:application
  EOF

  # Celery Beat cloud-init
  cloud_init_celery_beat = <<-EOF
    ${local.cloud_init_base}
      # Pull and run Celery Beat container
      - docker pull ${local.images.celery}
      - |
        docker run -d \
          --name celery-beat \
          --restart unless-stopped \
          -e VAULT_ADDR=${var.vault_addr} \
          -e VAULT_TOKEN=${var.vault_token} \
          -e DJANGO_SETTINGS_MODULE=config.settings.production \
          ${local.images.celery} \
          uv run celery -A config beat -l info --pidfile=/tmp/celerybeat.pid
  EOF

  # Celery Worker cloud-init
  cloud_init_celery_worker = <<-EOF
    ${local.cloud_init_base}
      # Pull and run Celery Worker container
      - docker pull ${local.images.celery}
      - |
        docker run -d \
          --name celery-worker \
          --restart unless-stopped \
          -e VAULT_ADDR=${var.vault_addr} \
          -e VAULT_TOKEN=${var.vault_token} \
          -e DJANGO_SETTINGS_MODULE=config.settings.production \
          ${local.images.celery} \
          uv run celery -A config worker -l info --concurrency=${var.celery_worker_concurrency} --max-tasks-per-child=1000
  EOF

  # Flower cloud-init
  cloud_init_flower = <<-EOF
    ${local.cloud_init_base}
      # Pull and run Flower container
      - docker pull ${local.images.celery}
      - |
        docker run -d \
          --name flower \
          --restart unless-stopped \
          -p ${var.flower_port}:${var.flower_port} \
          -e VAULT_ADDR=${var.vault_addr} \
          -e VAULT_TOKEN=${var.vault_token} \
          -e DJANGO_SETTINGS_MODULE=config.settings.production \
          -e CELERY_FLOWER_USER=${var.flower_user} \
          -e CELERY_FLOWER_PASSWORD=${var.flower_password} \
          ${local.images.celery} \
          uv run celery -A config flower --port=${var.flower_port} --basic_auth=${var.flower_user}:${var.flower_password}
  EOF
}

# =============================================================================
# Django Main Droplets
# =============================================================================

resource "digitalocean_droplet" "django_main" {
  count = var.django_main_count

  name     = "${local.name_prefix}-django-main-${count.index + 1}"
  size     = var.django_main_size
  image    = "ubuntu-22-04-x64"
  region   = var.region
  vpc_uuid = digitalocean_vpc.main.id

  ssh_keys = var.ssh_keys

  user_data = local.cloud_init_django_main

  tags = [
    digitalocean_tag.production.id,
    digitalocean_tag.django_main.id,
  ]

  monitoring = true

  graceful_shutdown = true

  lifecycle {
    create_before_destroy = true
  }

  timeouts {
    create = "10m"
    update = "10m"
    delete = "5m"
  }

  depends_on = [
    digitalocean_vpc.main,
    digitalocean_container_registry_docker_credentials.main,
  ]
}

# =============================================================================
# Django Channels Droplets
# =============================================================================

resource "digitalocean_droplet" "django_channels" {
  count = var.django_channels_count

  name     = "${local.name_prefix}-django-channels-${count.index + 1}"
  size     = var.django_channels_size
  image    = "ubuntu-22-04-x64"
  region   = var.region
  vpc_uuid = digitalocean_vpc.main.id

  ssh_keys = var.ssh_keys

  user_data = local.cloud_init_django_channels

  tags = [
    digitalocean_tag.production.id,
    digitalocean_tag.django_channels.id,
  ]

  monitoring = true

  graceful_shutdown = true

  lifecycle {
    create_before_destroy = true
  }

  timeouts {
    create = "10m"
    update = "10m"
    delete = "5m"
  }

  depends_on = [
    digitalocean_vpc.main,
    digitalocean_container_registry_docker_credentials.main,
  ]
}

# =============================================================================
# Celery Beat Droplet (Single Instance)
# =============================================================================

resource "digitalocean_droplet" "celery_beat" {
  name     = "${local.name_prefix}-celery-beat"
  size     = var.celery_beat_size
  image    = "ubuntu-22-04-x64"
  region   = var.region
  vpc_uuid = digitalocean_vpc.main.id

  ssh_keys = var.ssh_keys

  user_data = local.cloud_init_celery_beat

  tags = [
    digitalocean_tag.production.id,
    digitalocean_tag.celery_beat.id,
  ]

  monitoring = true

  graceful_shutdown = true

  lifecycle {
    create_before_destroy = true
    # Prevent accidental deletion - Celery Beat should never have more than 1 instance
    prevent_destroy = false
  }

  timeouts {
    create = "10m"
    update = "10m"
    delete = "5m"
  }

  depends_on = [
    digitalocean_vpc.main,
    digitalocean_container_registry_docker_credentials.main,
  ]
}

# =============================================================================
# Celery Worker Droplets
# =============================================================================

resource "digitalocean_droplet" "celery_worker" {
  count = var.celery_worker_count

  name     = "${local.name_prefix}-celery-worker-${count.index + 1}"
  size     = var.celery_worker_size
  image    = "ubuntu-22-04-x64"
  region   = var.region
  vpc_uuid = digitalocean_vpc.main.id

  ssh_keys = var.ssh_keys

  user_data = local.cloud_init_celery_worker

  tags = [
    digitalocean_tag.production.id,
    digitalocean_tag.celery_worker.id,
  ]

  monitoring = true

  graceful_shutdown = true

  lifecycle {
    create_before_destroy = true
  }

  timeouts {
    create = "10m"
    update = "10m"
    delete = "5m"
  }

  depends_on = [
    digitalocean_vpc.main,
    digitalocean_container_registry_docker_credentials.main,
  ]
}

# =============================================================================
# Flower Droplet
# =============================================================================

resource "digitalocean_droplet" "flower" {
  name     = "${local.name_prefix}-flower"
  size     = var.flower_size
  image    = "ubuntu-22-04-x64"
  region   = var.region
  vpc_uuid = digitalocean_vpc.main.id

  ssh_keys = var.ssh_keys

  user_data = local.cloud_init_flower

  tags = [
    digitalocean_tag.production.id,
    digitalocean_tag.flower.id,
  ]

  monitoring = true

  graceful_shutdown = true

  lifecycle {
    create_before_destroy = true
  }

  timeouts {
    create = "10m"
    update = "10m"
    delete = "5m"
  }

  depends_on = [
    digitalocean_vpc.main,
    digitalocean_container_registry_docker_credentials.main,
  ]
}
