#!/bin/bash
# Test A12 — Arms Controller
# Requires: A12 server running on $A12_HOST:$A12_PORT
# Tests: register values, device ID, rolling nonce XOR challenge, wrong response rejection

set -e

A12_HOST="${A12_HOST:-127.0.0.1}"
A12_PORT="${A12_PORT:-5022}"

python3 -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('$A12_HOST', port=$A12_PORT)
if not c.connect(): exit(77)
c.close()
" || exit 77

python3 << 'PYEOF'
import sys, os, time
from pymodbus.client import ModbusTcpClient

HOST = os.environ.get("A12_HOST", "127.0.0.1")
PORT = int(os.environ.get("A12_PORT", "5022"))
errors = []

def check(name, condition, detail=""):
    if not condition:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

c = ModbusTcpClient(HOST, port=PORT)
c.connect()

# --- Operational registers ---
r = c.read_holding_registers(address=41, count=3)
check("max output 2400MW", r.registers[0] == 2400, f"got {r.registers[0]}")
check("sustained draw 1800MW", r.registers[1] == 1800, f"got {r.registers[1]}")
check("target lock 0", r.registers[2] == 0, f"got {r.registers[2]}")

r = c.read_holding_registers(address=54, count=2)
check("caliber 500mm", r.registers[0] == 500, f"got {r.registers[0]}")
check("rounds 12", r.registers[1] == 12, f"got {r.registers[1]}")

# --- No nonce before diagnostics ---
r = c.read_input_registers(address=60, count=1)
check("no nonce before diag enable", r.registers[0] == 0, f"got {r.registers[0]}")

# --- Flag registers locked ---
r = c.read_holding_registers(address=100, count=24)
check("flag regs locked", all(v == 0 for v in r.registers))

# --- Enable diagnostics ---
c.write_coil(address=50, value=True)
time.sleep(0.5)

# --- Read nonce ---
r = c.read_input_registers(address=60, count=1)
nonce = r.registers[0]
check("nonce appears after diag enable", nonce > 0, f"got {nonce}")
check("nonce is 4 digits", 1000 <= nonce <= 9999, f"got {nonce}")

# --- Wrong response ---
c.write_register(address=200, value=9999)
time.sleep(0.3)
r = c.read_holding_registers(address=201, count=1)
check("wrong response confirmation=0", r.registers[0] == 0, f"got {r.registers[0]}")
r = c.read_holding_registers(address=100, count=24)
check("flag still locked after wrong", all(v == 0 for v in r.registers))

# --- Correct response: nonce XOR 2847 ---
# Re-read nonce (may have been same window or rotated)
r = c.read_input_registers(address=60, count=1)
nonce = r.registers[0]
response = nonce ^ 2847
c.write_register(address=200, value=response)
time.sleep(0.5)

r = c.read_holding_registers(address=201, count=1)
check("correct response confirmation=1", r.registers[0] == 1, f"got {r.registers[0]}")

r = c.read_holding_registers(address=100, count=24)
flag = "".join(chr(v) for v in r.registers if v > 0)
check("flag 34 correct", flag == "FLAG{f0d8b2e6a4c71935}", f"got '{flag}'")

c.close()

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
