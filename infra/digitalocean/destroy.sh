#!/bin/bash
# =============================================================================
# Destroy Infrastructure Script
# =============================================================================
# This script destroys all Terraform-managed infrastructure.
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
# Main
# -----------------------------------------------------------------------------

main() {
    echo ""
    echo -e "${RED}=============================================================================${NC}"
    echo -e "${RED}DESTROY INFRASTRUCTURE${NC}"
    echo -e "${RED}=============================================================================${NC}"
    echo ""
    
    log_warning "This will PERMANENTLY DESTROY all infrastructure!"
    log_warning "Resources that will be destroyed:"
    echo "  - All Droplets (Django, Celery, Flower)"
    echo "  - All Load Balancers"
    echo "  - Kubernetes Cluster (ARQ Workers)"
    echo "  - VPC and Firewall Rules"
    echo "  - DNS Records"
    echo "  - Monitoring Alert Policies"
    echo ""
    log_info "Resources that will be PRESERVED:"
    echo "  - SSL Certificates (to avoid Let's Encrypt rate limits)"
    echo "  - Container Registry"
    echo ""
    
    read -p "Type 'DESTROY' to confirm: " confirm
    if [[ "$confirm" != "DESTROY" ]]; then
        log_info "Aborted."
        exit 0
    fi
    
    cd "${SCRIPT_DIR}"
    
    if [[ ! -f terraform.tfstate ]]; then
        log_warning "No Terraform state found. Nothing to destroy."
        exit 0
    fi
    
    # Remove certificates from state to preserve them (avoid Let's Encrypt rate limits)
    log_info "Preserving SSL certificates (removing from Terraform state)..."
    terraform state rm digitalocean_certificate.main 2>/dev/null || true
    terraform state rm digitalocean_certificate.channels 2>/dev/null || true
    terraform state rm digitalocean_certificate.flower 2>/dev/null || true
    
    log_info "Destroying infrastructure..."
    terraform destroy -auto-approve
    
    # Remove kubeconfig
    if [[ -f "${SCRIPT_DIR}/kubeconfig" ]]; then
        log_info "Removing kubeconfig..."
        rm -f "${SCRIPT_DIR}/kubeconfig"
    fi
    
    # Remove terraform plan if exists
    rm -f "${SCRIPT_DIR}/tfplan"
    
    echo ""
    echo -e "${GREEN}=============================================================================${NC}"
    echo -e "${GREEN}INFRASTRUCTURE DESTROYED${NC}"
    echo -e "${GREEN}=============================================================================${NC}"
    echo ""
    
    log_success "All Terraform-managed resources have been destroyed."
    echo ""
    echo "Note: The following resources are PRESERVED and can be reused:"
    echo "  - SSL Certificates (preserved to avoid Let's Encrypt rate limits)"
    echo "  - Container Registry (may contain images)"
    echo "  - Domain configuration in DigitalOcean DNS"
    echo ""
}

main "$@"
