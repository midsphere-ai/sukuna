#!/bin/bash
# =============================================================================
# Full Deployment Script
# =============================================================================
# This script performs a complete destroy and redeploy of the infrastructure.
# WARNING: This will cause downtime!
# =============================================================================

set -o errexit
set -o pipefail
set -o nounset

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# -----------------------------------------------------------------------------
# Check Prerequisites
# -----------------------------------------------------------------------------

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check terraform
    if ! command -v terraform &> /dev/null; then
        log_error "terraform is not installed."
        exit 1
    fi

    # Check doctl
    if ! command -v doctl &> /dev/null; then
        log_error "doctl is not installed."
        exit 1
    fi

    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed."
        exit 1
    fi

    # Check terraform.tfvars exists
    if [[ ! -f "${SCRIPT_DIR}/terraform.tfvars" ]]; then
        log_error "terraform.tfvars not found. Copy terraform.tfvars.example and fill in values."
        exit 1
    fi

    log_success "All prerequisites met."
}

# -----------------------------------------------------------------------------
# Destroy Existing Infrastructure
# -----------------------------------------------------------------------------

destroy_infrastructure() {
    log_warning "Destroying existing infrastructure..."
    log_warning "This will cause DOWNTIME!"
    
    echo ""
    read -p "Are you sure you want to destroy existing infrastructure? (yes/no): " confirm
    if [[ "$confirm" != "yes" ]]; then
        log_info "Aborted."
        exit 0
    fi

    cd "${SCRIPT_DIR}"
    
    if [[ -f terraform.tfstate ]]; then
        terraform destroy -auto-approve
        log_success "Infrastructure destroyed."
    else
        log_info "No existing state found. Skipping destroy."
    fi
}

# -----------------------------------------------------------------------------
# Build and Push Images
# -----------------------------------------------------------------------------

build_images() {
    log_info "Building and pushing Docker images..."
    
    if [[ -x "${SCRIPT_DIR}/build-and-push.sh" ]]; then
        "${SCRIPT_DIR}/build-and-push.sh"
    else
        chmod +x "${SCRIPT_DIR}/build-and-push.sh"
        "${SCRIPT_DIR}/build-and-push.sh"
    fi
    
    log_success "Images built and pushed."
}

# -----------------------------------------------------------------------------
# Apply Terraform
# -----------------------------------------------------------------------------

apply_terraform() {
    log_info "Initializing Terraform..."
    cd "${SCRIPT_DIR}"
    
    terraform init -upgrade
    log_success "Terraform initialized."

    log_info "Running Terraform plan..."
    terraform plan -out=tfplan
    
    echo ""
    echo "============================================================================="
    echo "TERRAFORM PLAN COMPLETE"
    echo "============================================================================="
    echo ""
    
    read -p "Review the plan above. Proceed with apply? (yes/no): " confirm
    if [[ "$confirm" != "yes" ]]; then
        log_info "Aborted."
        rm -f tfplan
        exit 0
    fi

    log_info "Applying Terraform configuration..."
    terraform apply tfplan
    rm -f tfplan
    
    log_success "Terraform apply complete."
}

# -----------------------------------------------------------------------------
# Verify Kubernetes Deployment
# -----------------------------------------------------------------------------

verify_kubernetes() {
    log_info "Verifying Kubernetes deployment..."
    
    export KUBECONFIG="${SCRIPT_DIR}/kubeconfig"
    
    if [[ ! -f "$KUBECONFIG" ]]; then
        log_warning "Kubeconfig not found. Skipping Kubernetes verification."
        return
    fi
    
    log_info "Waiting for ARQ workers to be ready..."
    
    # Wait for namespace
    kubectl wait --for=condition=Active namespace/agent-platform --timeout=60s || true
    
    # Wait for deployment
    kubectl rollout status deployment/arq-workers -n agent-platform --timeout=300s || true
    
    # Show pods
    echo ""
    log_info "ARQ Worker Pods:"
    kubectl get pods -n agent-platform -l app=arq-workers
    
    log_success "Kubernetes verification complete."
}

# -----------------------------------------------------------------------------
# Print Summary
# -----------------------------------------------------------------------------

print_summary() {
    cd "${SCRIPT_DIR}"
    
    echo ""
    echo -e "${GREEN}=============================================================================${NC}"
    echo -e "${GREEN}DEPLOYMENT COMPLETE${NC}"
    echo -e "${GREEN}=============================================================================${NC}"
    echo ""
    
    # Print Terraform outputs
    terraform output deployment_summary
    
    echo ""
    echo "Next steps:"
    echo "  1. Verify services are healthy: ./status.sh"
    echo "  2. Create Kubernetes secrets: see k8s/README.md"
    echo "  3. Configure Vault secrets on droplets"
    echo ""
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
    echo ""
    echo -e "${BLUE}=============================================================================${NC}"
    echo -e "${BLUE}Midsphere Production Deployment${NC}"
    echo -e "${BLUE}=============================================================================${NC}"
    echo ""
    
    check_prerequisites
    destroy_infrastructure
    apply_terraform
    verify_kubernetes
    print_summary
}

main "$@"
