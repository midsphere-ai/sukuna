# DigitalOcean Provider Configuration
provider "digitalocean" {
  token = var.do_token
}

# Kubernetes Provider - configured after cluster creation
provider "kubernetes" {
  host  = digitalocean_kubernetes_cluster.arq_cluster.endpoint
  token = digitalocean_kubernetes_cluster.arq_cluster.kube_config[0].token
  cluster_ca_certificate = base64decode(
    digitalocean_kubernetes_cluster.arq_cluster.kube_config[0].cluster_ca_certificate
  )
}

# Helm Provider - for KEDA installation
provider "helm" {
  kubernetes {
    host  = digitalocean_kubernetes_cluster.arq_cluster.endpoint
    token = digitalocean_kubernetes_cluster.arq_cluster.kube_config[0].token
    cluster_ca_certificate = base64decode(
      digitalocean_kubernetes_cluster.arq_cluster.kube_config[0].cluster_ca_certificate
    )
  }
}
