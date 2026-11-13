# DigitalOcean Infrastructure

This directory contains Terraform configurations and scripts for deploying the Midsphere production infrastructure on DigitalOcean.

## Architecture Overview

```
                                    ┌─────────────────────────────────────────────────────────────────┐
                                    │                         DigitalOcean                            │
                                    │                                                                 │
    Internet                        │   ┌─────────────────────────────────────────────────────────┐  │
       │                            │   │                    VPC (10.0.0.0/16)                    │  │
       │                            │   │                                                         │  │
       ▼                            │   │  ┌─────────┐    ┌─────────┐    ┌─────────┐             │  │
  ┌─────────┐                       │   │  │ Django  │    │ Django  │    │ Celery  │             │  │
  │   LB    │──────────────────────────────│  Main   │    │  Main   │    │  Beat   │             │  │
  │  (API)  │                       │   │  │  (1)    │    │  (2)    │    │         │             │  │
  └─────────┘                       │   │  └─────────┘    └─────────┘    └─────────┘             │  │
       │                            │   │        │              │              │                  │  │
       │                            │   │        └──────────────┴──────────────┘                  │  │
       │                            │   │                       │                                 │  │
       ▼                            │   │                       ▼                                 │  │
  ┌─────────┐                       │   │  ┌─────────┐    ┌─────────┐    ┌─────────┐             │  │
  │   LB    │──────────────────────────────│ Channels│    │ Celery  │    │ Celery  │             │  │
  │(Channels)│                      │   │  │         │    │ Worker  │    │ Worker  │             │  │
  └─────────┘                       │   │  └─────────┘    │  (1)    │    │  (2)    │             │  │
       │                            │   │                 └─────────┘    └─────────┘             │  │
       │                            │   │                                                         │  │
       ▼                            │   │  ┌─────────┐                                           │  │
  ┌─────────┐                       │   │  │ Flower  │                                           │  │
  │   LB    │──────────────────────────────│         │                                           │  │
  │(Flower) │                       │   │  └─────────┘                                           │  │
  └─────────┘                       │   │                                                         │  │
                                    │   │  ┌─────────────────────────────────────────────────┐   │  │
                                    │   │  │              Kubernetes Cluster                 │   │  │
                                    │   │  │  ┌───────┐ ┌───────┐ ┌───────┐ ... ┌───────┐   │   │  │
                                    │   │  │  │  ARQ  │ │  ARQ  │ │  ARQ  │     │  ARQ  │   │   │  │
                                    │   │  │  │Worker1│ │Worker2│ │Worker3│     │Worker12│  │   │  │
                                    │   │  │  └───────┘ └───────┘ └───────┘     └───────┘   │   │  │
                                    │   │  │                    + KEDA Autoscaling          │   │  │
                                    │   │  └─────────────────────────────────────────────────┘   │  │
                                    │   └─────────────────────────────────────────────────────────┘  │
                                    └─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

### Required Tools

1. **Terraform** (>= 1.5.0)
   ```bash
   # macOS (via tfenv)
   brew install tfenv
   tfenv install 1.5.0
   tfenv use 1.5.0
   
   # Arch Linux
   yay -S tfenv  # via AUR, then:
   tfenv install 1.5.0
   tfenv use 1.5.0
   # Or install directly:
   sudo pacman -S terraform
   
   # Or direct download
   # https://developer.hashicorp.com/terraform/downloads
   ```

2. **doctl** (DigitalOcean CLI)
   ```bash
   # macOS
   brew install doctl
   
   # Linux (Ubuntu/Debian)
   snap install doctl
   
   # Arch Linux
   yay -S doctl  # via AUR
   
   # Authenticate
   doctl auth init
   ```

3. **kubectl** (Kubernetes CLI)
   ```bash
   # macOS
   brew install kubectl
   
   # Linux (Ubuntu/Debian)
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
   chmod +x kubectl
   sudo mv kubectl /usr/local/bin/
   
   # Arch Linux
   sudo pacman -S kubectl
   ```

4. **Docker**
   ```bash
   # macOS/Windows: Install Docker Desktop
   # https://docs.docker.com/get-docker/
   
   # Linux (Ubuntu/Debian): Install Docker Engine
   # https://docs.docker.com/engine/install/ubuntu/
   
   # Arch Linux
   sudo pacman -S docker docker-compose
   sudo systemctl enable --now docker
   sudo usermod -aG docker $USER  # Add user to docker group (re-login required)
   ```

### DigitalOcean Setup

1. **API Token**: Create at https://cloud.digitalocean.com/account/api/tokens
   - Needs Read + Write access

2. **Domain**: Add `midsphere.ai` to DigitalOcean DNS
   - Go to Networking > Domains
   - Add your domain and configure nameservers with your registrar

3. **SSH Keys** (optional): Add SSH keys for droplet access
   - Go to Settings > Security > SSH Keys

## Quick Start

### 1. Configure Variables

```bash
# Copy the example file
cp terraform.tfvars.example terraform.tfvars

