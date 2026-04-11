#!/bin/bash
# Test A9 — Splice Landing Box content
# Requires: A9 content files at standard locations on the test VM
# Tests: README, scan_results, modbus_client.py existence and content

set -e

# Check if content exists (could be in repo or deployed to /tmp)
CONTENT_DIR=""
for d in "/home/atomik/src/shifter-k8s/docs/ctf/mechag/A9-splice-landing" "/tmp/a9-content"; do
    [ -f "$d/README.txt" ] && CONTENT_DIR="$d" && break
done
[ -z "$CONTENT_DIR" ] && exit 77

python3 << PYEOF
import sys, os

CONTENT_DIR = "$CONTENT_DIR"
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

# README.txt
readme = os.path.join(CONTENT_DIR, "README.txt")
check("README.txt exists", os.path.isfile(readme))
with open(readme) as f:
    content = f.read()
check("README mentions POLARIS", "POLARIS" in content)
check("README mentions JTF-2", "JTF-2" in content)
check("README lists 4 hosts", "10.10.40.10" in content and "10.10.40.50" in content)
check("README mentions port 502", "502" in content)
check("README mentions port 9100", "9100" in content)
check("README mentions modbus_client.py", "modbus_client" in content)

# scan_results.txt
scan = os.path.join(CONTENT_DIR, "scan_results.txt")
check("scan_results.txt exists", os.path.isfile(scan))
with open(scan) as f:
    content = f.read()
check("scan shows 4 hosts up", "4 hosts up" in content)
check("scan shows 10.10.40.10", "10.10.40.10" in content)
check("scan shows 10.10.40.11", "10.10.40.11" in content)
check("scan shows 10.10.40.12", "10.10.40.12" in content)
check("scan shows 10.10.40.50", "10.10.40.50" in content)
check("scan shows port 9100", "9100" in content)

# modbus_client.py
client = os.path.join(CONTENT_DIR, "modbus_client.py")
check("modbus_client.py exists", os.path.isfile(client))
with open(client) as f:
    content = f.read()
check("client supports read command", "def read_registers" in content)
check("client supports write command", "def write_register" in content)
check("client supports devid command", "def read_device_id" in content or "devid" in content)
check("client supports scan command", "def scan_registers" in content or "scan" in content)
check("client uses pymodbus", "pymodbus" in content)

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
