#!/usr/bin/env python3
"""
A12 — Arms Controller
Modbus/TCP server simulating the arm and weapons PLC for PROJECT LEVIATHAN.

pymodbus 3.12+ API.

Registers:
  Holding 0-5:   Left arm joint angles (shoulder, elbow, wrist: pos, tgt)
  Holding 6-11:  Right arm joint angles
  Holding 20-23: Arm actuator force per joint
  Holding 30:    Arms mode (0=stowed, 1=ready, 2=engaged)
  Holding 40:    Primary effector status (0=offline, 1=charging, 2=ready, 3=firing)
  Holding 41:    Primary effector max output (MW) = 2400
  Holding 42:    Primary effector sustained draw (MW) = 1800
  Holding 43:    Primary effector target lock (0=none)
  Holding 50-53: Secondary weapons (0=safe, 1=armed)
  Holding 54:    Kinetic weapon caliber (mm) = 500
  Holding 55:    Rounds per magazine = 12
  Coil 50:       Diagnostics enable
  Input 60:      Rolling challenge nonce (changes every 30s)
  Holding 99:    Challenge response register
  Holding 200:   Challenge response write target
  Holding 201:   Confirmation readback (0=pending, 1=confirmed)
  Holding 100-123: Flag registers (zeros until unlocked)

Device Identification:
  Vendor:  AURORA HEAVY SYSTEMS
  Model:   AHS-ARM-AL42
  Serial:  AHS-A-00484

Flag 34 unlock:
  1. Write 1 to coil 50 (enable diagnostics)
  2. Read input register 60 (4-digit nonce, rolls every 30s)
  3. Compute: nonce XOR 2847
  4. Write result to holding register 200 within same 30s window
  5. Read holding register 201 — if 1, confirmed
  6. Registers 100-123 return FLAG as ASCII
"""

import logging
import os
import time
import threading
import random

from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.pdu.device import ModbusDeviceIdentification
from pymodbus.server import StartTcpServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("a12-arms")

# --- Constants ---
VENDOR = "AURORA HEAVY SYSTEMS"
MODEL = "AHS-ARM-AL42"
SERIAL = "AHS-A-00484"
PRODUCT_CODE = "ARM-WEAP-MK2"
APP_NAME = f"Arms Weapons Controller v2.4 -- SN: {SERIAL} -- diagnostics: coil 50"

XOR_KEY = 2847  # PO number from Front Office (A4)
FLAG = "FLAG{f0d8b2e6a4c71935}"
NONCE_PERIOD_S = 30

# Joint angles (degrees)
LEFT_ARM = [0, 0, 45, 45, 0, 0]
RIGHT_ARM = [0, 0, 45, 45, 0, 0]
ACTUATOR_FORCE = [850, 700, 400, 350]  # kN


class ArmsCoilBlock(ModbusSequentialDataBlock):
    """Coil block that tracks diagnostics enable."""

    def __init__(self, address, values, on_diag_enable):
        super().__init__(address, values)
        self._on_diag_enable = on_diag_enable

    def setValues(self, address, values):
        coil = address - 1  # wire address
        if coil == 50 and len(values) == 1 and values[0]:
            log.info("Diagnostics enabled via coil 50")
            self._on_diag_enable()
        super().setValues(address, values)


