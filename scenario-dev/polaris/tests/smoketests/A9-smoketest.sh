#!/usr/bin/env sh
# A9 Splice Landing Box smoketest.
#
# Runs from inside the a9-splice container (only entry point to the
# Bunker OT network). Verifies the JTF Polaris field relay artifacts, the
# Modbus helper script, and queries A10/A11/A12 device identification
# to build the flag 31 concatenation answer.
#
# Usage (from the range host):
#     docker cp smoketest.sh a9-splice:/tmp/a9-smoke.sh
#     docker exec a9-splice sh /tmp/a9-smoke.sh
#
# Exits 0 on full pass, 1 on any failure.

set -u

EXPECTED_A10_MODEL="AHS-TAIL-7741"
EXPECTED_A11_MODEL="AHS-LEG-MN07"
EXPECTED_A12_MODEL="AHS-ARM-AL42"
EXPECTED_ANSWER="${EXPECTED_A10_MODEL}${EXPECTED_A11_MODEL}${EXPECTED_A12_MODEL}"
EXPECTED_FLAG_31="FLAG{2e8c0a5d7f3b1946}"

FAIL=0
pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

echo "A9 smoketest - running inside a9-splice (Bunker OT entry point)"

echo
echo "--- JTF Polaris field relay artifacts ---"
[ -f /root/README.txt ] && pass "/root/README.txt present" || fail "/root/README.txt missing"
grep -q 'POLARIS FIELD RELAY' /root/README.txt 2>/dev/null \
    && pass "README mentions POLARIS FIELD RELAY" || fail "README text wrong"
grep -q 'SPLICE ACTIVE' /root/README.txt 2>/dev/null \
    && pass "README mentions SPLICE ACTIVE" || fail "README text wrong"
[ -f /root/scan_results.txt ] && pass "/root/scan_results.txt present" || fail "scan_results missing"
grep -q 'modbus' /root/scan_results.txt 2>/dev/null \
    && pass "scan_results lists modbus port" || fail "scan_results missing modbus ref"
[ -x /usr/local/bin/modbus_client.py ] && pass "modbus_client.py executable" || fail "modbus_client.py missing/not exec"

echo
echo "--- Toolset expected on a field relay ---"
for tool in python3 nmap ncat tcpdump ssh; do
    command -v "$tool" >/dev/null 2>&1 && pass "$tool present" || fail "$tool missing"
done
python3 -c "import pymodbus" 2>/dev/null && pass "pymodbus importable" || fail "pymodbus not installed"

echo
echo "--- Bunker OT reachability (A10-A13) ---"
for host_port in "tail-ctrl:502:A10" "leg-ctrl:502:A11" "arms-ctrl:502:A12" "brain-main:9100:A13"; do
    host="${host_port%%:*}"
    rest="${host_port#*:}"
    port="${rest%%:*}"
    label="${rest#*:}"
    if python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(('${host}', ${port}))
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        pass "$label ($host:$port) reachable"
    else
        fail "$label ($host:$port) not reachable"
    fi
done

echo
echo "--- Flag 31: Modbus FC 43 device ID probe ---"
TMPOUT=$(mktemp)
a10_model=""
a11_model=""
a12_model=""
for host_var in "tail-ctrl:A10_MODEL:$EXPECTED_A10_MODEL" \
                "leg-ctrl:A11_MODEL:$EXPECTED_A11_MODEL" \
                "arms-ctrl:A12_MODEL:$EXPECTED_A12_MODEL"; do
    host="${host_var%%:*}"
    rest="${host_var#*:}"
    label="${rest%%:*}"
    expected="${rest#*:}"
    python3 /usr/local/bin/modbus_client.py "$host" devid > "$TMPOUT" 2>&1
    model="$(grep -m1 'ProductName:' "$TMPOUT" | awk '{print $2}')"
    if [ "$model" = "$expected" ]; then
        pass "$host ProductName = $model"
        case "$label" in
            A10_MODEL) a10_model="$model" ;;
            A11_MODEL) a11_model="$model" ;;
            A12_MODEL) a12_model="$model" ;;
        esac
    else
        fail "$host ProductName expected=$expected got='$model'"
    fi
done
rm -f "$TMPOUT"

echo
echo "--- Flag 31 concatenation answer ---"
answer="${a10_model}${a11_model}${a12_model}"
if [ "$answer" = "$EXPECTED_ANSWER" ]; then
    pass "concatenation = $answer"
    echo "  (CTFd challenge accepts this string; issues static flag $EXPECTED_FLAG_31)"
else
    fail "concatenation expected=$EXPECTED_ANSWER got=$answer"
fi

echo
if [ "$FAIL" = "0" ]; then
    echo "A9 smoketest: PASS"
    exit 0
else
    echo "A9 smoketest: FAIL ($FAIL failure(s))"
    exit 1
fi
