#!/usr/bin/env bash
# A6 Engineering Workstation smoketest.
#
# Runs every flag path from an attacker's perspective via SSH pivot
# through a3-intranet (A6 is on lab VLAN 30, not reachable from a14-kali
# directly per design - compromise A3 first, then ssh to A6).
#
# Usage (from the range host):
#     docker cp smoketest.sh a3-intranet:/tmp/a6-smoke.sh
#     docker exec a3-intranet bash /tmp/a6-smoke.sh
#
# Requires: openssh-client + sshpass in a3-intranet (bundled in a3
# Dockerfile as pivot-host tooling), python3 with stdlib zipfile.
#
# Exits 0 on full pass, 1 on any failure.

set -u

HOST="${A6_HOST:-eng-ws01.boreas.local}"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

EXPECTED_FLAG_20="FLAG{5b8e1d3a7c0f9246}"
EXPECTED_FLAG_22="FLAG{e2a9c4f7d8b01536}"
EXPECTED_FLAG_23="FLAG{0c7d8a2e5f1b3946}"
EXPECTED_FLAG_25="FLAG{3f6a9d1e7c4b0258}"
EXPECTED_FLAG_26="FLAG{7e2b0c5d9a4f8163}"
EXPECTED_FLAG_30="FLAG{d4c8f0a2e6b71935}"

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

run_as() {
    local user="$1" pw="$2"
    shift 2
    sshpass -p "$pw" ssh $SSH_OPTS "$user@$HOST" "$@"
}

scp_from() {
    local user="$1" pw="$2" src="$3" dst="$4"
    sshpass -p "$pw" scp $SSH_OPTS "$user@$HOST:$src" "$dst"
}

echo "A6 smoketest - target=$HOST via a3 pivot"

echo
echo "--- SSH reachability from a3 (pivot) ---"
if run_as jenkins build2025 "echo ok" 2>/dev/null | grep -q ok; then
    pass "jenkins ssh login works"
else
    fail "jenkins ssh login broke"
fi
if run_as r.tanaka 'SimEngine#42' "echo ok" 2>/dev/null | grep -q ok; then
    pass "r.tanaka ssh login works"
else
    fail "r.tanaka ssh login broke"
fi
if run_as p.nielsen Hydraulics1 "echo ok" 2>/dev/null | grep -q ok; then
    pass "p.nielsen ssh login works"
else
    fail "p.nielsen ssh login broke"
fi

echo
echo "--- Flag 20: jenkins deploy token ---"
flag20="$(run_as jenkins build2025 "grep -oE 'FLAG\{[a-f0-9]+\}' ~/.credentials" 2>/dev/null | head -1)"
check_flag "flag 20" "$EXPECTED_FLAG_20" "$flag20"

echo
echo "--- Flag 22: /opt/builds/latest reactor interface spec ---"
flag22="$(run_as jenkins build2025 "grep -roE 'FLAG\{[a-f0-9]+\}' /opt/builds/latest/ 2>/dev/null" | grep -oE 'FLAG\{[a-f0-9]+\}' | head -1)"
check_flag "flag 22" "$EXPECTED_FLAG_22" "$flag22"
tracking_line="$(run_as jenkins build2025 "grep -i -E 'reactor|Novikov|compact power' /opt/builds/latest/reactor_interface_spec.* 2>/dev/null" | head -3)"
[[ -n "$tracking_line" ]] && pass "reactor spec mentions Novikov / compact power" || fail "reactor spec missing narrative text"

