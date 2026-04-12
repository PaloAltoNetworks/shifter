#!/bin/bash
# Test A11 — Leg Controller
# Requires: A11 server running on $A11_HOST:$A11_PORT
# Tests: register values, device ID, timed sequence unlock, wrong sequence rejection

set -e

A11_HOST="${A11_HOST:-127.0.0.1}"
A11_PORT="${A11_PORT:-5021}"

python3 -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('$A11_HOST', port=$A11_PORT)
if not c.connect(): exit(77)
c.close()
" || exit 77

python3 << 'PYEOF'
import sys, os, time
from pymodbus.client import ModbusTcpClient

HOST = os.environ.get("A11_HOST", "127.0.0.1")
PORT = int(os.environ.get("A11_PORT", "5021"))
errors = []

def check(name, condition, detail=""):
    if not condition:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

c = ModbusTcpClient(HOST, port=PORT)
c.connect()

# --- Operational registers ---
r = c.read_holding_registers(address=30, count=5)
check("gait mode is 0 (stationary)", r.registers[0] == 0, f"got {r.registers[0]}")
check("step length is 4200mm", r.registers[1] == 4200, f"got {r.registers[1]}")
check("cycle time is 85s", r.registers[2] == 85, f"got {r.registers[2]}")
check("per-leg mass is 24000t", r.registers[3] == 24000, f"got {r.registers[3]}")
check("max actuator force is 200t", r.registers[4] == 200, f"got {r.registers[4]}")

# --- Input reg 60 initially zero ---
r = c.read_input_registers(address=60, count=1)
check("input reg 60 initially 0", r.registers[0] == 0, f"got {r.registers[0]}")

# --- Flag registers locked ---
r = c.read_holding_registers(address=100, count=24)
check("flag regs locked", all(v == 0 for v in r.registers))

# --- Wrong sequence produces no code ---
for mode in [0, 2, 1, 0]:  # wrong order
    c.write_register(address=30, value=mode)
    time.sleep(0.3)
r = c.read_input_registers(address=60, count=1)
check("wrong sequence no code", r.registers[0] == 0, f"got {r.registers[0]}")

# --- Correct sequence: 0->1->2->0 ---
for mode in [0, 1, 2, 0]:
    c.write_register(address=30, value=mode)
    time.sleep(0.5)
time.sleep(0.5)

r = c.read_input_registers(address=60, count=1)
code = r.registers[0]
check("calibration code appears", code > 0, f"got {code}")
check("calibration code is 4783", code == 4783, f"got {code}")

# --- Write code to unlock ---
c.write_register(address=99, value=code)
time.sleep(0.5)
r = c.read_holding_registers(address=100, count=24)
flag = "".join(chr(v) for v in r.registers if v > 0)
check("flag 33 correct", flag == "FLAG{c7a1e3f9d0b52864}", f"got '{flag}'")

c.close()

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
