#!/usr/bin/env python3
"""
A10 Tail Controller smoketest.

Runs from inside a9-splice (the Bunker OT entry point). Uses pymodbus
(bundled in a9's image) to exercise the flag 32 unlock sequence and
verify the register map.

Usage (from the range host):
    docker cp smoketest.py a9-splice:/tmp/a10-smoke.py
    docker exec a9-splice python3 /tmp/a10-smoke.py

Exits 0 on full pass, 1 on any failure.
"""
import sys
import time

from pymodbus.client import ModbusTcpClient

HOST = "tail-ctrl"
PORT = 502

EXPECTED_VENDOR = "AURORA HEAVY SYSTEMS"
EXPECTED_MODEL = "AHS-TAIL-7741"
SERIAL_CHALLENGE = 482  # last 3 digits of AHS-T-00482
EXPECTED_FLAG_32 = "FLAG{9b3e7c1d0f5a2846}"

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


print(f"A10 smoketest - target={HOST}:{PORT}")

client = ModbusTcpClient(HOST, port=PORT)
if not client.connect():
    print("  [FAIL] cannot connect to A10")
    sys.exit(1)

try:
    print()
    print("--- Device identification (verified in A9 smoketest - skipped here) ---")
    print("  (A9 smoketest uses modbus_client.py devid which covers A10/A11/A12)")

    print()
    print("--- Default register reads (unauthorised) ---")
    rr = client.read_holding_registers(address=0, count=10)
    check("motor positions reg 0-9 readable", not rr.isError())
    if not rr.isError():
        print(f"  motors: {rr.registers}")
    rr = client.read_holding_registers(address=10, count=10)
    check("torque reg 10-19 readable", not rr.isError())
    rr = client.read_holding_registers(address=20, count=1)
    mode = rr.registers[0] if not rr.isError() else None
    check(f"tail mode reg 20 = 1 (balance) initially (got {mode})", mode == 1)
    rr = client.read_holding_registers(address=21, count=2)
    if not rr.isError():
        check(f"tail length reg 21 = 120 (got {rr.registers[0]})", rr.registers[0] == 120)
        check(f"tail mass reg 22 = 8500 (got {rr.registers[1]})", rr.registers[1] == 8500)

    print()
    print("--- Flag registers are zero pre-unlock ---")
    rr = client.read_holding_registers(address=100, count=22)
    if not rr.isError():
        all_zero = all(v == 0 for v in rr.registers)
        check("reg 100-121 all zero before unlock", all_zero)

    print()
    print("--- Flag 32 unlock sequence ---")
    wr = client.write_register(address=20, value=3)
    check("write reg 20 = 3 (diagnostic mode)", not wr.isError())

    rr = client.read_holding_registers(address=100, count=22)
    flag_after_mode_only = "".join(chr(v) for v in rr.registers if 32 <= v < 127)
    check("reg 100-121 still zero after mode-only (challenge required)",
          all(v == 0 for v in rr.registers))

    wr = client.write_register(address=99, value=SERIAL_CHALLENGE)
    check(f"write reg 99 = {SERIAL_CHALLENGE} (last 3 of serial AHS-T-00482)", not wr.isError())

    rr = client.read_holding_registers(address=100, count=22)
    if rr.isError():
        fail(f"read reg 100-121 after unlock: {rr}")
    else:
        flag_ascii = "".join(chr(v) for v in rr.registers if 32 <= v < 127)
        if flag_ascii == EXPECTED_FLAG_32:
            pass_(f"flag 32 = {flag_ascii}")
        else:
            fail(f"flag 32 mismatch: expected={EXPECTED_FLAG_32} got='{flag_ascii}' raw={rr.registers}")

    print()
    print("--- Wrong challenge path (fresh state) ---")
    client.write_register(address=20, value=1)  # reset to balance
    time.sleep(0.2)
    client.write_register(address=20, value=3)
    client.write_register(address=99, value=9999)  # wrong
    time.sleep(0.2)
    # After wrong challenge, mode should have reset to 1
    rr = client.read_holding_registers(address=20, count=1)
    if not rr.isError():
        check("mode reset to 1 after wrong challenge", rr.registers[0] == 1)

    print()
    print("--- Coils 30-39 (motor enables) ---")
    rr = client.read_coils(address=30, count=10)
    if not rr.isError():
        all_on = all(rr.bits[:10])
        check("all 10 motor enable coils ON", all_on)

finally:
    client.close()

print()
if fails == 0:
    print("A10 smoketest: PASS")
    sys.exit(0)
else:
    print(f"A10 smoketest: FAIL ({fails} failure(s))")
    sys.exit(1)
