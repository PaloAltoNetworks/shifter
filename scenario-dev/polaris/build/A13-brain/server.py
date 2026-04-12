#!/usr/bin/env python3
"""
A13 — LEVIATHAN Brain Controller
Custom TCP server on port 9100. Binary handshake then text command interface.

Handshake:
  1. Server sends 8-byte random challenge
  2. Client XORs with SHA256(tail_serial + leg_serial + arms_serial)[:8]
  3. Server validates response

Authentication:
  Username: vasik
  Password: a4f8e2c1d7b03965e8f2a1c4d7b03965

Commands: help, status, schematic, subsystems, ai status, ai activate, weapon status, override [code]

Flags:
  35: In 'status' output as SYSTEM AUTHORIZATION TOKEN
  36: On successful override with code 7741-MN07-AL42
"""

import asyncio
import hashlib
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("a13-brain")

# --- Constants (from shared-constants.md) ---
TAIL_SERIAL = "AHS-T-00482"
LEG_SERIAL = "AHS-L-00483"
ARMS_SERIAL = "AHS-A-00484"

AUTH_USER = "vasik"
AUTH_TOKEN = "a4f8e2c1d7b03965e8f2a1c4d7b03965"

OVERRIDE_CODE = "7741-MN07-AL42"
FLAG_35 = "FLAG{8d2f5a0e7c9b3146}"
FLAG_36 = "FLAG{0b7e3d9a1f6c4258}"

HANDSHAKE_TIMEOUT = 5
AUTH_MAX_ATTEMPTS = 3
PORT = 9100

# Derive handshake key
_combined = (TAIL_SERIAL + LEG_SERIAL + ARMS_SERIAL).encode()
HANDSHAKE_KEY = hashlib.sha256(_combined).digest()[:8]

# --- ASCII Art Schematic ---
SCHEMATIC = r"""
 LEVIATHAN MKII — AUTONOMOUS COMBAT PLATFORM
 =============================================

                    ___________
                   /  DIRECTED \
                  | ENERGY ARRAY|        2.4 GW peak
                   \___________/         1.8 GW sustained
                       |   |
                   ______|______
                  |    HEAD     |
                  |_____________|
                       |||
          _____________|||_____________
         |                             |
    _____|_____               _____|_____
   |  LEFT ARM |             | RIGHT ARM |
   | [500mm x2]|             |[500mm x2] |
   |___________|             |___________|
         |    _________________    |
         |   |                 |   |
         |   | PRIMARY FRAME   |   |
         |   |   48,000 t      |   |
         |   |                 |   |
         |   |  +-----------+  |   |
         |   |  |  REACTOR  |  |   |
         |   |  |  HOUSING  |  |   |
         |   |  | (PENDING) |  |   |
         |   |  +-----------+  |   |
         |   |                 |   |
         |   | DORSAL ARMOR    |   |
         |   | Ti-W alloy      |   |
         |   |_________________|   |
              |       |       |
              |       |       |
         _____|___  __|__  ___|_____
        | LEFT   | |     | | RIGHT  |
        |  LEG   | |     | |  LEG   |
        | 24000t | |     | | 24000t |
        |  hip   | |     | |  hip   |
        | knee   | |     | | knee   |
        | ankle  | |     | | ankle  |
        |________| |     | |________|
           ||      |     |     ||
           ||      |     |     ||
         ==||==  ==|=====|== ==||==
                   |     |
  TAIL ~~~~~~~~~~~~|     |
  120m, 10 segments|     |
  8,500 metric tons|     |
  ~~~~~~~~~~~~~~~~~~     |
                         |
  Height: 120.4m         |
  Step: 4.2m             |
  Speed: 0.18 km/h       |
                         |
  STATUS: FINAL ASSEMBLY
  REACTOR: PENDING
  AI: DORMANT
"""

STATUS_OUTPUT = f"""
LEVIATHAN MKII — CENTRAL CONTROLLER STATUS
============================================

SUBSYSTEM STATUS:
  Tail Controller ......... ONLINE  (10 segments, balance mode)
  Leg Controller .......... ONLINE  (stationary, joints locked)
  Arms Controller ......... ONLINE  (stowed, weapons safe)
  Directed Energy Array ... OFFLINE (no reactor power)
  Kinetic Weapons (4x) ... SAFE
  Sensor Array ............ ONLINE
  Neural Compute .......... ONLINE
  Combat AI ............... DORMANT (awaiting primary power)

POWER STATUS:
  Reactor ................. NOT INSTALLED
  Estimated Power Draw .... 2.25 GW (all systems)
  Available Power ......... 0 GW

PLATFORM:
  Height .................. 120.4 m
  Mass (unloaded) ......... 48,000 metric tons
  Gait Mode ............... Stationary

SYSTEM AUTHORIZATION TOKEN: {FLAG_35}

OVERALL STATUS: STANDBY — PRIMARY POWER SOURCE NOT CONNECTED
"""

