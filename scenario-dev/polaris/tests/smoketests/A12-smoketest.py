#!/usr/bin/env python3
"""
A12 Arms Controller smoketest.

Runs from inside a9-splice. Exercises the rolling-nonce
challenge-response unlock for flag 34. Requires cross-zone intel
(XOR key 2847 = PO-2847 from A4 Front Office).

Usage (from the range host):
    docker cp smoketest.py a9-splice:/tmp/a12-smoke.py
    docker exec a9-splice python3 /tmp/a12-smoke.py

Exits 0 on full pass, 1 on any failure.
"""
import sys
import time

from pymodbus.client import ModbusTcpClient

HOST = "arms-ctrl"
PORT = 502

XOR_KEY = 2847  # from PO-2847 in A4 Procurement share
EXPECTED_FLAG_34 = "FLAG{f0d8b2e6a4c71935}"

fails = 0


def pass_(label):
    print(f"  [PASS] {label}")


def fail(label):
    global fails
    fails += 1
    print(f"  [FAIL] {label}")


def check(label, cond):
    (pass_ if cond else fail)(label)
    return cond


print(f"A12 smoketest - target={HOST}:{PORT}")

client = ModbusTcpClient(HOST, port=PORT)
if not client.connect():
    print("  [FAIL] cannot connect to A12")
    sys.exit(1)

try:
    print()
    print("--- Default register reads ---")
    rr = client.read_holding_registers(address=0, count=12)
    check("arm joint angles reg 0-11 readable", not rr.isError())
    if not rr.isError():
        print(f"  joints: {rr.registers}")

    rr = client.read_holding_registers(address=20, count=4)
    check("actuator force reg 20-23 readable", not rr.isError())

    rr = client.read_holding_registers(address=30, count=1)
    check(f"arms mode reg 30 = 0 stowed (got {rr.registers[0] if not rr.isError() else '?'})",
          not rr.isError() and rr.registers[0] == 0)

    rr = client.read_holding_registers(address=40, count=4)
    if not rr.isError():
        check(f"primary effector status reg 40 = 0 offline (got {rr.registers[0]})", rr.registers[0] == 0)
        check(f"primary effector max output reg 41 = 2400 MW (got {rr.registers[1]})", rr.registers[1] == 2400)
        check(f"primary effector sustained draw reg 42 = 1800 MW (got {rr.registers[2]})", rr.registers[2] == 1800)

    rr = client.read_holding_registers(address=54, count=2)
    if not rr.isError():
        check(f"kinetic caliber reg 54 = 500mm (got {rr.registers[0]})", rr.registers[0] == 500)
        check(f"rounds per mag reg 55 = 12 (got {rr.registers[1]})", rr.registers[1] == 12)

    print()
    print("--- Pre-unlock: flag registers zero, input reg 60 zero ---")
    rr = client.read_holding_registers(address=100, count=22)
    if not rr.isError():
        check("reg 100-121 all zero before unlock", all(v == 0 for v in rr.registers))
    rr = client.read_input_registers(address=60, count=1)
    if not rr.isError():
        check("input reg 60 = 0 before diagnostics enabled", rr.registers[0] == 0)

    print()
    print("--- Wrong challenge write before diag enabled is ignored ---")
    client.write_register(address=200, value=0)
    rr = client.read_holding_registers(address=201, count=1)
    if not rr.isError():
        check("reg 201 still 0 (no confirmation without diag)", rr.registers[0] == 0)

    print()
    print("--- Enable diagnostics: write coil 50 = 1 ---")
    wr = client.write_coil(address=50, value=True)
    check("write coil 50 = 1", not wr.isError())
    time.sleep(0.3)

    print()
    print("--- Read rolling nonce from input reg 60 ---")
    rr = client.read_input_registers(address=60, count=1)
    nonce = rr.registers[0] if not rr.isError() else 0
    check(f"nonce is 4 digits (1000-9999): {nonce}", 1000 <= nonce <= 9999)

    print()
    print("--- XOR nonce with PO-2847 key, write response to reg 200 ---")
    response = nonce ^ XOR_KEY
    print(f"  nonce={nonce} XOR {XOR_KEY} = {response}")
    wr = client.write_register(address=200, value=response)
    check(f"write reg 200 = {response}", not wr.isError())
    time.sleep(0.3)

    print()
    print("--- Verify confirmation readback on reg 201 ---")
    rr = client.read_holding_registers(address=201, count=1)
    if not rr.isError():
        check(f"reg 201 = 1 after correct challenge (got {rr.registers[0]})", rr.registers[0] == 1)

    print()
    print("--- Read flag ASCII from reg 100-121 ---")
    rr = client.read_holding_registers(address=100, count=22)
    if rr.isError():
        fail(f"read reg 100-121 after unlock: {rr}")
    else:
        flag_ascii = "".join(chr(v) for v in rr.registers if 32 <= v < 127)
        if flag_ascii == EXPECTED_FLAG_34:
            pass_(f"flag 34 = {flag_ascii}")
        else:
            fail(f"flag 34 mismatch: expected={EXPECTED_FLAG_34} got='{flag_ascii}' raw={rr.registers}")

finally:
    client.close()

print()
if fails == 0:
    print("A12 smoketest: PASS")
    sys.exit(0)
else:
    print(f"A12 smoketest: FAIL ({fails} failure(s))")
    sys.exit(1)
