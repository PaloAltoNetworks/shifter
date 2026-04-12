#!/bin/bash
# Chain test: Flag 34 — A4 PO number → A12 arms controller XOR key
#
# Path: Read PO-2847 from A4 file share → extract PO number 2847 →
#       use as XOR key against A12 rolling nonce → flag 34
#
# Requires: A4 content at /tmp/a4-content/, A12 server running

set -e

A12_HOST="${A12_HOST:-127.0.0.1}"
A12_PORT="${A12_PORT:-5022}"

[ -f "/tmp/a4-content/Procurement/PO-2847_hydraulic_actuators.pdf" ] || exit 77
python3 -c "from pymodbus.client import ModbusTcpClient; c=ModbusTcpClient('$A12_HOST',port=$A12_PORT); exit(0 if c.connect() else 77); c.close()" || exit 77

python3 << 'PYEOF'
import sys, os, time, re
from pdfminer.high_level import extract_text
from pymodbus.client import ModbusTcpClient

HOST = os.environ.get("A12_HOST", "127.0.0.1")
PORT = int(os.environ.get("A12_PORT", "5022"))
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

# Step 1: Extract PO number from A4 document
pdf_path = "/tmp/a4-content/Procurement/PO-2847_hydraulic_actuators.pdf"
text = extract_text(pdf_path)
# Participant would notice "PO-2847" in the filename and document
match = re.search(r"PO[- ]?(\d{4})", text)
check("PO number extractable from document", match is not None, "no PO number found")
po_number = int(match.group(1)) if match else 0
check("PO number is 2847", po_number == 2847, f"got {po_number}")

# Step 2: Use PO number as XOR key against A12 nonce
c = ModbusTcpClient(HOST, port=PORT)
c.connect()

# Check if already unlocked from a prior test run
r = c.read_holding_registers(address=100, count=24)
already_unlocked = any(v > 0 for v in r.registers)

if already_unlocked:
    # Flag was already unlocked by unit test — just verify it's correct
    flag = "".join(chr(v) for v in r.registers if v > 0)
    check("flag 34 (pre-unlocked) via A4→A12 chain", flag == "FLAG{f0d8b2e6a4c71935}", f"got: {flag!r}")
else:
    # Fresh state — do the full XOR challenge
    c.write_coil(address=50, value=True)
    time.sleep(0.5)
    r = c.read_input_registers(address=60, count=1)
    nonce = r.registers[0]
    check("nonce from A12", nonce > 0, f"got {nonce}")

    response = nonce ^ po_number
    c.write_register(address=200, value=response)
    time.sleep(0.5)

    r = c.read_holding_registers(address=201, count=1)
    check("confirmation=1", r.registers[0] == 1, f"got {r.registers[0]}")

    r = c.read_holding_registers(address=100, count=24)
    flag = "".join(chr(v) for v in r.registers if v > 0)
    check("flag 34 via A4→A12 chain", flag == "FLAG{f0d8b2e6a4c71935}", f"got: {flag!r}")

c.close()

if errors:
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