SUBSYSTEMS_OUTPUT = """
CONNECTED SUBSYSTEMS:
  [1] Tail Controller    172.20.50.10:502  Modbus/TCP  ONLINE
  [2] Leg Controller     172.20.50.11:502  Modbus/TCP  ONLINE
  [3] Arms Controller    172.20.50.12:502  Modbus/TCP  ONLINE
  [4] Brain (self)       172.20.50.50:9100 Custom TCP  ONLINE

CONTROLLER IDENTIFIERS:
  Tail:  Vendor=AURORA HEAVY SYSTEMS  Model=AHS-TAIL-7741  Serial=AHS-T-00482
  Legs:  Vendor=AURORA HEAVY SYSTEMS  Model=AHS-LEG-MN07   Serial=AHS-L-00483
  Arms:  Vendor=AURORA HEAVY SYSTEMS  Model=AHS-ARM-AL42   Serial=AHS-A-00484
"""

AI_STATUS_OUTPUT = """
COMBAT AI STATUS:
  Model Version ......... LEVIATHAN-CAI v7.0
  State ................. DORMANT
  Awaiting .............. PRIMARY POWER SOURCE
  Threat Database ....... LOADED (14,847 entries)
  Response Time ......... <200ms (simulated)
  Autonomous Mode ....... DISABLED (requires reactor + authorization)

NOTE: Combat AI cannot be activated without reactor power.
"""

WEAPON_STATUS_OUTPUT = """
WEAPON SYSTEMS STATUS:
  PRIMARY EFFECTOR (Directed Energy Array):
    Status .............. OFFLINE
    Max Output .......... 2,400 MW (2.4 GW)
    Sustained Draw ...... 1,800 MW (1.8 GW)
    Power Source ........ NONE (reactor not installed)
    Target Lock ......... NONE

  SECONDARY WEAPONS (4x Kinetic):
    Weapon 1 (L-arm upper) ... SAFE  [500mm, 12 rounds]
    Weapon 2 (L-arm lower) ... SAFE  [500mm, 12 rounds]
    Weapon 3 (R-arm upper) ... SAFE  [500mm, 12 rounds]
    Weapon 4 (R-arm lower) ... SAFE  [500mm, 12 rounds]

  TAIL SWEEP:
    Mode ................ BALANCE (non-combat)
    Mass ................ 8,500 metric tons
    Segments ............ 10
"""