# Edit with your values
nano terraform.tfvars
```

Required variables:
- `do_token` - Your DigitalOcean API token
- `flower_user` - Username for Flower basic auth
- `flower_password` - Password for Flower basic auth

### 2. Initial Deployment

```bash
# Make scripts executable
chmod +x *.sh

# Run full deployment
./deploy.sh
```

This will:
1. Build and push Docker images
2. Create all infrastructure with Terraform
3. Verify Kubernetes deployment
4. Print deployment summary

### 3. Configure Secrets

After deployment, you need to manually configure secrets:

#### Kubernetes (ARQ Workers)
```bash
# Set kubeconfig
export KUBECONFIG=./kubeconfig

# Create secrets
kubectl create secret generic arq-secrets \
  --namespace=agent-platform \
  --from-literal=DATABASE_URL='your-database-url' \
  --from-literal=REDIS_URL='your-redis-url'

# Restart workers to pick up secrets
kubectl rollout restart deployment/arq-workers -n agent-platform
```

See [k8s/README.md](k8s/README.md) for more details.

#### Droplets (Vault)
Secrets are injected from Vault. Configure Vault with:
- `DATABASE_URL`
- `REDIS_URL`
- Other application secrets

## Directory Structure

```
digitalocean/
├── k8s/                        # Kubernetes manifests (for reference)
│   ├── namespace.yaml
│   ├── arq-deployment.yaml
│   ├── keda-scaledobject.yaml
│   ├── pdb.yaml
│   └── README.md
├── build-and-push.sh          # Build and push Docker images
├── deploy.sh                  # Full deployment script
├── destroy.sh                 # Destroy all infrastructure
├── rollback.sh                # Rollback to previous version
├── status.sh                  # Check service status
├── versions.tf                # Terraform version constraints
├── providers.tf               # Provider configurations
├── variables.tf               # Input variables
├── terraform.tfvars.example   # Example variables file
├── main.tf                    # Main configuration
├── vpc.tf                     # VPC and registry
├── firewall.tf                # Firewall rules
├── droplets.tf                # Compute instances
├── loadbalancers.tf           # Load balancers
├── dns.tf                     # DNS records
├── kubernetes.tf              # K8s cluster configuration
├── monitoring.tf              # Alerts and monitoring
├── outputs.tf                 # Output values
└── README.md                  # This file
```

## Common Operations

### Check Status

```bash
./status.sh
```

### Update Deployment

To update with new code:

```bash
# Build and push new images
./build-and-push.sh

# Update Kubernetes deployment
export KUBECONFIG=./kubeconfig
kubectl rollout restart deployment/arq-workers -n agent-platform

# For droplets, SSH in and restart containers:
ssh root@<droplet-ip>
docker pull registry.digitalocean.com/midsphere-production/platform-main:latest
docker stop django-main
docker rm django-main
# Run new container with same config...
```

### Rollback

```bash
# Get the git SHA to rollback to
git log --oneline -10

# Rollback
./rollback.sh abc1234
```

### Destroy Everything

```bash
./destroy.sh
```

### Scale Workers

#### Kubernetes (ARQ)
```bash
export KUBECONFIG=./kubeconfig

# Manual scale
kubectl scale deployment/arq-workers -n agent-platform --replicas=20

