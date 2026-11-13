# =============================================================================
# Kubernetes Cluster Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# Kubernetes Cluster
# -----------------------------------------------------------------------------

resource "digitalocean_kubernetes_cluster" "agent_cluster" {
  name    = "${local.name_prefix}-agent-cluster"
  region  = var.region
  version = data.digitalocean_kubernetes_versions.available.latest_version

  vpc_uuid = digitalocean_vpc.main.id

  # Automatic upgrades on Sunday 4:00 AM IST (Saturday 22:30 UTC)
  auto_upgrade = true
  maintenance_policy {
    start_time = "22:30"
    day        = "saturday"
  }

  # Enable HA control plane for production
  ha = true

  # Node pool for agent platform workers
  node_pool {
    name       = "agent-worker-pool"
    size       = var.k8s_node_size
    node_count = var.k8s_node_min

    auto_scale = true
    min_nodes  = var.k8s_node_min
    max_nodes  = var.k8s_node_max

    tags = [
      "production",
      "agent-platform",
      "workers",
    ]

    labels = {
      service     = "agent-worker"
      environment = var.environment
    }
  }

  tags = [
    digitalocean_tag.production.id,
    digitalocean_tag.arq_workers.id,
  ]

  depends_on = [
    digitalocean_vpc.main,
  ]
}

# -----------------------------------------------------------------------------
# Registry Integration with Kubernetes
# -----------------------------------------------------------------------------

resource "digitalocean_container_registry_docker_credentials" "k8s" {
  registry_name = var.registry_name
  write         = false
  expiry_seconds = 31536000  # 1 year

  depends_on = [
    digitalocean_kubernetes_cluster.agent_cluster,
  ]
}

# Create Kubernetes secret for registry access
resource "kubernetes_secret" "registry_credentials" {
  metadata {
    name      = "do-registry-credentials"
    namespace = kubernetes_namespace.agent_platform.metadata[0].name
  }

  type = "kubernetes.io/dockerconfigjson"

  data = {
    ".dockerconfigjson" = digitalocean_container_registry_docker_credentials.k8s.docker_credentials
  }

  depends_on = [
    kubernetes_namespace.agent_platform,
    digitalocean_container_registry_docker_credentials.k8s,
  ]
}

# -----------------------------------------------------------------------------
# Kubernetes Namespace
# -----------------------------------------------------------------------------

resource "kubernetes_namespace" "agent_platform" {
  metadata {
    name = "agent-platform"

    labels = {
      name        = "agent-platform"
      environment = var.environment
      managed-by  = "terraform"
    }
  }

  depends_on = [digitalocean_kubernetes_cluster.agent_cluster]
}

# -----------------------------------------------------------------------------
# KEDA Installation via Helm
# -----------------------------------------------------------------------------

resource "helm_release" "keda" {
  name             = "keda"
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  namespace        = "keda"
  create_namespace = true
  version          = "2.13.0"

  set {
    name  = "metricsServer.useHostNetwork"
    value = "false"
  }

  depends_on = [digitalocean_kubernetes_cluster.agent_cluster]
}

# -----------------------------------------------------------------------------
# Save Kubeconfig to Local File
# -----------------------------------------------------------------------------

resource "local_file" "kubeconfig" {
  content  = digitalocean_kubernetes_cluster.agent_cluster.kube_config[0].raw_config
  filename = "${path.module}/kubeconfig"

  file_permission = "0600"

  depends_on = [digitalocean_kubernetes_cluster.agent_cluster]
}