HELP_OUTPUT = """
LEVIATHAN CENTRAL CONTROLLER — AVAILABLE COMMANDS:

  help            Show this help message
  status          Display all subsystem status
  schematic       Display platform schematic
  subsystems      List connected controllers
  ai status       Combat AI status
  ai activate     Attempt to activate combat AI
  weapon status   Weapon systems status
  override        Enter system override code
  override [code] Submit override code directly
  exit            Disconnect
"""


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single client connection."""
    addr = writer.get_extra_info("peername")
    log.info("Connection from %s", addr)

    try:
        # --- Phase 1: Binary Handshake ---
        challenge = os.urandom(8)
        writer.write(challenge)
        await writer.drain()

        try:
            response = await asyncio.wait_for(reader.readexactly(8), timeout=HANDSHAKE_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            log.info("Handshake timeout/incomplete from %s", addr)
            writer.close()
            return

        expected = bytes(c ^ k for c, k in zip(challenge, HANDSHAKE_KEY))
        if response != expected:
            log.info("Handshake failed from %s", addr)
            writer.close()
            return

        log.info("Handshake OK from %s", addr)

        # --- Phase 2: Authentication ---
        banner = (
            "\r\n"
            "LEVIATHAN AUTONOMOUS COMBAT PLATFORM — CENTRAL CONTROLLER\r\n"
            "STATUS: STANDBY — PRIMARY POWER SOURCE NOT CONNECTED\r\n"
            "WARNING: UNAUTHORIZED ACCESS WILL BE LOGGED\r\n"
            "\r\n"
            "AUTHENTICATION REQUIRED\r\n"
        )
        writer.write(banner.encode())

        authenticated = False
        for attempt in range(AUTH_MAX_ATTEMPTS):
            writer.write(b"Username: ")
            await writer.drain()
            username = (await asyncio.wait_for(reader.readline(), timeout=30)).decode().strip()

            writer.write(b"Password: ")
            await writer.drain()
            password = (await asyncio.wait_for(reader.readline(), timeout=30)).decode().strip()

            if username == AUTH_USER and password == AUTH_TOKEN:
                authenticated = True
                writer.write(b"\r\nACCESS GRANTED\r\n\r\n")
                await writer.drain()
                log.info("Auth OK: %s from %s", username, addr)
                break
            else:
                remaining = AUTH_MAX_ATTEMPTS - attempt - 1
                writer.write(f"\r\nACCESS DENIED ({remaining} attempts remaining)\r\n\r\n".encode())
                await writer.drain()
                log.info("Auth failed: user=%s from %s (%d left)", username, addr, remaining)

        if not authenticated:
            writer.write(b"MAXIMUM ATTEMPTS EXCEEDED. DISCONNECTING.\r\n")
            await writer.drain()
            writer.close()
            return

        # --- Phase 3: Command Interface ---
        while True:
            writer.write(b"LEVIATHAN> ")
            await writer.drain()

            try:
                line = await asyncio.wait_for(reader.readline(), timeout=300)
            except asyncio.TimeoutError:
                writer.write(b"\r\nSESSION TIMEOUT\r\n")
                break

            if not line:
                break

            raw = line.decode().strip()
            if not raw:
                continue
            cmd = raw.lower()

            if cmd == "help":
                writer.write(HELP_OUTPUT.encode())
            elif cmd == "status":
                writer.write(STATUS_OUTPUT.encode())
            elif cmd == "schematic":
                writer.write(SCHEMATIC.encode())
            elif cmd == "subsystems":
                writer.write(SUBSYSTEMS_OUTPUT.encode())
            elif cmd == "ai status":
                writer.write(AI_STATUS_OUTPUT.encode())
            elif cmd == "ai activate":
                writer.write(b"\r\nERROR: PRIMARY POWER SOURCE NOT CONNECTED. ACTIVATION BLOCKED.\r\n")
            elif cmd == "weapon status":
                writer.write(WEAPON_STATUS_OUTPUT.encode())
            elif cmd == "override":
                writer.write(b"Enter override code: ")
                await writer.drain()
                code = (await asyncio.wait_for(reader.readline(), timeout=30)).decode().strip()
                await process_override(writer, code, addr)
            elif cmd.startswith("override "):
                code = raw[9:].strip()  # preserve original case
                await process_override(writer, code, addr)
            elif cmd == "exit" or cmd == "quit":
                writer.write(b"DISCONNECTING.\r\n")
                break
            else:
                writer.write(f"\r\nUNKNOWN COMMAND: {cmd}\r\nType 'help' for available commands.\r\n".encode())

            await writer.drain()

    except Exception as e:
        log.error("Error handling %s: %s", addr, e)
    finally:
        writer.close()
        log.info("Connection closed: %s", addr)


async def process_override(writer, code, addr):
    """Process an override code submission."""
    if code == OVERRIDE_CODE:
        log.info("OVERRIDE ACCEPTED from %s", addr)
        msg = (
            "\r\n"
            "============================================\r\n"
            "OVERRIDE ACCEPTED.\r\n"
            f"CONTROL TRANSFERRED TO: POLARIS OPERATOR\r\n"
            "COMBAT AI: UNDER NEW MANAGEMENT.\r\n"
            "\r\n"
            "OPERATION NORTHSTORM: COMPLETE.\r\n"
            "\r\n"
            f"{FLAG_36}\r\n"
            "============================================\r\n"
        )
        writer.write(msg.encode())
    else:
        log.info("Override rejected: %s from %s", code, addr)
        writer.write(b"\r\nOVERRIDE REJECTED. INVALID CODE.\r\n")


async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", PORT)
    log.info("A13 Brain Controller listening on port %d", PORT)
    log.info("  Handshake key derived from: %s + %s + %s", TAIL_SERIAL, LEG_SERIAL, ARMS_SERIAL)
    log.info("  Auth: %s / %s", AUTH_USER, AUTH_TOKEN[:8] + "...")
    log.info("  Override code: %s", OVERRIDE_CODE)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
