#!/bin/bash
# =============================================================================
# Status Check Script
# =============================================================================
# This script checks the status of all deployed services.
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

# Service URLs (update if using different domain)
API_URL="${API_URL:-https://api.midsphere.ai}"
CHANNELS_URL="${CHANNELS_URL:-https://channels.midsphere.ai}"
FLOWER_URL="${FLOWER_URL:-https://flower.example.com}"

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

check_status() {
    local name=$1
    local url=$2
    local expected_code=${3:-200}
    
    local response_code
    response_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${url}" 2>/dev/null || echo "000")
    
    if [[ "$response_code" == "$expected_code" ]]; then
        log_success "${name}: ${url} (HTTP ${response_code})"
        return 0
    elif [[ "$response_code" == "000" ]]; then
        log_error "${name}: ${url} (Connection failed)"
        return 1
    else
        log_warning "${name}: ${url} (HTTP ${response_code}, expected ${expected_code})"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Check DigitalOcean Droplets
# -----------------------------------------------------------------------------

check_droplets() {
    echo ""
    echo -e "${BLUE}=== DigitalOcean Droplets ===${NC}"
    echo ""
    
    if command -v doctl &> /dev/null; then
        doctl compute droplet list \
            --format ID,Name,Status,PublicIPv4,PrivateIPv4,Memory,VCPUs,Region \
            --no-header 2>/dev/null | while read -r line; do
            if echo "$line" | grep -q "active"; then
                echo -e "${GREEN}●${NC} $line"
            else
                echo -e "${RED}●${NC} $line"
            fi
        done
    else
        log_warning "doctl not installed. Skipping droplet status."
    fi
}

# -----------------------------------------------------------------------------
# Check Load Balancers
# -----------------------------------------------------------------------------

check_load_balancers() {
    echo ""
    echo -e "${BLUE}=== Load Balancers ===${NC}"
    echo ""
    
    if command -v doctl &> /dev/null; then
        doctl compute load-balancer list \
            --format ID,Name,IP,Status,Region \
            --no-header 2>/dev/null | while read -r line; do
            if echo "$line" | grep -q "active"; then
                echo -e "${GREEN}●${NC} $line"
            else
                echo -e "${RED}●${NC} $line"
            fi
        done
    else
        log_warning "doctl not installed. Skipping load balancer status."
    fi
}

# -----------------------------------------------------------------------------
# Check Kubernetes Cluster
# -----------------------------------------------------------------------------

check_kubernetes() {
    echo ""
    echo -e "${BLUE}=== Kubernetes Cluster ===${NC}"
    echo ""
    
    export KUBECONFIG="${SCRIPT_DIR}/kubeconfig"
    
    if [[ ! -f "$KUBECONFIG" ]]; then
        log_warning "Kubeconfig not found. Skipping Kubernetes status."
        return
    fi
    
    # Check nodes
    echo "Nodes:"
    kubectl get nodes -o wide 2>/dev/null || log_error "Failed to get nodes"
    
    echo ""
    echo "ARQ Worker Pods:"
    kubectl get pods -n agent-platform -l app=arq-workers -o wide 2>/dev/null || log_error "Failed to get pods"
    
    echo ""
    echo "Pod Status Summary:"
    kubectl get pods -n agent-platform -l app=arq-workers -o jsonpath='{range .items[*]}{.status.phase}{"\n"}{end}' 2>/dev/null | sort | uniq -c || true
    
    echo ""
    echo "KEDA ScaledObject:"
    kubectl get scaledobject -n agent-platform 2>/dev/null || log_warning "KEDA ScaledObject not found"
}

# -----------------------------------------------------------------------------
# Check Health Endpoints
# -----------------------------------------------------------------------------

check_health_endpoints() {
    echo ""
    echo -e "${BLUE}=== Health Endpoints ===${NC}"
    echo ""
    
    check_status "API Health" "${API_URL}/health/" 200 || true
    check_status "Channels Health" "${CHANNELS_URL}/ws-health/" 200 || true
    check_status "Flower Dashboard" "${FLOWER_URL}/" 401 || true  # 401 expected due to basic auth
}

# -----------------------------------------------------------------------------
# Check Container Registry
# -----------------------------------------------------------------------------

check_registry() {
    echo ""
    echo -e "${BLUE}=== Container Registry ===${NC}"
    echo ""
    
    if command -v doctl &> /dev/null; then
        doctl registry get --format Name,Endpoint,Region 2>/dev/null || log_error "Failed to get registry info"
        echo ""
        echo "Recent images:"
        doctl registry repository list 2>/dev/null || log_warning "No repositories found"
    else
        log_warning "doctl not installed. Skipping registry status."
    fi
}

# -----------------------------------------------------------------------------
# Print Summary
# -----------------------------------------------------------------------------

print_summary() {
    echo ""
    echo -e "${BLUE}=== Summary ===${NC}"
    echo ""
    echo "Service URLs:"
    echo "  API:      ${API_URL}"
    echo "  Channels: ${CHANNELS_URL}"
    echo "  Flower:   ${FLOWER_URL}"
    echo ""
    echo "Kubeconfig: ${SCRIPT_DIR}/kubeconfig"
    echo ""
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
    echo ""
    echo -e "${BLUE}=============================================================================${NC}"
    echo -e "${BLUE}Midsphere Production Status${NC}"
    echo -e "${BLUE}=============================================================================${NC}"
    
    check_droplets
    check_load_balancers
    check_kubernetes
    check_health_endpoints
    check_registry
    print_summary
}

main "$@"
