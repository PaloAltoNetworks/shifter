#!/usr/bin/env python3
"""
A11 Leg Controller smoketest.

Runs from inside a9-splice. Exercises the timed gait-sequence unlock
(0->1->2->0) and challenge-response for flag 33.

Usage (from the range host):
    docker cp smoketest.py a9-splice:/tmp/a11-smoke.py
    docker exec a9-splice python3 /tmp/a11-smoke.py

Exits 0 on full pass, 1 on any failure.
"""
import sys
import time

from pymodbus.client import ModbusTcpClient

HOST = "leg-ctrl"
PORT = 502

EXPECTED_CAL_CODE = 4783
EXPECTED_FLAG_33 = "FLAG{c7a1e3f9d0b52864}"

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


print(f"A11 smoketest - target={HOST}:{PORT}")

client = ModbusTcpClient(HOST, port=PORT)
if not client.connect():
    print("  [FAIL] cannot connect to A11")
    sys.exit(1)

try:
    print()
    print("--- Default register reads ---")
    rr = client.read_holding_registers(address=0, count=12)
    check("left+right leg joint angles reg 0-11 readable", not rr.isError())
    if not rr.isError():
        print(f"  joints: {rr.registers}")
    rr = client.read_holding_registers(address=20, count=6)
    check("hydraulic pressures reg 20-25 readable", not rr.isError())
    if not rr.isError():
        print(f"  pressures: {rr.registers}")
    rr = client.read_holding_registers(address=30, count=5)
    if not rr.isError():
        check(f"gait mode reg 30 = 0 stationary (got {rr.registers[0]})", rr.registers[0] == 0)
        check(f"step length reg 31 = 4200mm (got {rr.registers[1]})", rr.registers[1] == 4200)
        check(f"cycle time reg 32 = 85s (got {rr.registers[2]})", rr.registers[2] == 85)
        check(f"per-leg mass reg 33 = 24000t (got {rr.registers[3]})", rr.registers[3] == 24000)
        check(f"max actuator force reg 34 = 200t (got {rr.registers[4]})", rr.registers[4] == 200)

    print()
    print("--- Flag registers zero pre-unlock ---")
    rr = client.read_holding_registers(address=100, count=22)
    if not rr.isError():
        check("reg 100-121 all zero", all(v == 0 for v in rr.registers))

    print()
    print("--- Input reg 60 is 0 before calibration ---")
    rr = client.read_input_registers(address=60, count=1)
    check("input reg 60 = 0 pre-calibration", not rr.isError() and rr.registers[0] == 0)

    print()
    print("--- Wrong sequence gets rejected ---")
    # Start with 0 then write 3 (wrong)
    client.write_register(address=30, value=0)
    client.write_register(address=30, value=3)
    time.sleep(0.2)
    rr = client.read_input_registers(address=60, count=1)
    check("wrong sequence -> input reg 60 still 0", not rr.isError() and rr.registers[0] == 0)

    print()
    print("--- Correct gait sequence 0->1->2->0 ---")
    for i, value in enumerate([0, 1, 2, 0]):
        wr = client.write_register(address=30, value=value)
        check(f"  step {i+1}: write reg 30 = {value}", not wr.isError())
        time.sleep(0.1)

    time.sleep(0.3)
    rr = client.read_input_registers(address=60, count=1)
    if not rr.isError():
        got = rr.registers[0]
        check(f"input reg 60 = {EXPECTED_CAL_CODE} after sequence (got {got})",
              got == EXPECTED_CAL_CODE)

    print()
    print("--- Write challenge code to reg 99 ---")
    wr = client.write_register(address=99, value=EXPECTED_CAL_CODE)
    check(f"write reg 99 = {EXPECTED_CAL_CODE}", not wr.isError())

    time.sleep(0.3)
    rr = client.read_holding_registers(address=100, count=22)
    if rr.isError():
        fail(f"read reg 100-121 after unlock: {rr}")
    else:
        flag_ascii = "".join(chr(v) for v in rr.registers if 32 <= v < 127)
        if flag_ascii == EXPECTED_FLAG_33:
            pass_(f"flag 33 = {flag_ascii}")
        else:
            fail(f"flag 33 mismatch: expected={EXPECTED_FLAG_33} got='{flag_ascii}' raw={rr.registers}")

finally:
    client.close()

print()
if fails == 0:
    print("A11 smoketest: PASS")
    sys.exit(0)
else:
    print(f"A11 smoketest: FAIL ({fails} failure(s))")
    sys.exit(1)