# KEDA will auto-scale based on queue length
```

#### Droplets
Modify `terraform.tfvars`:
```hcl
django_main_count   = 3   # Scale from 2 to 3
celery_worker_count = 4   # Scale from 2 to 4
```

Then run:
```bash
terraform apply
```

## Configuration Reference

### Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `do_token` | DigitalOcean API token | (required) |
| `region` | Deployment region | `blr1` |
| `project_name` | Project name prefix | `midsphere` |
| `environment` | Environment name | `production` |
| `domain` | Base domain | `midsphere.ai` |
| `django_main_count` | Number of Django instances | `2` |
| `django_main_size` | Django droplet size | `s-2vcpu-4gb` |
| `celery_worker_count` | Number of Celery workers | `2` |
| `k8s_node_min` | Min K8s nodes | `1` |
| `k8s_node_max` | Max K8s nodes | `3` |
| `arq_replicas` | ARQ worker replicas | `12` |
| `alert_emails` | Alert email addresses | `[]` |

See `variables.tf` for complete list.

### Droplet Sizes

| Service | Default Size | vCPUs | Memory |
|---------|--------------|-------|--------|
| Django Main | `s-2vcpu-4gb` | 2 | 4 GB |
| Django Channels | `s-1vcpu-2gb` | 1 | 2 GB |
| Celery Beat | `s-1vcpu-1gb` | 1 | 1 GB |
| Celery Worker | `s-1vcpu-2gb` | 1 | 2 GB |
| Flower | `s-1vcpu-1gb` | 1 | 1 GB |
| K8s Node | `s-4vcpu-8gb` | 4 | 8 GB |

## Troubleshooting

### Terraform Errors

**Error: Domain not found**
```
Ensure the domain is added to DigitalOcean DNS:
1. Go to Networking > Domains
2. Add midsphere.ai
```

**Error: Rate limit exceeded**
```
Wait a few minutes and retry. Consider adding delay between operations.
```

### Kubernetes Issues

**Pods stuck in Pending**
```bash
kubectl describe pod <pod-name> -n agent-platform
# Check Events section for issues
```

**Pods in CrashLoopBackOff**
```bash
kubectl logs <pod-name> -n agent-platform --previous
# Check for application errors
```

**KEDA not scaling**
```bash
kubectl get scaledobject -n agent-platform
kubectl describe scaledobject arq-workers-scaler -n agent-platform
# Check Conditions section
```

### Health Check Failures

**Load balancer shows unhealthy backends**
```bash
# SSH to droplet
ssh root@<ip>

# Check container status
docker ps
docker logs django-main

# Check if app is listening
curl localhost:8000/health/
```

### Connection Issues

**Cannot connect to droplets**
```bash
# Verify firewall allows SSH
doctl compute firewall list

# Check droplet status
doctl compute droplet list
```

## Security Notes

1. **Secrets Management**
   - `terraform.tfvars` contains sensitive data - NEVER commit it
   - Use Vault for application secrets
   - Rotate API tokens periodically

2. **Network Security**
   - All inter-service communication is within VPC
   - Only load balancers expose public endpoints
   - Flower is protected by IP whitelist (optional) and basic auth

3. **Access Control**
   - Use SSH keys for droplet access
   - Enable 2FA on DigitalOcean account
   - Use RBAC for Kubernetes access

## Monitoring

### DigitalOcean Dashboard
- CPU, memory, disk usage for droplets
- Load balancer metrics
- Kubernetes cluster insights

### Alert Policies
Alerts are configured for:
- CPU usage > 80%
- Memory usage > 85%
- Disk usage > 90%
- Load balancer down
- Kubernetes node not ready

Configure alert emails in `terraform.tfvars`:
```hcl
alert_emails = ["ops@midsphere.ai", "devops@midsphere.ai"]
```

## Cost Estimation

| Resource | Count | Size | Estimated Monthly Cost |
|----------|-------|------|------------------------|
| Django Main | 2 | s-2vcpu-4gb | $48 |
| Django Channels | 1 | s-1vcpu-2gb | $12 |
| Celery Beat | 1 | s-1vcpu-1gb | $6 |
| Celery Workers | 2 | s-1vcpu-2gb | $24 |
| Flower | 1 | s-1vcpu-1gb | $6 |
| K8s Cluster | 1 | - | $12 (control plane) |
| K8s Nodes | 1-3 | s-4vcpu-8gb | $48-144 |
| Load Balancers | 3 | - | $36 |
| Container Registry | 1 | Professional | $20 |
| **Total (min)** | | | **~$212/month** |
| **Total (max)** | | | **~$308/month** |

Note: Costs may vary. Check DigitalOcean pricing for current rates.

## Support

For issues with this infrastructure configuration, check:
1. DigitalOcean status: https://status.digitalocean.com
2. Terraform DO provider docs: https://registry.terraform.io/providers/digitalocean/digitalocean/latest/docs
3. KEDA docs: https://keda.sh/docs/
