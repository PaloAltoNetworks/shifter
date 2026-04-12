#!/bin/bash
# Test A10 — Tail Controller
# Requires: A10 server running on $A10_HOST:$A10_PORT
# Tests: register values, device ID, flag 32 unlock, wrong challenge rejection

set -e

A10_HOST="${A10_HOST:-127.0.0.1}"
A10_PORT="${A10_PORT:-5020}"

# Check if server is reachable
python3 -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('$A10_HOST', port=$A10_PORT)
if not c.connect():
    exit(77)
c.close()
" || exit 77

python3 << 'PYEOF'
import sys, os
from pymodbus.client import ModbusTcpClient
from pymodbus.pdu.mei_message import ReadDeviceInformationRequest
import time

HOST = os.environ.get("A10_HOST", "127.0.0.1")
PORT = int(os.environ.get("A10_PORT", "5020"))
errors = []

def check(name, condition, detail=""):
    if not condition:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)
    return condition

c = ModbusTcpClient(HOST, port=PORT)
c.connect()

# --- Operational registers ---
r = c.read_holding_registers(address=20, count=3)
check("mode is 1 (balance)", r.registers[0] == 1, f"got {r.registers[0]}")
check("length is 120m", r.registers[1] == 120, f"got {r.registers[1]}")
check("mass is 8500t", r.registers[2] == 8500, f"got {r.registers[2]}")

# Motor positions (10 segments)
r = c.read_holding_registers(address=0, count=10)
check("10 motor positions", len(r.registers) == 10, f"got {len(r.registers)}")
check("motor positions nonzero", any(v > 0 for v in r.registers), f"all zero")

# Torque values
r = c.read_holding_registers(address=10, count=10)
check("10 torque values", len(r.registers) == 10)
check("torque values nonzero", any(v > 0 for v in r.registers), f"all zero")

# --- Device identification ---
rq = ReadDeviceInformationRequest(read_code=1)
resp = c.execute(False, rq)
if hasattr(resp, "information") and resp.information:
    vendor = resp.information.get(0, b"").decode() if isinstance(resp.information.get(0), bytes) else ""
    check("vendor is AURORA HEAVY SYSTEMS", "AURORA" in vendor, f"got '{vendor}'")
else:
    errors.append("FAIL: device identification returned no information")

# --- Flag registers locked before unlock ---
r = c.read_holding_registers(address=100, count=24)
check("flag regs locked (all zero)", all(v == 0 for v in r.registers), f"nonzero found: {[v for v in r.registers if v]}")

# --- Wrong challenge rejects ---
c.write_register(address=20, value=3)
c.write_register(address=99, value=9999)  # wrong
time.sleep(0.3)
r = c.read_holding_registers(address=20, count=1)
check("wrong challenge resets mode to 1", r.registers[0] == 1, f"mode is {r.registers[0]}")
r = c.read_holding_registers(address=100, count=24)
check("flag still locked after wrong challenge", all(v == 0 for v in r.registers))

# --- Correct unlock sequence ---
c.write_register(address=20, value=3)
c.write_register(address=99, value=482)
time.sleep(0.5)
r = c.read_holding_registers(address=100, count=24)
flag = "".join(chr(v) for v in r.registers if v > 0)
check("flag 32 correct", flag == "FLAG{9b3e7c1d0f5a2846}", f"got '{flag}'")

c.close()

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
