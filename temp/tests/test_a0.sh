#!/bin/bash
# Test A0 — Boreas Website
# Requires: A0 server running on $A0_HOST:$A0_PORT
# Tests:
#   - Flag 1: HTML comment on /about near registration number
#   - Flag 2: In org chart document (metadata placeholder)
#   - Flag 3: Hidden form field on /careers
#   - Flag 4: HTML comment on /old/clients
#   - Registration number 7741 on /about (override code piece)
#   - /robots.txt disallows /internal/ and /admin/
#   - /internal/ directory listing accessible
#   - Annual report NOT in directory listing but accessible by URL
#   - Annual report contains Kursk $12M line (flag 6 data)
#   - /old/ backup site accessible with annual report URL hint

set -e

A0_HOST="${A0_HOST:-127.0.0.1}"
A0_PORT="${A0_PORT:-8082}"
BASE="http://${A0_HOST}:${A0_PORT}"

curl -sf "$BASE/" > /dev/null 2>&1 || exit 77

python3 << 'PYEOF'
import sys, os, requests

HOST = os.environ.get("A0_HOST", "127.0.0.1")
PORT = int(os.environ.get("A0_PORT", "8082"))
BASE = f"http://{HOST}:{PORT}"
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

# === Homepage ===
r = requests.get(f"{BASE}/")
check("homepage loads", r.status_code == 200)
check("homepage mentions Boreas", "Boreas" in r.text)

# === Flag 1: /about HTML comment with registration number ===
r = requests.get(f"{BASE}/about")
check("about page loads", r.status_code == 200)
check("registration number 7741 on about", "7741" in r.text, "override code piece missing")
check("flag 1 in HTML source", "FLAG{8f3a2c1e9b7d4056}" in r.text, "flag 1 not found")
# Verify it's in a comment
check("flag 1 is in HTML comment", "<!-- " in r.text and "FLAG{8f3a2c1e9b7d4056}" in r.text)

# === Flag 3: Hidden form field on /careers ===
r = requests.get(f"{BASE}/careers")
check("careers page loads", r.status_code == 200)
check("careers mentions Modbus/OPC-UA", "Modbus" in r.text and "OPC-UA" in r.text)
check("flag 3 in hidden field", 'type="hidden"' in r.text and "FLAG{a1c9e3f7054b82d6}" in r.text)

# === /robots.txt ===
r = requests.get(f"{BASE}/robots.txt")
check("robots.txt accessible", r.status_code == 200)
check("robots disallows /internal/", "/internal/" in r.text)
check("robots disallows /admin/", "/admin/" in r.text)

# === /internal/ directory listing ===
r = requests.get(f"{BASE}/internal/")
check("internal listing accessible", r.status_code == 200)
check("org chart listed", "org_chart" in r.text)
check("Q1 report listed", "Q1-2025" in r.text)
check("Q2 report listed", "Q2-2025" in r.text)
check("annual report NOT listed", "annual" not in r.text.lower(),
      "annual report should not be in directory listing")

# === Flag 2: Org chart ===
r = requests.get(f"{BASE}/internal/org_chart.txt")
check("org chart accessible", r.status_code == 200)
check("flag 2 in org chart", "FLAG{d4e7b1f283a6c950}" in r.text)
check("org chart shows Underground Operations", "Underground Operations" in r.text)

# === Annual report (fuzzable, not linked) ===
r = requests.get(f"{BASE}/internal/boreas-annual-2025.txt")
check("annual report accessible by URL", r.status_code == 200)
check("annual report has Kursk $12M", "Kursk" in r.text and "12,000,000" in r.text)
check("annual report has 40+ line items", r.text.count("$") >= 40,
      f"only {r.text.count('$')} $ signs")

# === /old/ backup site ===
r = requests.get(f"{BASE}/old/")
check("old site accessible", r.status_code == 200)
check("old site hints at annual report URL", "annual-2025" in r.text,
      "HTML comment with annual report path missing")

# === Flag 4: /old/clients ===
r = requests.get(f"{BASE}/old/clients")
check("old clients page accessible", r.status_code == 200)
check("flag 4 in HTML source", "FLAG{72b5e0d8f1a34c69}" in r.text)
check("Project L listed", "Project L" in r.text)
check("Project L budget $165M", "165" in r.text)

# === Leadership page ===
r = requests.get(f"{BASE}/leadership")
check("leadership loads", r.status_code == 200)
check("leadership shows Harlan", "Harlan" in r.text)
check("leadership shows Vasik", "Vasik" in r.text)
check("leadership shows Webb", "Webb" in r.text)

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
