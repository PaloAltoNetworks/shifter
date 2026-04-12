#!/usr/bin/env python3
"""
A11 — Leg Controller
Modbus/TCP server simulating the bipedal locomotion PLC for PROJECT LEVIATHAN.

pymodbus 3.12+ API.

Registers:
  Holding 0-5:   Left leg joint angles (hip, knee, ankle: position, target)
  Holding 6-11:  Right leg joint angles
  Holding 20-25: Hydraulic pressure per joint (MPa)
  Holding 30:    Gait mode (0=stationary, 1=walk, 2=run, 3=combat stance)
  Holding 31:    Step length (mm) = 4200
  Holding 32:    Step cycle time (seconds) = 85
  Holding 33:    Per-leg mass (metric tons) = 24000
  Holding 34:    Max actuator force (tons) = 200
  Input 60:      Calibration code (appears after correct sequence)
  Holding 99:    Challenge register (write calibration code to unlock)
  Holding 100-123: Flag registers (zeros until unlocked)

Device Identification:
  Vendor:  AURORA HEAVY SYSTEMS
  Model:   AHS-LEG-MN07
  Serial:  AHS-L-00483

Flag 33 unlock:
  1. Write gait mode sequence 0→1→2→0 to register 30 within 10 seconds
  2. Read calibration code from input register 60 (becomes 4783)
  3. Write 4783 to holding register 99
  4. Registers 100-123 return FLAG as ASCII
"""

import logging
import os
import time
import threading

from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.pdu.device import ModbusDeviceIdentification
from pymodbus.server import StartTcpServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("a11-leg")

# --- Constants ---
VENDOR = "AURORA HEAVY SYSTEMS"
MODEL = "AHS-LEG-MN07"
SERIAL = "AHS-L-00483"
PRODUCT_CODE = "LEG-BIPED-MK2"

CALIBRATION_CODE = 4783
FLAG = "FLAG{c7a1e3f9d0b52864}"
SEQUENCE_TIMEOUT_S = 10
CODE_VALID_S = 60

# Expected gait sequence: 0 → 1 → 2 → 0
EXPECTED_SEQUENCE = [0, 1, 2, 0]

# Joint angles (degrees): hip_pos, hip_tgt, knee_pos, knee_tgt, ankle_pos, ankle_tgt
LEFT_JOINTS = [0, 0, 15, 15, -5, -5]
RIGHT_JOINTS = [0, 0, 15, 15, -5, -5]
PRESSURES = [180, 175, 190, 185, 160, 155]  # MPa per joint


