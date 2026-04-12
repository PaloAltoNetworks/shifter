#!/usr/bin/env bash
# A0 Boreas Systems smoketest.
#
# Runs every flag path from an attacker's perspective. Intended to be executed
# from inside the a14-kali container (or any host on the shared network that can
# resolve boreas-systems.ctf via the DNS sidecar). Every assertion mirrors what
# a participant would do in a walkthrough.
#
# Usage (from the range host):
#     docker exec -it a14-kali /path/to/smoketest.sh
# Or copy into the container:
#     docker cp smoketest.sh a14-kali:/tmp/a0-smoke.sh
#     docker exec a14-kali bash /tmp/a0-smoke.sh
#
# Exit 0 on full pass, 1 on any failure.

set -u

HOST="${A0_HOST:-boreas-systems.ctf}"
DNS="${A0_DNS:-172.20.0.2}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

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

echo "A0 smoketest — target=$HOST dns=$DNS"

echo
echo "--- Flag 1: about.html HTML comment near registration number ---"
body="$(curl -s "http://$HOST/about.html")"
flag1="$(printf '%s' "$body" | grep -oE 'FLAG\{[a-f0-9]+\}' | head -1)"
check_flag "flag 1" "FLAG{8f3a2c1e9b7d4056}" "$flag1"
grep -q '7741-BSI-2018' <<<"$body" && pass "registration 7741-BSI-2018 present" || fail "registration number missing"

echo
echo "--- Flag 2: org_chart.pdf PDF metadata (Author field) ---"
curl -sf "http://$HOST/internal/org_chart.pdf" -o "$TMP/org.pdf" || fail "could not fetch org_chart.pdf"
flag2="$(exiftool "$TMP/org.pdf" 2>/dev/null | awk -F': +' '/^Author/ {print $2}')"
check_flag "flag 2" "FLAG{d4e7b1f283a6c950}" "$flag2"

echo
echo "--- Flag 3: careers.html hidden form field ---"
flag3="$(curl -s "http://$HOST/careers.html" | grep -oE 'tracking_id" value="FLAG\{[a-f0-9]+\}' | grep -oE 'FLAG\{[a-f0-9]+\}')"
check_flag "flag 3" "FLAG{a1c9e3f7054b82d6}" "$flag3"

echo
echo "--- Flag 4: old/clients.html HTML comment ---"
flag4="$(curl -s "http://$HOST/old/clients.html" | grep -oE 'FLAG\{[a-f0-9]+\}' | head -1)"
check_flag "flag 4" "FLAG{72b5e0d8f1a34c69}" "$flag4"

echo
echo "--- Flag 5: DNS AXFR _flag TXT record ---"
flag5="$(dig +short axfr boreas-systems.ctf @"$DNS" 2>/dev/null | grep -oE 'FLAG\{[a-f0-9]+\}' | head -1)"
check_flag "flag 5" "FLAG{5e9c2a0f73b148d6}" "$flag5"

echo
echo "--- Flag 6: annual report discovery + Kursk line ---"
listing="$(curl -s "http://$HOST/internal/")"
if grep -q 'annual' <<<"$listing"; then
    fail "annual report IS linked in /internal/ listing (should be hidden)"
else
    pass "annual report NOT linked in /internal/ listing"
fi
curl -sf "http://$HOST/internal/boreas-annual-2025.pdf" -o "$TMP/annual.pdf" || fail "direct fetch of annual report failed"
if [[ -s "$TMP/annual.pdf" ]]; then
    pass "annual report reachable via filename fuzzing"
else
    fail "annual.pdf empty or missing"
fi

kursk_line=""
if command -v pdftotext >/dev/null; then
    kursk_line="$(pdftotext "$TMP/annual.pdf" - 2>/dev/null | grep -i kursk | head -1)"
elif [[ -x /opt/tools/bin/pdf2txt.py ]]; then
    kursk_line="$(/opt/tools/bin/pdf2txt.py "$TMP/annual.pdf" 2>/dev/null | grep -i kursk | head -1)"
fi

if [[ "$kursk_line" == *Kursk* && "$kursk_line" == *12,000,000* ]]; then
    pass "Kursk Heavy Industries 12,000,000 line in annual report: $kursk_line"
else
    fail "Kursk/12,000,000 line not found in annual PDF text extraction"
fi

echo
echo "--- Design elements ---"
curl -s "http://$HOST/robots.txt" | grep -q '/internal/' && pass "robots.txt disallows /internal/" || fail "robots.txt /internal/ missing"
curl -s "http://$HOST/robots.txt" | grep -q '/admin/'    && pass "robots.txt disallows /admin/"    || fail "robots.txt /admin/ missing"
curl -s -o /dev/null -w '%{http_code}' "http://$HOST/admin/"  | grep -q '200\|403' && pass "/admin/ reachable" || fail "/admin/ unreachable"
curl -s -o /dev/null -w '%{http_code}' "http://$HOST/portal/" | grep -q '200'       && pass "/portal/ reachable" || fail "/portal/ unreachable"
curl -s "http://$HOST/leadership.html" | grep -q 'Viktor Harlan' && pass "leadership page lists Harlan" || fail "leadership missing"
curl -s "http://$HOST/leadership.html" | grep -q 'Elena Vasik'   && pass "leadership page lists Vasik"   || fail "leadership missing Vasik"
curl -s "http://$HOST/leadership.html" | grep -q 'Marcus Webb'   && pass "leadership page lists Webb"    || fail "leadership missing Webb"
curl -s "http://$HOST/careers.html" | grep -q 'Modbus/TCP'  && pass "careers lists Modbus/TCP"    || fail "careers missing Modbus/TCP"
curl -s "http://$HOST/careers.html" | grep -q 'Allen-Bradley' && pass "careers lists Allen-Bradley" || fail "careers missing Allen-Bradley"
curl -s "http://$HOST/news.html"    | grep -q 'Major Milestone' && pass "news has Major Milestone post" || fail "news missing milestone post"
curl -s "http://$HOST/old/"         | grep -q 'annual report'   && pass "/old/ has dev comment referencing annual report" || fail "/old/ dev comment missing"
dig +short mail.boreas-systems.ctf  @"$DNS" | grep -q '172.20' && pass "DNS mail subdomain resolves" || fail "mail subdomain not resolving"
dig +short scada-gw.boreas-systems.ctf @"$DNS" | grep -q '172.20.40' && pass "DNS scada-gw subdomain resolves" || fail "scada-gw not resolving"

echo
if (( FAIL == 0 )); then
    echo "A0 smoketest: PASS"
    exit 0
else
    echo "A0 smoketest: FAIL"
    exit 1
fi
