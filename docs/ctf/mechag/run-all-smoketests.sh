#!/usr/bin/env bash
# NORTHSTORM range full test sweep.
#
# Resets sticky-state services, then runs every per-asset smoketest from
# the correct runner container (a14-kali / a3-intranet / a9-splice), plus
# the cross-cutting isolation smoketest from the host. Aggregates PASS/FAIL
# and exits non-zero on any failure.
#
# Usage:
#     bash /home/atomik/range/run-all-smoketests.sh
#     RANGE_DIR=/other bash run-all-smoketests.sh
#
# Exits 0 only if every asset sweep AND the isolation sweep pass.

set -u
RANGE_DIR="${RANGE_DIR:-/home/atomik/range}"
cd "$RANGE_DIR"

# asset|runner|smoketest path (relative to RANGE_DIR)|interpreter
# Order matters: run shared/corporate assets (a14-kali path) first, then
# pivot through a3-intranet for scada/lab assets, then a9-splice for
# bunker-ot assets, then a14 self-test, then isolation.
TESTS=(
    "a0|a14-kali|A0-boreas-website/smoketest.sh|bash"
    "a1|a14-kali|A1-mail-server/smoketest.py|python3"
    "a2|a14-kali|A2-domain-controller/smoketest.sh|bash"
    "a3|a14-kali|A3-web-app/smoketest.sh|bash"
    "a4|a14-kali|A4-file-share/smoketest.sh|bash"
    "a7|a14-kali|A7-source-repo/smoketest.sh|bash"
    "a5|a3-intranet|A5-scada-generator/smoketest.py|python3"
    "a6|a3-intranet|A6-engineering-workstation/smoketest.sh|bash"
    "a8|a3-intranet|A8-research-database/smoketest.sh|bash"
    "a9|a9-splice|A9-splice-landing/smoketest.sh|sh"
    "a10|a9-splice|A10-tail-controller/smoketest.py|python3"
    "a11|a9-splice|A11-leg-controller/smoketest.py|python3"
    "a12|a9-splice|A12-arms-controller/smoketest.py|python3"
    "a13|a9-splice|A13-brain/smoketest.py|python3"
    "a14|a14-kali|A14-kali/smoketest.sh|bash"
)

RESULTS=()
FAIL=0
TOTAL=0

log() { echo "[run-all] $*"; }
hdr() { echo; echo "========================================"; echo "  $*"; echo "========================================"; }

hdr "PRE-FLIGHT: reset sticky state"
if ! bash "$RANGE_DIR/reset.sh"; then
    log "[FATAL] reset.sh failed"
    exit 1
fi

for test in "${TESTS[@]}"; do
    IFS='|' read -r name runner path interp <<<"$test"
    TOTAL=$((TOTAL + 1))
    hdr "$name via $runner ($path)"
    src="$RANGE_DIR/$path"
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
if bash "$RANGE_DIR/isolation-smoketest.sh"; then
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
