#!/usr/bin/env python3
"""
A10 — Tail Controller
Modbus/TCP server simulating the tail articulation PLC for PROJECT LEVIATHAN.

pymodbus 3.12+ API.

Registers:
  Holding 0-9:   Motor positions (degrees) for 10 tail segments
  Holding 10-19: Torque readings (kN-m) per segment
  Holding 20:    Tail mode (0=stowed, 1=balance, 2=combat, 3=diagnostic)
  Holding 21:    Total tail length (meters) = 120
  Holding 22:    Tail mass (metric tons) = 8500
  Coil 30-39:    Motor enable per segment
  Holding 99:    Challenge-response register
  Holding 100-115: Flag registers (zeros until unlocked)

Device Identification:
  Vendor:  AURORA HEAVY SYSTEMS
  Model:   AHS-TAIL-7741
  Serial:  AHS-T-00482

Flag 32 unlock:
  1. Write 3 to register 20 (diagnostic mode)
  2. Write 482 to register 99 (serial-derived challenge)
  3. Registers 100-115 return FLAG as ASCII
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
log = logging.getLogger("a10-tail")

# --- Constants ---
VENDOR = "AURORA HEAVY SYSTEMS"
MODEL = "AHS-TAIL-7741"
SERIAL = "AHS-T-00482"
PRODUCT_CODE = "TAIL-10SEG-MK2"
APP_NAME = "Tail Articulation Controller v2.4 -- maintenance mode: write reg 20=3"

SERIAL_CHALLENGE = 482
FLAG = "FLAG{9b3e7c1d0f5a2846}"
DIAG_TIMEOUT_S = 30

MOTOR_POSITIONS = [45, 38, 30, 22, 15, 10, 8, 5, 3, 1]
TORQUE_VALUES = [1200, 1100, 1000, 900, 850, 800, 750, 700, 600, 500]


class TailDataBlock(ModbusSequentialDataBlock):
    """Custom holding register block with flag unlock logic."""

    def __init__(self, address, values):
        super().__init__(address, values)
        self._diag_mode_time = None
        self._unlocked = False
        self._lock = threading.Lock()

    def setValues(self, address, values):
        """Intercept writes for flag unlock logic.

        Note: ModbusDeviceContext.setValues adds +1 to address before
        calling us, so wire address 20 arrives here as 21.
        """
        reg = address - 1  # convert back to wire address

        # Write to register 20 (tail mode)
        if reg == 20 and len(values) == 1:
            if values[0] == 3:
                with self._lock:
                    self._diag_mode_time = time.time()
                    log.info("Diagnostic mode requested — awaiting challenge on reg 99")
            else:
                with self._lock:
                    self._diag_mode_time = None
            super().setValues(address, values)
            return

        # Write to register 99 (challenge-response)
        if reg == 99 and len(values) == 1:
            with self._lock:
                if self._diag_mode_time is not None:
                    elapsed = time.time() - self._diag_mode_time
                    if elapsed > DIAG_TIMEOUT_S:
                        log.info("Challenge too late (%.1fs) — reset", elapsed)
                        self._diag_mode_time = None
                        # Reset mode back to balance (internal addr = wire + 1)
                        super().setValues(21, [1])
                    elif values[0] == SERIAL_CHALLENGE:
                        log.info("Challenge correct — flag unlocked")
                        self._unlocked = True
                        self._diag_mode_time = None
                        self._write_flag()
                    else:
                        log.info("Challenge wrong (got %d, want %d) — reset", values[0], SERIAL_CHALLENGE)
                        self._diag_mode_time = None
                        super().setValues(21, [1])
                else:
                    log.info("Challenge write without diagnostic mode — ignored")
            return

        super().setValues(address, values)

    def _write_flag(self):
        flag_ascii = [ord(c) for c in FLAG]
        # Pad to 24 registers (flag is 22 chars)
        while len(flag_ascii) < 24:
            flag_ascii.append(0)
        # Internal address = wire address + 1
        super().setValues(101, flag_ascii[:24])


def build_context():
    """Build Modbus data store with initial values.

    Note: ModbusDeviceContext.setValues/getValues adds +1 to the wire address
    before accessing the data block. So wire address 0 = block index 1.
    We prepend a dummy value at index 0 so that hr[N+1] = wire address N.
    """
    # Holding registers: prepend dummy + 256 entries
    hr = [0] * 257  # index 0 is dummy, index 1 = wire addr 0
    for i, pos in enumerate(MOTOR_POSITIONS):
        hr[i + 1] = pos    # wire addr 0-9
    for i, torque in enumerate(TORQUE_VALUES):
        hr[11 + i] = torque  # wire addr 10-19
    hr[21] = 1     # wire addr 20: mode = balance
    hr[22] = 120   # wire addr 21: tail length meters
    hr[23] = 8500  # wire addr 22: tail mass metric tons

    holding = TailDataBlock(0, hr)

    # Coils: prepend dummy + 50 entries
    coils = [0] * 51
    for i in range(30, 40):
        coils[i + 1] = 1  # wire addr 30-39

    store = ModbusDeviceContext(
        di=ModbusSequentialDataBlock(0, [0] * 17),
        co=ModbusSequentialDataBlock(0, coils),
        hr=holding,
        ir=ModbusSequentialDataBlock(0, [0] * 65),  # need at least up to wire addr 60
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

    log.info("A10 Tail Controller starting on port 502")
    log.info("  Vendor: %s | Model: %s | Serial: %s", VENDOR, MODEL, SERIAL)
    log.info("  Flag unlock: reg 20=3, then reg 99=%d", SERIAL_CHALLENGE)

    port = int(os.environ.get("MODBUS_PORT", "502"))
    StartTcpServer(context=context, identity=identity, address=("0.0.0.0", port))


if __name__ == "__main__":
    main()
