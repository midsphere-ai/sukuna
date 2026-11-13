#!/usr/bin/env bash
# Encrypt agent_server/ and tools/ with PyArmor 9+.
#
# Usage:
#   ./encrypt.sh              # basic encryption (trial-compatible)
#   ./encrypt.sh --rft        # with RFT mode (requires Pro license)
#
# Output: dist/ directory with encrypted packages + runtime .so
#
# Notes:
#   - Both packages are encrypted in a single invocation so they share
#     the same runtime key and can import each other freely.
#   - The --prefix flag stores the shared runtime inside agent_server/.
#   - RFT mode renames all functions/variables/classes at source level
#     (irreversible without original source). Use for production.
#   - BCC/ECC modes do NOT support async code — do not enable them.

set -euo pipefail

cd "$(dirname "$0")"

EXTRA_FLAGS=""
if [[ "${1:-}" == "--rft" ]]; then
    EXTRA_FLAGS="--enable-rft"
    echo "RFT mode enabled (requires PyArmor Pro license)"
fi

echo "Encrypting agent_server/ and tools/ with PyArmor 9..."

pyarmor gen \
    -r \
    -i \
    --prefix agent_server \
    --mix-str \
    --assert-call \
    --assert-import \
    $EXTRA_FLAGS \
    -O dist \
    agent_server/ \
    tools/

echo ""
echo "Encrypted output: dist/"
echo "Files encrypted: $(find dist/ -name '*.py' | wc -l)"
echo "Runtime: dist/agent_server/pyarmor_runtime_*/pyarmor_runtime.so"
