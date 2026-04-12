#!/usr/bin/env bash
# A4 File Share smoketest.
#
# Runs every flag path from an attacker's perspective against the live
# Samba file server (fileserv.boreas.local). Intended to be executed
# from inside the a14-kali container.
#
# Usage (from the range host):
#     docker cp smoketest.sh a14-kali:/tmp/a4-smoke.sh
#     docker exec a14-kali bash /tmp/a4-smoke.sh
#
# Exits 0 on full pass, 1 on any failure.

set -u

HOST="${A4_HOST:-fileserv.boreas.local}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

EXEC_USER="v.harlan"
EXEC_PASS='Boreas2025!'
SVC_USER="svc-fileshare"
SVC_PASS='F1l3Sh@r3Svc!'

EXPECTED_FLAG_9="FLAG{7a1b3d9e2c8f0546}"
EXPECTED_FLAG_11="FLAG{0e6f9c2d4a8b7135}"
EXPECTED_FLAG_13="FLAG{8c5a0d3f7e1b2964}"
EXPECTED_FLAG_15="FLAG{9a4c7e2f58d0b163}"

FAIL=0
pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAIL=1; }
check_flag() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$actual" == *"$expected"* ]]; then
        pass "$label = $expected"
    else
        fail "$label expected=$expected got='$actual'"
    fi
}

echo "A4 smoketest - target=$HOST"

echo
echo "--- Port reachability ---"
for p in 139 445; do
    if timeout 2 bash -c "exec 3<>/dev/tcp/$HOST/$p" 2>/dev/null; then
        pass "tcp/$p open"
    else
        fail "tcp/$p unreachable"
    fi
done

echo
echo "--- Share listing as $SVC_USER ---"
SHARES="$(smbclient -L "//$HOST" -U "$SVC_USER%$SVC_PASS" 2>&1)"
for s in Public HR Procurement IT Executive; do
    grep -qE "^\s*$s\s+Disk" <<<"$SHARES" && pass "share $s listed" || fail "share $s missing from listing"
done

echo
echo "--- Flag 11: Public share anonymous + cafeteria menu Author metadata ---"
mkdir -p pub && cd pub
smbclient "//$HOST/Public" -N -c "prompt OFF; mget *" >/dev/null 2>&1
if [[ -f cafeteria_menu_april.pdf ]]; then
    pass "anonymous read of Public share"
    flag11="$(exiftool cafeteria_menu_april.pdf 2>/dev/null | awk -F': +' '/^Author/ {print $2}')"
    check_flag "flag 11" "$EXPECTED_FLAG_11" "$flag11"
else
    fail "cafeteria_menu_april.pdf not downloadable anonymously"
fi
[[ -f parking_policy_2025.pdf ]] && pass "parking_policy_2025.pdf present" || fail "parking_policy missing"
[[ -f office_floorplan.pdf ]] && pass "office_floorplan.pdf present" || fail "floorplan missing"
cd ..

echo
echo "--- Flag 9: HR share as $EXEC_USER, chen termination page 2 ---"
mkdir -p hr && cd hr
smbclient "//$HOST/HR" -U "$EXEC_USER%$EXEC_PASS" \
    -c "prompt OFF; recurse ON; mget *" >/dev/null 2>&1
if [[ -f personnel/chen_james_termination.pdf ]]; then
    pass "HR/personnel/chen_james_termination.pdf retrieved"
    flag9="$(/opt/tools/bin/pdf2txt.py personnel/chen_james_termination.pdf 2>/dev/null \
        | grep -oE 'FLAG\{[a-f0-9]+\}' | head -1)"
    check_flag "flag 9" "$EXPECTED_FLAG_9" "$flag9"
    /opt/tools/bin/pdf2txt.py personnel/chen_james_termination.pdf 2>/dev/null \
        | grep -q 'Case Reference Number' \
        && pass "Chen termination PDF has 'Case Reference Number' field" \
        || fail "Chen termination missing Case Reference Number"
else
    fail "chen termination PDF not retrievable"
fi
[[ -f personnel/chen_james_nda.pdf ]] && pass "chen NDA present" || fail "chen NDA missing"
[[ -f org_chart_current.xlsx ]] && pass "org_chart_current.xlsx present" || fail "org chart missing"
cd ..

