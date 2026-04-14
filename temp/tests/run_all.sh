#!/bin/bash
# NORTHSTORM Range — Full Test Suite
# Runs every asset test and every cross-asset chain test.
# Exit code 0 = all pass. Any failure = nonzero exit.
#
# Usage: ./run_all.sh [test_name]
#   No args: run everything
#   With arg: run only that test (e.g., ./run_all.sh test_a10)

set -o pipefail

PASS=0
FAIL=0
SKIP=0
ERRORS=""

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

run_test() {
    local name=$1
    local script=$2

    if [ -n "$FILTER" ] && [ "$FILTER" != "$name" ]; then
        return
    fi

    if [ ! -f "$script" ]; then
        echo -e "  ${YELLOW}SKIP${NC} $name (not yet written)"
        SKIP=$((SKIP + 1))
        return
    fi

    echo -n "  RUN  $name ... "
    output=$(bash "$script" 2>&1)
    rc=$?

    if [ $rc -eq 0 ]; then
        echo -e "${GREEN}PASS${NC}"
        PASS=$((PASS + 1))
    elif [ $rc -eq 77 ]; then
        echo -e "${YELLOW}SKIP${NC} (service not running)"
        SKIP=$((SKIP + 1))
    else
        echo -e "${RED}FAIL${NC}"
        FAIL=$((FAIL + 1))
        ERRORS="${ERRORS}\n--- ${name} ---\n${output}\n"
    fi
}

FILTER="${1:-}"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo "NORTHSTORM Range — Full Test Suite"
echo "========================================"
echo ""

# --- Individual asset tests ---
echo "=== Configuration Tests ==="
run_test "test_ctfd_config"  "$DIR/test_ctfd_config.sh"

echo ""
echo "=== Asset Tests ==="
run_test "test_a2_dc"       "$DIR/test_a2.sh"
run_test "test_a7_gitea"    "$DIR/test_a7.sh"
run_test "test_a6_content"  "$DIR/test_a6.sh"
run_test "test_a8_db"       "$DIR/test_a8.sh"
run_test "test_a9_content"  "$DIR/test_a9.sh"
run_test "test_a10_tail"    "$DIR/test_a10.sh"
run_test "test_a11_leg"     "$DIR/test_a11.sh"
run_test "test_a12_arms"    "$DIR/test_a12.sh"
run_test "test_a13_brain"   "$DIR/test_a13.sh"
run_test "test_a0_website"  "$DIR/test_a0.sh"
run_test "test_a1_mail"     "$DIR/test_a1.sh"
run_test "test_a3_webapp"   "$DIR/test_a3.sh"
run_test "test_a4_fileshare" "$DIR/test_a4.sh"
run_test "test_a5_scada"    "$DIR/test_a5.sh"
run_test "test_a14_kali"    "$DIR/test_a14.sh"

echo ""

# --- Cross-asset chain tests ---
echo "=== Cross-Asset Chain Tests ==="
run_test "chain_flag17_kerberoast_dcsync"  "$DIR/chain_flag17.sh"
run_test "chain_flag30_gpg_a6_a8_a7"       "$DIR/chain_flag30.sh"
run_test "chain_flag35_36_brain_full"       "$DIR/chain_flag35_36.sh"
run_test "chain_flag32_a7_to_a10"           "$DIR/chain_flag32.sh"
run_test "chain_flag33_a7_to_a11"           "$DIR/chain_flag33.sh"
run_test "chain_flag34_a4_to_a12"           "$DIR/chain_flag34.sh"
run_test "chain_flag15_a1_to_a4"            "$DIR/chain_flag15.sh"

echo ""
echo "========================================"
echo "Results: ${PASS} passed, ${FAIL} failed, ${SKIP} skipped"
echo "========================================"

if [ $FAIL -gt 0 ]; then
    echo ""
    echo -e "${RED}FAILURES:${NC}"
    echo -e "$ERRORS"
    exit 1
fi

exit 0