class LegHoldingBlock(ModbusSequentialDataBlock):
    """Custom holding register block with timed sequence unlock logic."""

    def __init__(self, address, values, input_block):
        super().__init__(address, values)
        self._input_block = input_block
        self._sequence = []
        self._sequence_start = None
        self._code_presented_time = None
        self._unlocked = False
        self._lock = threading.Lock()

    def setValues(self, address, values):
        """Intercept writes for timed sequence and challenge logic."""
        reg = address - 1  # wire address (ModbusDeviceContext adds +1)

        # Write to register 30 (gait mode)
        if reg == 30 and len(values) == 1:
            mode = values[0]
            with self._lock:
                now = time.time()

                in_progress = (len(self._sequence) > 0 and self._sequence_start
                              and (now - self._sequence_start) <= SEQUENCE_TIMEOUT_S)

                if in_progress:
                    # Sequence is active and within timeout — check next expected value
                    expected_idx = len(self._sequence)
                    if expected_idx < len(EXPECTED_SEQUENCE) and mode == EXPECTED_SEQUENCE[expected_idx]:
                        self._sequence.append(mode)
                        log.info("Sequence step %d: [%s]", expected_idx, ",".join(str(x) for x in self._sequence))

                        if self._sequence == EXPECTED_SEQUENCE:
                            log.info("Calibration sequence complete — presenting code %d on input reg 60", CALIBRATION_CODE)
                            self._code_presented_time = now
                            self._input_block.setValues(61, [CALIBRATION_CODE])
                            self._sequence = []
                            self._sequence_start = None
                    else:
                        log.info("Sequence broken at step %d (got %d, expected %d) — reset",
                                expected_idx, mode, EXPECTED_SEQUENCE[expected_idx] if expected_idx < len(EXPECTED_SEQUENCE) else -1)
                        self._sequence = []
                        self._sequence_start = None
                        self._input_block.setValues(61, [0])
                        self._code_presented_time = None
                        # If the breaking value happens to be the start value, begin a new sequence
                        if mode == EXPECTED_SEQUENCE[0]:
                            self._sequence = [mode]
                            self._sequence_start = now
                            log.info("Sequence restarted: [%d]", mode)
                elif mode == EXPECTED_SEQUENCE[0]:
                    # No active sequence — start a new one if this is the start value
                    self._sequence = [mode]
                    self._sequence_start = now
                    log.info("Sequence started: [%d]", mode)
                    # Clear any stale state
                    if self._code_presented_time and not self._unlocked:
                        self._input_block.setValues(61, [0])
                        self._code_presented_time = None

            super().setValues(address, values)
            return

        # Write to register 99 (challenge response)
        if reg == 99 and len(values) == 1:
            with self._lock:
                if self._code_presented_time is not None:
                    elapsed = time.time() - self._code_presented_time
                    if elapsed > CODE_VALID_S:
                        log.info("Code expired (%.1fs) — reset", elapsed)
                        self._input_block.setValues(61, [0])
                        self._code_presented_time = None
                    elif values[0] == CALIBRATION_CODE:
                        log.info("Calibration code correct — flag unlocked")
                        self._unlocked = True
                        self._code_presented_time = None
                        self._write_flag()
                    else:
                        log.info("Wrong code (got %d, want %d) — reset", values[0], CALIBRATION_CODE)
                        self._input_block.setValues(61, [0])
                        self._code_presented_time = None
                else:
                    log.info("Code write without calibration — ignored")
            return

        super().setValues(address, values)

    def _write_flag(self):
        flag_ascii = [ord(c) for c in FLAG]
        while len(flag_ascii) < 24:
            flag_ascii.append(0)
        super().setValues(101, flag_ascii[:24])  # internal addr 101 = wire addr 100


def build_context():
    """Build Modbus data store."""
    # Holding registers: dummy + 256
    hr = [0] * 257
    for i, v in enumerate(LEFT_JOINTS):
        hr[i + 1] = v        # wire 0-5
    for i, v in enumerate(RIGHT_JOINTS):
        hr[7 + i] = v        # wire 6-11
    for i, v in enumerate(PRESSURES):
        hr[21 + i] = v       # wire 20-25
    hr[31] = 0       # wire 30: gait mode = stationary
    hr[32] = 4200    # wire 31: step length mm
    hr[33] = 85      # wire 32: cycle time seconds
    hr[34] = 24000   # wire 33: per-leg mass metric tons
    hr[35] = 200     # wire 34: max actuator force tons

    # Input registers: dummy + 65
    ir = [0] * 66  # wire addr 0-64, index 0 is dummy

    input_block = ModbusSequentialDataBlock(0, ir)
    holding = LegHoldingBlock(0, hr, input_block)

    store = ModbusDeviceContext(
        di=ModbusSequentialDataBlock(0, [0] * 17),
        co=ModbusSequentialDataBlock(0, [0] * 51),
        hr=holding,
        ir=input_block,
    )
    return ModbusServerContext(devices=store, single=True)


def build_identity():
    identity = ModbusDeviceIdentification()
    identity.VendorName = VENDOR
    identity.ProductCode = PRODUCT_CODE
    identity.VendorUrl = "https://aurora-internal.boreas.local"
    identity.ProductName = MODEL
    identity.ModelName = MODEL
    identity.MajorMinorRevision = "2.4.1"
    return identity


def main():
    context = build_context()
    identity = build_identity()

    port = int(os.environ.get("MODBUS_PORT", "502"))
    log.info("A11 Leg Controller starting on port %d", port)
    log.info("  Vendor: %s | Model: %s | Serial: %s", VENDOR, MODEL, SERIAL)
    log.info("  Sequence: %s within %ds", EXPECTED_SEQUENCE, SEQUENCE_TIMEOUT_S)
    log.info("  Calibration code: %d", CALIBRATION_CODE)

    StartTcpServer(context=context, identity=identity, address=("0.0.0.0", port))


if __name__ == "__main__":
    main()
