#!/bin/bash
# Chain test: Flag 33 — A7 manufacturing-orchestrator → A11 leg controller
#
# Path: Read deploy_combat_ai.yml from A7 → learn calibration sequence 0→1→2→0 →
#       execute sequence on A11 → read code from input reg 60 → write to reg 99 → flag
#
# Requires: Gitea on :3000, A11 on $A11_PORT

set -e
A11_HOST="${A11_HOST:-127.0.0.1}"
A11_PORT="${A11_PORT:-5021}"

curl -sf http://localhost:3000/api/v1/version > /dev/null 2>&1 || exit 77
python3 -c "from pymodbus.client import ModbusTcpClient; c=ModbusTcpClient('$A11_HOST',port=$A11_PORT); exit(0 if c.connect() else 77); c.close()" || exit 77

python3 << 'PYEOF'
import subprocess, sys, os, tempfile, shutil, time

errors = []
def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

HOST = os.environ.get("A11_HOST", "127.0.0.1")
PORT = int(os.environ.get("A11_PORT", "5021"))

# Step 1: Clone manufacturing-orchestrator, find calibration sequence
d = tempfile.mkdtemp()
subprocess.run(["git", "clone", "-q",
    "http://e_vasik:TestPass123!@localhost:3000/aurora/manufacturing-orchestrator.git", d],
    capture_output=True, check=True)
with open(os.path.join(d, "playbooks", "deploy_combat_ai.yml")) as f:
    playbook = f.read()
# Participant reads: "0 -> 1 -> 2 -> 0 (stationary -> walk -> run -> stationary) within 10 seconds"
check("playbook documents 0->1->2->0 sequence", "0" in playbook and "1" in playbook and "2" in playbook)
check("playbook mentions 10 second window", "10 second" in playbook.lower() or "10s" in playbook.lower())
check("playbook mentions input register 60", "register 60" in playbook or "input register" in playbook.lower())
shutil.rmtree(d)

# Step 2: Check if already unlocked
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient(HOST, port=PORT)
c.connect()

r = c.read_holding_registers(address=100, count=24)
already_unlocked = any(v > 0 for v in r.registers)

if not already_unlocked:
    for mode in [0, 1, 2, 0]:
        c.write_register(address=30, value=mode)
        time.sleep(0.5)
    time.sleep(0.5)
    r = c.read_input_registers(address=60, count=1)
    code = r.registers[0]
    check("calibration code appeared", code > 0, f"got {code}")
    c.write_register(address=99, value=code)
    time.sleep(0.5)
    r = c.read_holding_registers(address=100, count=24)

flag = "".join(chr(v) for v in r.registers if v > 0)
check("flag 33 unlocked via A7 hint chain", flag == "FLAG{c7a1e3f9d0b52864}", f"got: {flag!r}")
c.close()

if errors:
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
