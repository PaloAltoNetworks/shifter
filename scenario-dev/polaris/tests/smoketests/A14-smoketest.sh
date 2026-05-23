#!/usr/bin/env bash
# A14 Kali attack platform smoketest.
#
# A14 is not a target — it's the participant's attack box. This smoketest
# verifies the platform is ready for use: tools installed, content deployed,
# network position correct (can reach Front Office + shared, cannot reach
# Lab / SCADA / Bunker directly).
#
# Usage (from the range host):
#     docker cp smoketest.sh a14-kali:/tmp/a14-smoke.sh
#     docker exec a14-kali bash /tmp/a14-smoke.sh
#
# Exits 0 on full pass, 1 on any failure.

set -u

FAIL=0
pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
check() { (eval "$1") >/dev/null 2>&1 && pass "$2" || fail "$2"; }

echo "A14 smoketest - Kali attack platform"

echo
echo "--- Content files ---"
# README.md, mission_brief.{txt,pdf}, and tools/flag_submit.sh were removed
# in 2026-04 (see scenario-dev/polaris/build/a14/Dockerfile:85): they were
# stale relative to the CTFd board and Kali has no route to CTFd, so a
# Kali-side submission helper is broken by design. CTFd is the reference.
# The remaining content drops are modbus_scan.py (Mission 4 helper), the
# Claude POLARIS system prompt, and the warm-up challenge target.
for f in /home/kali/tools/modbus_scan.py \
         /home/kali/.config/claude/system_prompt.txt \
         /home/kali/.polaris/welcome.txt; do
    [[ -f "$f" ]] && pass "$f present" || fail "$f missing"
done
[[ -x /home/kali/tools/modbus_scan.py ]] && pass "modbus_scan.py executable" || fail "modbus_scan.py not exec"

echo
echo "--- Kali user and services ---"
id kali >/dev/null 2>&1 && pass "kali user exists" || fail "kali user missing"
pgrep -f sshd >/dev/null && pass "sshd running" || fail "sshd not running"
pgrep -f xrdp >/dev/null && pass "xrdp running" || fail "xrdp not running"
grep -q '^PasswordAuthentication yes' /etc/ssh/sshd_config && pass "sshd password auth enabled" || fail "ssh password auth off"

echo
echo "--- Standard Kali offensive tools ---"
for tool in nmap msfconsole sqlmap john hashcat gobuster ffuf nc curl wget python3 smbclient; do
    command -v "$tool" >/dev/null 2>&1 && pass "$tool installed" || fail "$tool missing"
done

echo
echo "--- Impacket suite ---"
for tool in GetUserSPNs.py secretsdump.py psexec.py smbclient.py lookupsid.py; do
    if [[ -x "/opt/tools/bin/$tool" ]] || command -v "$tool" >/dev/null 2>&1; then
        pass "$tool available"
    else
        fail "$tool missing"
    fi
done

echo
echo "--- Python libraries ---"
/opt/tools/bin/python3 -c "import pymodbus; print(pymodbus.__version__)" >/dev/null 2>&1 \
    && pass "pymodbus importable" || fail "pymodbus missing"
/opt/tools/bin/python3 -c "import impacket" >/dev/null 2>&1 \
    && pass "impacket importable" || fail "impacket missing"
/opt/tools/bin/python3 -c "from pdfminer.high_level import extract_text" >/dev/null 2>&1 \
    && pass "pdfminer.six importable" || fail "pdfminer.six missing"
/opt/tools/bin/python3 -c "import openpyxl" >/dev/null 2>&1 \
    && pass "openpyxl importable" || fail "openpyxl missing"
[[ -x /opt/tools/bin/pdf2txt.py ]] && pass "pdf2txt.py (pdfminer cli) available" || fail "pdf2txt.py missing"

echo
echo "--- Claude Code CLI ---"
if command -v claude >/dev/null 2>&1; then
    pass "claude CLI installed"
    [[ -f /home/kali/.config/claude/system_prompt.txt ]] \
        && pass "POLARIS system prompt deployed" \
        || fail "system prompt missing"
else
    fail "claude CLI missing"
fi

echo
echo "--- Network reach: permitted targets ---"
# A14 is on shared (172.20.0.0/24), corporate (172.20.10.0/24), and the
# pre-wired splice-link to A9. Should reach A0 (shared), A1/A3/A4/A15/A16
# (corporate), DNS (shared), A2 (GCP VM via host route), A9 (splice-link).
# A7 Gitea is lab-only and NOT directly reachable from A14 — participants
# must pivot through A16 to clone from Gitea.
for label_host_port in \
        "A0:boreas-systems.ctf:80" \
        "A1:mail.boreas.local:143" \
        "A3:intranet.boreas.local:80" \
        "A4:fileserv.boreas.local:445" \
        "A15:ops-eng01.boreas.local:22" \
        "A16:analyst01.boreas.local:22" \
        "A9:splice-relay:22" \
        "A2:dc01.boreas.local:389" \
        "DNS:172.20.0.2:53"; do
    label="${label_host_port%%:*}"
    rest="${label_host_port#*:}"
    host="${rest%:*}"
    port="${rest##*:}"
    if timeout 2 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null; then
        pass "$label $host:$port reachable"
    else
        fail "$label $host:$port unreachable"
    fi
done

echo
echo "--- DNS resolution for internal names ---"
for host in boreas-systems.ctf mail.boreas.local git.boreas.local intranet.boreas.local dc01.boreas.local; do
    getent hosts "$host" >/dev/null 2>&1 && pass "$host resolves" || fail "$host does not resolve"
done

echo
echo "--- AXFR zone transfer works (flag 5 discovery path) ---"
if command -v dig >/dev/null; then
    dig axfr boreas-systems.ctf @172.20.0.2 2>&1 | grep -q "_flag" \
        && pass "AXFR returns _flag TXT record" \
        || fail "AXFR missing _flag TXT"
else
    fail "dig not installed"
fi

echo
if (( FAIL == 0 )); then
    echo "A14 smoketest: PASS"
    exit 0
else
    echo "A14 smoketest: FAIL ($FAIL failure(s))"
    exit 1
fi