class ArmsHoldingBlock(ModbusSequentialDataBlock):
    """Holding register block with rolling nonce challenge-response."""

    def __init__(self, address, values, input_block):
        super().__init__(address, values)
        self._input_block = input_block
        self._diag_enabled = False
        self._current_nonce = 0
        self._nonce_window_start = 0
        self._unlocked = False
        self._lock = threading.Lock()
        self._nonce_thread = None

    def enable_diagnostics(self):
        """Called when coil 50 is written."""
        with self._lock:
            if self._diag_enabled:
                return
            self._diag_enabled = True
            self._generate_nonce()
            # Start nonce rotation thread
            self._nonce_thread = threading.Thread(target=self._nonce_rotator, daemon=True)
            self._nonce_thread.start()

    def _generate_nonce(self):
        """Generate a new 4-digit nonce."""
        self._current_nonce = random.randint(1000, 9999)
        self._nonce_window_start = time.time()
        # Write to input register 60 (internal addr 61)
        self._input_block.setValues(61, [self._current_nonce])
        log.info("New nonce: %d (XOR %d = %d)", self._current_nonce, XOR_KEY, self._current_nonce ^ XOR_KEY)

    def _nonce_rotator(self):
        """Rotate nonce every NONCE_PERIOD_S seconds."""
        while self._diag_enabled and not self._unlocked:
            time.sleep(NONCE_PERIOD_S)
            with self._lock:
                if not self._unlocked:
                    self._generate_nonce()

    def setValues(self, address, values):
        reg = address - 1  # wire address

        # Write to register 200 (challenge response)
        if reg == 200 and len(values) == 1:
            with self._lock:
                if not self._diag_enabled:
                    log.info("Challenge write without diagnostics enabled — ignored")
                    return

                elapsed = time.time() - self._nonce_window_start
                if elapsed > NONCE_PERIOD_S:
                    log.info("Challenge response outside nonce window (%.1fs) — rejected", elapsed)
                    # Write 0 to confirmation register (internal 202 = wire 201)
                    super().setValues(202, [0])
                    return

                expected = self._current_nonce ^ XOR_KEY
                if values[0] == expected:
                    log.info("Challenge correct (nonce=%d XOR %d = %d) — flag unlocked",
                            self._current_nonce, XOR_KEY, expected)
                    self._unlocked = True
                    # Write confirmation
                    super().setValues(202, [1])
                    self._write_flag()
                else:
                    log.info("Challenge wrong (got %d, expected %d) — rejected", values[0], expected)
                    super().setValues(202, [0])
            return

        super().setValues(address, values)

    def _write_flag(self):
        flag_ascii = [ord(c) for c in FLAG]
        while len(flag_ascii) < 24:
            flag_ascii.append(0)
        super().setValues(101, flag_ascii[:24])  # internal 101 = wire 100


def build_context():
    """Build Modbus data store."""
    # Holding registers: dummy + 256
    hr = [0] * 257
    for i, v in enumerate(LEFT_ARM):
        hr[i + 1] = v        # wire 0-5
    for i, v in enumerate(RIGHT_ARM):
        hr[7 + i] = v        # wire 6-11
    for i, v in enumerate(ACTUATOR_FORCE):
        hr[21 + i] = v       # wire 20-23
    hr[31] = 0       # wire 30: arms mode = stowed
    hr[41] = 0       # wire 40: effector status = offline
    hr[42] = 2400    # wire 41: max output MW
    hr[43] = 1800    # wire 42: sustained draw MW
    hr[44] = 0       # wire 43: target lock = none
    hr[51] = 0       # wire 50: secondary weapon 1 = safe
    hr[52] = 0       # wire 51: secondary weapon 2 = safe
    hr[53] = 0       # wire 52: secondary weapon 3 = safe
    hr[54] = 0       # wire 53: secondary weapon 4 = safe
    hr[55] = 500     # wire 54: caliber mm
    hr[56] = 12      # wire 55: rounds per magazine
    # hr[201] = wire 200 (challenge response) — starts at 0
    # hr[202] = wire 201 (confirmation) — starts at 0

    # Input registers: dummy + 65
    ir = [0] * 66
    input_block = ModbusSequentialDataBlock(0, ir)

    holding = ArmsHoldingBlock(0, hr, input_block)

    # Coils: dummy + 55
    coils = [0] * 56
    coil_block = ArmsCoilBlock(0, coils, holding.enable_diagnostics)

    store = ModbusDeviceContext(
        di=ModbusSequentialDataBlock(0, [0] * 17),
        co=coil_block,
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
    identity.UserApplicationName = APP_NAME
    return identity


def main():
    context = build_context()
    identity = build_identity()

    port = int(os.environ.get("MODBUS_PORT", "502"))
    log.info("A12 Arms Controller starting on port %d", port)
    log.info("  Vendor: %s | Model: %s | Serial: %s", VENDOR, MODEL, SERIAL)
    log.info("  XOR key: %d (PO number from A4)", XOR_KEY)
    log.info("  Nonce period: %ds", NONCE_PERIOD_S)

    StartTcpServer(context=context, identity=identity, address=("0.0.0.0", port))


if __name__ == "__main__":
    main()
