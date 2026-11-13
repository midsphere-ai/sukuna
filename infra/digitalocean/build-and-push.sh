#!/bin/bash
# =============================================================================
# Build and Push Docker Images to DigitalOcean Container Registry
# =============================================================================
# This script builds 4 production Docker images and pushes them to the
# DigitalOcean container registry with both :latest and :${GIT_SHA} tags.
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

# Configuration
REGISTRY_NAME="${REGISTRY_NAME:-midsphere-production}"
REGISTRY_URL="registry.digitalocean.com/${REGISTRY_NAME}"
PROJECT_ROOT="${PROJECT_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
DOCKERFILE_PATH="${PROJECT_ROOT}/infra/compose/production/django/Dockerfile"

# Get git SHA for versioning
GIT_SHA="${GIT_SHA:-$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')}"

# Image names
IMAGES=(
    "platform-main"
    "platform-channels"
    "platform-celery"
    "platform-workers"
)

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

    # Check doctl
    if ! command -v doctl &> /dev/null; then
        log_error "doctl is not installed. Install it from https://docs.digitalocean.com/reference/doctl/how-to/install/"
        exit 1
    fi

    # Check docker
    if ! command -v docker &> /dev/null; then
        log_error "docker is not installed."
        exit 1
    fi

    # Check doctl authentication
    if ! doctl account get &> /dev/null; then
        log_error "doctl is not authenticated. Run: doctl auth init"
        exit 1
    fi

    log_success "All prerequisites met."
}

# -----------------------------------------------------------------------------
# Verify/Create Container Registry
# -----------------------------------------------------------------------------

verify_registry() {
    log_info "Verifying container registry '${REGISTRY_NAME}'..."

    if doctl registry get 2>/dev/null | grep -q "${REGISTRY_NAME}"; then
        log_success "Registry '${REGISTRY_NAME}' exists."
    else
        log_warning "Registry '${REGISTRY_NAME}' not found. Creating..."
        doctl registry create "${REGISTRY_NAME}" --region blr1 --subscription-tier professional
        log_success "Registry '${REGISTRY_NAME}' created."
    fi

    # Login to registry
    log_info "Logging into container registry..."
    doctl registry login
    log_success "Logged into registry."
}

# -----------------------------------------------------------------------------
# Build Docker Images
# -----------------------------------------------------------------------------

build_images() {
    log_info "Building Docker images from ${DOCKERFILE_PATH}..."
    log_info "Git SHA: ${GIT_SHA}"

    cd "${PROJECT_ROOT}"

    for image in "${IMAGES[@]}"; do
        log_info "Building ${image}..."

        # Build the image
        docker build \
            -t "${REGISTRY_URL}/${image}:latest" \
            -t "${REGISTRY_URL}/${image}:${GIT_SHA}" \
            -f "${DOCKERFILE_PATH}" \
            --build-arg BUILD_ENVIRONMENT=production \
            .

        log_success "Built ${image}:latest and ${image}:${GIT_SHA}"
    done
}

# -----------------------------------------------------------------------------
# Push Docker Images
# -----------------------------------------------------------------------------

push_images() {
    log_info "Pushing Docker images to registry..."

    for image in "${IMAGES[@]}"; do
        log_info "Pushing ${image}..."

        # Push latest tag
        docker push "${REGISTRY_URL}/${image}:latest"
        log_success "Pushed ${image}:latest"

        # Push SHA tag
        docker push "${REGISTRY_URL}/${image}:${GIT_SHA}"
        log_success "Pushed ${image}:${GIT_SHA}"
    done
}

# -----------------------------------------------------------------------------
# Print Summary
# -----------------------------------------------------------------------------

print_summary() {
    echo ""
    echo -e "${GREEN}=============================================================================${NC}"
    echo -e "${GREEN}BUILD AND PUSH COMPLETE${NC}"
    echo -e "${GREEN}=============================================================================${NC}"
    echo ""
    echo "Git SHA: ${GIT_SHA}"
    echo ""
    echo "Pushed images:"
    for image in "${IMAGES[@]}"; do
        echo "  - ${REGISTRY_URL}/${image}:latest"
        echo "  - ${REGISTRY_URL}/${image}:${GIT_SHA}"
    done
    echo ""
    echo "To pull an image:"
    echo "  docker pull ${REGISTRY_URL}/platform-main:latest"
    echo ""
    echo "To rollback to this version:"
    echo "  export GIT_SHA=${GIT_SHA}"
    echo "  ./rollback.sh"
    echo ""
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
    echo ""
    echo -e "${BLUE}=============================================================================${NC}"
    echo -e "${BLUE}DigitalOcean Docker Build and Push${NC}"
    echo -e "${BLUE}=============================================================================${NC}"
    echo ""

    check_prerequisites
    verify_registry
    build_images
    push_images
    print_summary
}

main "$@"
