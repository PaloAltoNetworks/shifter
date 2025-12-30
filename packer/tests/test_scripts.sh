#!/bin/bash
# Test suite for Packer shell scripts
# Run with: ./packer/tests/test_scripts.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKER_DIR="$(dirname "$SCRIPT_DIR")"
FAILED=0
PASSED=0

# Enable globstar for ** patterns
shopt -s globstar nullglob

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAILED++))
}

log_skip() {
    echo -e "${YELLOW}⊘${NC} $1 (skipped)"
}

echo "=== Packer Script Tests ==="
echo ""

# ------------------------------------------------------------------------------
# Test 1: All scripts have shebang
# ------------------------------------------------------------------------------
echo "--- Shebang Check ---"
for script in "$PACKER_DIR"/scripts/**/*.sh; do
    if head -1 "$script" | grep -q "^#!/bin/bash"; then
        log_pass "$(basename "$script") has bash shebang"
    else
        log_fail "$(basename "$script") missing bash shebang"
    fi
done
echo ""

# ------------------------------------------------------------------------------
# Test 2: All scripts use set -euo pipefail
# ------------------------------------------------------------------------------
echo "--- Strict Mode Check ---"
for script in "$PACKER_DIR"/scripts/**/*.sh; do
    if grep -q "set -euo pipefail" "$script"; then
        log_pass "$(basename "$script") uses strict mode"
    else
        log_fail "$(basename "$script") missing 'set -euo pipefail'"
    fi
done
echo ""

# ------------------------------------------------------------------------------
# Test 3: ShellCheck (if available)
# ------------------------------------------------------------------------------
echo "--- ShellCheck ---"
if command -v shellcheck &> /dev/null; then
    for script in "$PACKER_DIR"/scripts/**/*.sh; do
        if shellcheck -S warning "$script" 2>/dev/null; then
            log_pass "$(basename "$script") passes shellcheck"
        else
            log_fail "$(basename "$script") has shellcheck warnings"
        fi
    done
else
    log_skip "shellcheck not installed"
fi
echo ""

# ------------------------------------------------------------------------------
# Test 4: No hardcoded secrets
# ------------------------------------------------------------------------------
echo "--- Secret Detection ---"
for script in "$PACKER_DIR"/scripts/**/*.sh; do
    # Check for common secret patterns
    if grep -qiE "(password|secret|api_key|token)\s*=" "$script" 2>/dev/null; then
        log_fail "$(basename "$script") may contain hardcoded secrets"
    else
        log_pass "$(basename "$script") no hardcoded secrets detected"
    fi
done
echo ""

# ------------------------------------------------------------------------------
# Test 5: Packer template validation
# ------------------------------------------------------------------------------
echo "--- Packer Validation ---"
if command -v packer &> /dev/null; then
    cd "$PACKER_DIR"

    # Initialize if needed
    if [ ! -d ".packer.d" ] && [ ! -d "$HOME/.packer.d" ]; then
        packer init . 2>/dev/null || true
    fi

    for template in "$PACKER_DIR"/*.pkr.hcl; do
        [ -f "$template" ] || continue
        template_name=$(basename "$template")

        # Skip variables file
        if [[ "$template_name" == "variables.pkr.hcl" ]]; then
            continue
        fi

        if packer validate "$template" 2>/dev/null; then
            log_pass "$template_name is valid"
        else
            log_fail "$template_name validation failed"
        fi
    done
else
    log_skip "packer not installed"
fi
echo ""

# ------------------------------------------------------------------------------
# Test 6: Script execution permissions
# ------------------------------------------------------------------------------
echo "--- Execution Permissions ---"
for script in "$PACKER_DIR"/scripts/**/*.sh; do
    # Scripts don't need +x since packer runs them with bash explicitly
    # But they should be readable
    if [ -r "$script" ]; then
        log_pass "$(basename "$script") is readable"
    else
        log_fail "$(basename "$script") is not readable"
    fi
done
echo ""

# ------------------------------------------------------------------------------
# Test 7: No TODO/FIXME in production scripts
# ------------------------------------------------------------------------------
echo "--- TODO/FIXME Check ---"
for script in "$PACKER_DIR"/scripts/**/*.sh; do
    if grep -qiE "(TODO|FIXME|XXX|HACK)" "$script" 2>/dev/null; then
        log_fail "$(basename "$script") contains TODO/FIXME markers"
    else
        log_pass "$(basename "$script") no TODO/FIXME markers"
    fi
done
echo ""

# ------------------------------------------------------------------------------
# Test 8: Check for DEBIAN_FRONTEND in apt scripts
# ------------------------------------------------------------------------------
echo "--- Non-interactive apt Check ---"
for script in "$PACKER_DIR"/scripts/**/*.sh; do
    if grep -q "apt-get install" "$script"; then
        if grep -q "DEBIAN_FRONTEND=noninteractive" "$script" || \
           grep -q "apt-get install -y" "$script"; then
            log_pass "$(basename "$script") uses non-interactive apt"
        else
            log_fail "$(basename "$script") may hang on apt prompts"
        fi
    fi
done
echo ""

# ------------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------------
echo "=== Summary ==="
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo ""

if [ "$FAILED" -gt 0 ]; then
    echo -e "${RED}Tests failed!${NC}"
    exit 1
else
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
fi
