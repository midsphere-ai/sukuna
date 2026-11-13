#!/bin/bash
# =============================================================================
# Rollback Script
# =============================================================================
# This script rolls back to a previous deployment using a specific git SHA.
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
REGISTRY_NAME="${REGISTRY_NAME:-midsphere-production}"
REGISTRY_URL="registry.digitalocean.com/${REGISTRY_NAME}"

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
# Usage
# -----------------------------------------------------------------------------

usage() {
    echo "Usage: $0 <git-sha>"
    echo ""
    echo "Arguments:"
    echo "  git-sha    The git SHA tag to rollback to"
    echo ""
    echo "Examples:"
    echo "  $0 abc1234"
    echo "  GIT_SHA=abc1234 $0"
    echo ""
    echo "Environment variables:"
    echo "  GIT_SHA            Git SHA to rollback to (alternative to argument)"
    echo "  REGISTRY_NAME      Container registry name (default: midsphere-production)"
    exit 1
}

# -----------------------------------------------------------------------------
# Check Prerequisites
# -----------------------------------------------------------------------------

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed."
        exit 1
    fi

    # Check doctl
    if ! command -v doctl &> /dev/null; then
        log_error "doctl is not installed."
        exit 1
    fi

    # Check kubeconfig
    export KUBECONFIG="${SCRIPT_DIR}/kubeconfig"
    if [[ ! -f "$KUBECONFIG" ]]; then
        log_error "Kubeconfig not found at ${KUBECONFIG}"
        log_error "Run terraform first to generate kubeconfig."
        exit 1
    fi

    log_success "Prerequisites met."
}

# -----------------------------------------------------------------------------
# Verify Image Exists
# -----------------------------------------------------------------------------

verify_image() {
    local image=$1
    local tag=$2
    
    log_info "Verifying ${image}:${tag} exists in registry..."
    
    # Use doctl to check if image exists
    if ! doctl registry repository list-tags "${image}" 2>/dev/null | grep -q "${tag}"; then
        log_error "Image ${image}:${tag} not found in registry."
        log_error "Available tags:"
        doctl registry repository list-tags "${image}" 2>/dev/null || true
        exit 1
    fi
    
    log_success "Image ${image}:${tag} found."
}

# -----------------------------------------------------------------------------
# Rollback Kubernetes Deployment
# -----------------------------------------------------------------------------

rollback_kubernetes() {
    local sha=$1
    local image="${REGISTRY_URL}/platform-workers:${sha}"
    
    log_info "Rolling back Kubernetes ARQ workers to ${image}..."
    
    kubectl set image deployment/arq-workers \
        arq-worker="${image}" \
        -n agent-platform
    
    log_info "Waiting for rollout to complete..."
    kubectl rollout status deployment/arq-workers -n agent-platform --timeout=300s
    
    log_success "Kubernetes rollback complete."
}

# -----------------------------------------------------------------------------
# Rollback Droplets
# -----------------------------------------------------------------------------

rollback_droplets() {
    local sha=$1
    
    log_warning "Droplet rollback requires rebuilding droplets."
    log_warning "This is a destructive operation and will cause downtime."
    echo ""
    
    read -p "Do you want to rebuild droplets? (yes/no): " confirm
    if [[ "$confirm" != "yes" ]]; then
        log_info "Skipping droplet rollback."
        log_info "Droplets are still running the previous version."
        return
    fi
    
    log_info "To rollback droplets, you need to:"
    echo ""
    echo "1. SSH into each droplet"
    echo "2. Stop the current container:"
    echo "   docker stop <container-name>"
    echo "3. Pull the new image:"
    echo "   docker pull ${REGISTRY_URL}/platform-main:${sha}"
    echo "4. Start the new container with the same config"
    echo ""
    echo "Alternatively, run terraform apply with the new image tag."
    echo ""
    
    log_info "Droplet rollback instructions displayed."
}

# -----------------------------------------------------------------------------
# Print Summary
# -----------------------------------------------------------------------------

print_summary() {
    local sha=$1
    
    echo ""
    echo -e "${GREEN}=============================================================================${NC}"
    echo -e "${GREEN}ROLLBACK COMPLETE${NC}"
    echo -e "${GREEN}=============================================================================${NC}"
    echo ""
    echo "Rolled back to: ${sha}"
    echo ""
    echo "Kubernetes ARQ workers: ROLLED BACK"
    echo "Droplets: SEE INSTRUCTIONS ABOVE"
    echo ""
    echo "To verify:"
    echo "  ./status.sh"
    echo ""
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
    echo ""
    echo -e "${BLUE}=============================================================================${NC}"
    echo -e "${BLUE}Rollback to Previous Version${NC}"
    echo -e "${BLUE}=============================================================================${NC}"
    echo ""
    
    # Get git SHA from argument or environment
    local sha="${1:-${GIT_SHA:-}}"
    
    if [[ -z "$sha" ]]; then
        usage
    fi
    
    log_info "Rolling back to git SHA: ${sha}"
    echo ""
    
    check_prerequisites
    
    # Verify images exist
    verify_image "platform-workers" "${sha}"
    
    # Rollback Kubernetes
    rollback_kubernetes "${sha}"
    
    # Rollback Droplets (optional)
    rollback_droplets "${sha}"
    
    print_summary "${sha}"
}

main "$@"
