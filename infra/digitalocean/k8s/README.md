# Kubernetes Secrets Setup

This document describes how to manually create the required Kubernetes secrets that are **NOT** managed by Terraform.

## Prerequisites

1. Ensure you have `kubectl` installed and configured with the cluster context:
   ```bash
   # Install kubectl if not already installed:
   # macOS: brew install kubectl
   # Ubuntu/Debian: sudo snap install kubectl --classic
   # Arch Linux: sudo pacman -S kubectl
   
   # Configure cluster context
   export KUBECONFIG=./kubeconfig
   kubectl get nodes
   ```

## Required Secrets

### 1. ARQ Worker Secrets

The ARQ workers require database and Redis connection strings. These are stored in Vault and should be synced to Kubernetes.

#### Option A: Create secrets directly

```bash
kubectl create secret generic arq-secrets \
  --namespace=agent-platform \
  --from-literal=DATABASE_URL='postgresql://user:password@host:5432/database' \
  --from-literal=REDIS_URL='redis://user:password@host:6379/0'
```

#### Option B: Create from a file

1. Create a file named `arq-secrets.env`:
   ```
   DATABASE_URL=postgresql://user:password@host:5432/database
   REDIS_URL=redis://user:password@host:6379/0
   ```

2. Create the secret:
   ```bash
   kubectl create secret generic arq-secrets \
     --namespace=agent-platform \
     --from-env-file=arq-secrets.env
   ```

3. Delete the file:
   ```bash
   rm arq-secrets.env
   ```

#### Option C: Using Vault Agent Injector (Recommended for Production)

If you have Vault Agent Injector installed, you can annotate the deployment to inject secrets:

```yaml
spec:
  template:
    metadata:
      annotations:
        vault.hashicorp.com/agent-inject: "true"
        vault.hashicorp.com/role: "arq-worker"
        vault.hashicorp.com/agent-inject-secret-config: "secret/data/arq/config"
```

## Verify Secrets

```bash
# List secrets in namespace
kubectl get secrets -n agent-platform

# Describe secret (shows keys, not values)
kubectl describe secret arq-secrets -n agent-platform

# Verify deployment can access secrets
kubectl get pods -n agent-platform
kubectl logs -n agent-platform -l app=arq-workers --tail=50
```

## Update Secrets

To update an existing secret:

```bash
# Delete and recreate
kubectl delete secret arq-secrets -n agent-platform
kubectl create secret generic arq-secrets \
  --namespace=agent-platform \
  --from-literal=DATABASE_URL='...' \
  --from-literal=REDIS_URL='...'

# Restart pods to pick up new secrets
kubectl rollout restart deployment/arq-workers -n agent-platform
```

## Security Notes

> **WARNING**: Never commit secrets to version control.

- Secrets are base64 encoded, NOT encrypted
- Use Vault, External Secrets Operator, or Sealed Secrets for production
- Limit access to secrets using RBAC
- Rotate secrets regularly

## Troubleshooting

### Secret not found

```bash
# Check namespace
kubectl get namespaces
kubectl get secrets -n agent-platform
```

### Pod not starting due to missing secret

```bash
kubectl describe pod -n agent-platform -l app=arq-workers
# Look for "CreateContainerConfigError" in Events
```

### Verify secret content

```bash
# Decode secret value (use with caution!)
kubectl get secret arq-secrets -n agent-platform -o jsonpath='{.data.DATABASE_URL}' | base64 -d
```