echo
echo "--- HR share denies anonymous ---"
anon_hr="$(smbclient "//$HOST/HR" -N -c "ls" 2>&1)"
grep -q 'NT_STATUS_ACCESS_DENIED\|NT_STATUS_LOGON_FAILURE' <<<"$anon_hr" \
    && pass "HR share denies anonymous" || fail "HR share allows anonymous"

echo
echo "--- Flag 13: Procurement share, PO-2847 -> specs/actuator_requirements_v4 ---"
mkdir -p proc && cd proc
smbclient "//$HOST/Procurement" -U "$EXEC_USER%$EXEC_PASS" \
    -c "prompt OFF; recurse ON; mget *" >/dev/null 2>&1
if [[ -f PO-2847_hydraulic_actuators.pdf ]]; then
    pass "PO-2847_hydraulic_actuators.pdf retrieved"
    po_text="$(/opt/tools/bin/pdf2txt.py PO-2847_hydraulic_actuators.pdf 2>/dev/null)"
    grep -q 'specs/actuator_requirements' <<<"$po_text" \
        && pass "PO-2847 references specs/actuator_requirements" \
        || fail "PO-2847 missing specs reference"
    grep -q 'Kursk Heavy Industries' <<<"$po_text" \
        && pass "PO-2847 supplier = Kursk Heavy Industries" \
        || fail "PO-2847 missing Kursk supplier"
    grep -q '200' <<<"$po_text" \
        && pass "PO-2847 mentions 200-ton force" \
        || fail "PO-2847 missing force rating"
fi
if [[ -f specs/actuator_requirements_v4.pdf ]]; then
    pass "specs/actuator_requirements_v4.pdf retrieved"
    flag13="$(/opt/tools/bin/pdf2txt.py specs/actuator_requirements_v4.pdf 2>/dev/null \
        | grep -oE 'FLAG\{[a-f0-9]+\}' | head -1)"
    check_flag "flag 13" "$EXPECTED_FLAG_13" "$flag13"
else
    fail "specs/actuator_requirements_v4.pdf not retrievable"
fi
for f in PO-3102_servo_motors.pdf PO-3455_exotic_alloys.pdf invoice_reactor_deposit.pdf; do
    [[ -f "$f" ]] && pass "$f present" || fail "$f missing"
done
cd ..

echo
echo "--- Flag 15: IT share, backup_verification.log, svc-fileshare only ---"
mkdir -p it && cd it
it_anon="$(smbclient "//$HOST/IT" -N -c "ls" 2>&1)"
grep -q 'NT_STATUS_ACCESS_DENIED\|NT_STATUS_LOGON_FAILURE' <<<"$it_anon" \
    && pass "IT share denies anonymous" || fail "IT share allows anonymous"
smbclient "//$HOST/IT" -U "$SVC_USER%$SVC_PASS" \
    -c "prompt OFF; recurse ON; mget *" >/dev/null 2>&1
if [[ -f backup_verification.log ]]; then
    pass "backup_verification.log retrieved via $SVC_USER"
    flag15="$(grep -oE 'FLAG\{[a-f0-9]+\}' backup_verification.log | head -1)"
    check_flag "flag 15" "$EXPECTED_FLAG_15" "$flag15"
else
    fail "backup_verification.log not retrievable"
fi
[[ -f network_diagram.pdf ]] && pass "network_diagram.pdf present" || fail "network_diagram missing"
[[ -f server_inventory.xlsx ]] && pass "server_inventory.xlsx present" || fail "server_inventory missing"
cd ..

echo
echo "--- Executive share as $EXEC_USER ---"
mkdir -p exec && cd exec
smbclient "//$HOST/Executive" -U "$EXEC_USER%$EXEC_PASS" \
    -c "prompt OFF; mget *" >/dev/null 2>&1
[[ -f board_minutes_Q3_2025.pdf ]] && pass "board_minutes_Q3_2025.pdf present" || fail "board minutes missing"
[[ -f budget_summary_2025.pdf ]] && pass "budget_summary_2025.pdf present" || fail "budget missing"
cd ..

echo
if (( FAIL == 0 )); then
    echo "A4 smoketest: PASS"
    exit 0
else
    echo "A4 smoketest: FAIL ($FAIL failure(s))"
    exit 1
fi