echo
echo "--- Flag 23: stress_test archive in /home/r.tanaka/simulations/standard/ ---"
archive_count="$(run_as r.tanaka 'SimEngine#42' "ls ~/simulations/standard/*.tar.gz 2>/dev/null | wc -l")"
check "47 simulation archives present (got $archive_count)" "$archive_count" == "47" 2>/dev/null || {
    if [[ "$archive_count" == "47" ]]; then pass "47 simulation archives present"; else fail "expected 47 archives, got $archive_count"; fi
}
flag23="$(run_as r.tanaka 'SimEngine#42' "mkdir -p /tmp/s44 && tar xzf ~/simulations/standard/stress_test_44.tar.gz -C /tmp/s44 2>/dev/null && strings /tmp/s44/stress_test_44.dat 2>/dev/null | grep -oE 'FLAG\{[a-f0-9]+\}' | head -1")"
check_flag "flag 23" "$EXPECTED_FLAG_23" "$flag23"
bipedal_refs="$(run_as r.tanaka 'SimEngine#42' "for i in 28 31 44; do tar xzf ~/simulations/standard/stress_test_\${i}.tar.gz -O stress_test_\${i}.log 2>/dev/null | grep -i bipedal; done" | wc -l)"
(( bipedal_refs >= 3 )) && pass "bipedal references in stress_test 28/31/44 logs (got $bipedal_refs)" || fail "bipedal cross-references missing (got $bipedal_refs)"

echo
echo "--- Flag 25: MIDNIGHT-7 results (restricted to r.tanaka) ---"
anon_read="$(run_as jenkins build2025 "cat /home/r.tanaka/simulations/midnight/MIDNIGHT-7_results.dat 2>&1")"
grep -q 'Permission denied' <<<"$anon_read" && pass "midnight/ correctly denies non-tanaka users" || fail "midnight/ readable by jenkins (perms wrong)"
flag25="$(run_as r.tanaka 'SimEngine#42' "grep -oE 'FLAG\{[a-f0-9]+\}' ~/simulations/midnight/MIDNIGHT-7_results.dat 2>/dev/null")"
check_flag "flag 25" "$EXPECTED_FLAG_25" "$flag25"
mn07_id="$(run_as r.tanaka 'SimEngine#42' "grep -oE 'MN07-[A-Z0-9-]+' ~/simulations/midnight/MIDNIGHT-7_results.dat 2>/dev/null | head -1")"
[[ -n "$mn07_id" ]] && pass "MIDNIGHT-7 simulation ID $mn07_id (A13 override code piece)" || fail "MN07 simulation ID missing"

echo
echo "--- Flag 26: p.nielsen center_of_gravity_analysis.xlsx hidden Integration sheet ---"
scp_from p.nielsen Hydraulics1 "/home/p.nielsen/designs/center_of_gravity_analysis.xlsx" "$WORKDIR/cog.xlsx" 2>/dev/null
if [[ -s "$WORKDIR/cog.xlsx" ]]; then
    pass "xlsx retrieved via p.nielsen ssh+scp"
    flag26_result="$(python3 - "$WORKDIR/cog.xlsx" <<'PYEOF'
import sys, re, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    hidden_in_workbook = "Integration" in z.read("xl/workbook.xml").decode() and "hidden" in z.read("xl/workbook.xml").decode()
    print("HIDDEN_OK" if hidden_in_workbook else "HIDDEN_MISS")
    for name in z.namelist():
        if "sheet3" in name:
            content = z.read(name).decode(errors="ignore")
            flags = re.findall(r"FLAG\{[a-f0-9]+\}", content)
            if flags:
                print("FLAG=" + flags[0])
PYEOF
)"
    grep -q HIDDEN_OK <<<"$flag26_result" && pass "Integration sheet marked hidden in workbook.xml" || fail "Integration sheet not hidden"
    flag26="$(grep -oE 'FLAG\{[a-f0-9]+\}' <<<"$flag26_result" | head -1)"
    check_flag "flag 26" "$EXPECTED_FLAG_26" "$flag26"
else
    fail "xlsx download failed"
fi

echo
echo "--- p.nielsen designs/ permission check ---"
nielsen_anon="$(run_as jenkins build2025 "ls /home/p.nielsen/designs/ 2>&1")"
grep -q 'Permission denied' <<<"$nielsen_anon" && pass "nielsen designs/ correctly denies non-nielsen" || fail "nielsen designs/ readable by jenkins"

echo
echo "--- A8 cross-asset breadcrumb: p.nielsen .pgpass ---"
pgpass_line="$(run_as jenkins build2025 "cat /home/p.nielsen/.pgpass 2>/dev/null")"
grep -q 'researchdb.boreas.local' <<<"$pgpass_line" && pass ".pgpass references researchdb.boreas.local" || fail ".pgpass missing researchdb"
grep -q 'lab_mfg' <<<"$pgpass_line" && pass ".pgpass contains lab_mfg user (A8 pivot cred)" || fail ".pgpass missing lab_mfg"

echo
echo "--- Flag 30 prerequisites (full chain requires A7 passphrase + A8 private key) ---"
enc_file="$(run_as jenkins build2025 "ls /tmp/.deleted/full_integration_sim.mp4.gpg 2>/dev/null")"
[[ -n "$enc_file" ]] && pass "/tmp/.deleted/full_integration_sim.mp4.gpg present" || fail "encrypted file missing"
pub_key="$(run_as jenkins build2025 "ls /home/e.vasik/.gnupg/vasik_public.asc 2>/dev/null")"
[[ -n "$pub_key" ]] && pass "Vasik public key present in /home/e.vasik/.gnupg/" || fail "public key missing"
gpg_hint="$(run_as jenkins build2025 "grep -l researchdb /home/e.vasik/.gnupg/gpg-agent.conf 2>/dev/null")"
[[ -n "$gpg_hint" ]] && pass "gpg-agent.conf hints at researchdb (A8) for private key" || fail "gpg-agent.conf missing A8 hint"

echo
echo "--- Simulation logs narrative ---"
log_check="$(run_as jenkins build2025 "grep -c 'MIDNIGHT-7' /var/log/sim/simulation.log 2>/dev/null")"
(( log_check > 0 )) && pass "/var/log/sim/simulation.log has MIDNIGHT-7 entries" || fail "simulation log missing"
after_hours="$(run_as jenkins build2025 "grep -c '02:0\|02:4\|03:0\|04:0\|06:2' /var/log/sim/simulation.log 2>/dev/null")"
(( after_hours > 0 )) && pass "simulation log shows after-hours test runs" || fail "after-hours entries missing"

echo
if (( FAIL == 0 )); then
    echo "A6 smoketest: PASS"
    exit 0
else
    echo "A6 smoketest: FAIL ($FAIL failure(s))"
    exit 1
fi
