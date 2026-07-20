#!/usr/bin/env bash
# NORTHSTORM range full test sweep.
#
# Resets sticky-state services, then runs every per-asset smoketest from
# the correct runner container (a14-kali / a3-intranet / a9-splice), plus
# the cross-cutting isolation smoketest from the host. Aggregates PASS/FAIL
# and exits non-zero on any failure.
#
# Usage:
#     bash tests/run-all-smoketests.sh
#     RANGE_DIR=/other bash run-all-smoketests.sh
#
# Exits 0 only if every asset sweep AND the isolation sweep pass.

set -u
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_RANGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RANGE_DIR="${RANGE_DIR:-$DEFAULT_RANGE_DIR}"
cd "$RANGE_DIR"

# asset|runner|smoketest path (relative to $SMOKETESTS_DIR)|interpreter
# Order matters: run shared/corporate assets (a14-kali path) first, then
# pivot through a3-intranet for scada/lab assets, then a9-splice for
# bunker-ot assets, then a14 self-test, then isolation.
SMOKETESTS_DIR="${SMOKETESTS_DIR:-$RANGE_DIR/tests/smoketests}"
# Runner assignments reflect the post-A15/A16 refactor: scada + lab asset
# smoketests now run through the NEW pivot hosts (A15 for scada, A16 for
# lab), not through A3.
TESTS=(
    "a0|a14-kali|A0-smoketest.sh|bash"
    "a1|a14-kali|A1-smoketest.py|python3"
    "a2|a14-kali|A2-smoketest.sh|bash"
    "a3|a14-kali|A3-smoketest.sh|bash"
    "a4|a14-kali|A4-smoketest.sh|bash"
    "a15|a14-kali|A15-smoketest.sh|bash"
    "a16|a14-kali|A16-smoketest.sh|bash"
    "a5|a15-ops-eng|A5-smoketest.py|python3"
    "a7|a16-research-analyst|A7-smoketest.sh|bash"
    "a6|a16-research-analyst|A6-smoketest.sh|bash"
    "a8|a16-research-analyst|A8-smoketest.sh|bash"
    "a9|a9-splice|A9-smoketest.sh|sh"
    "a10|a9-splice|A10-smoketest.py|python3"
    "a11|a9-splice|A11-smoketest.py|python3"
    "a12|a9-splice|A12-smoketest.py|python3"
    "a13|a9-splice|A13-smoketest.py|python3"
    "a14|a14-kali|A14-smoketest.sh|bash"
)

RESULTS=()
FAIL=0
TOTAL=0

log() { echo "[run-all] $*"; }
hdr() { echo; echo "========================================"; echo "  $*"; echo "========================================"; }

hdr "PRE-FLIGHT: reset sticky state"
RESET_SCRIPT="${RESET_SCRIPT:-$RANGE_DIR/tests/reset.sh}"
if [[ ! -f "$RESET_SCRIPT" ]]; then
    RESET_SCRIPT="$RANGE_DIR/reset.sh"  # legacy flat layout fallback
fi
if ! bash "$RESET_SCRIPT"; then
    log "[FATAL] reset.sh failed"
    exit 1
fi

for test in "${TESTS[@]}"; do
    IFS='|' read -r name runner path interp <<<"$test"
    TOTAL=$((TOTAL + 1))
    hdr "$name via $runner ($path)"
    src="$SMOKETESTS_DIR/$path"
    if [[ ! -f "$src" ]]; then
        log "[FAIL] $name: $src not found"
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL $name (script missing)")
        continue
    fi

    ext="${path##*.}"
    dst="/tmp/smoke-$name.$ext"
    if ! docker cp "$src" "$runner:$dst" >/dev/null 2>&1; then
        log "[FAIL] $name: docker cp into $runner failed"
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL $name (docker cp)")
        continue
    fi

    if docker exec "$runner" "$interp" "$dst"; then
        RESULTS+=("PASS $name")
    else
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL $name")
    fi
done

hdr "isolation (cross-cutting network boundary sweep)"
TOTAL=$((TOTAL + 1))
ISOLATION_SCRIPT="${ISOLATION_SCRIPT:-$RANGE_DIR/tests/isolation-smoketest.sh}"
if [[ ! -f "$ISOLATION_SCRIPT" ]]; then
    ISOLATION_SCRIPT="$RANGE_DIR/isolation-smoketest.sh"  # legacy flat layout fallback
fi
if bash "$ISOLATION_SCRIPT"; then
    RESULTS+=("PASS isolation")
else
    FAIL=$((FAIL + 1))
    RESULTS+=("FAIL isolation")
fi

hdr "SUMMARY"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo
passed=$((TOTAL - FAIL))
echo "  $passed / $TOTAL asset sweeps PASS"
echo
if (( FAIL == 0 )); then
    echo "NORTHSTORM full range: PASS"
    exit 0
else
    echo "NORTHSTORM full range: FAIL ($FAIL)"
    exit 1
fi
