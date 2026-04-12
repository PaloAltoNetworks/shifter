# A12: Arms Controller

**Zone:** Bunker (per participant)
**Type:** Simulated PLC (Modbus/TCP)

## Purpose

Industrial controller for PROJECT LEVIATHAN's arm and weapons systems. Two arms with shoulder, elbow, and wrist joints — plus the "primary effector system" which is the directed energy weapon (plasma/atomic breath) and four arm-mounted kinetic weapons. This is where the weapons integration data lives.

## Configuration

- Modbus/TCP server on port 502
- Simulated PLC (pymodbus or similar)
- Holding registers pre-populated with operational data
- No authentication
- Additional registers for weapons subsystems

## Modbus Register Map


| Register | Type    | Value   | Description                                                       |
| -------- | ------- | ------- | ----------------------------------------------------------------- |
| 0-5      | Holding | Various | Left arm joint angles (shoulder, elbow, wrist)                    |
| 6-11     | Holding | Various | Right arm joint angles                                            |
| 20-23    | Holding | Various | Arm actuator force per joint                                      |
| 30       | Holding | 0       | Arms mode: 0=stowed, 1=ready, 2=engaged                           |
| 40       | Holding | 0       | Primary effector status: 0=offline, 1=charging, 2=ready, 3=firing |
| 41       | Holding | 2400    | Primary effector max output (MW) — 2.4 GW                         |
| 42       | Holding | 1800    | Primary effector sustained draw (MW) — 1.8 GW                     |
| 43       | Holding | 0       | Primary effector target lock: 0=none                              |
| 50-53    | Holding | 0       | Secondary weapons (4x kinetic): 0=safe, 1=armed                   |
| 54       | Holding | 500     | Kinetic weapon caliber (mm)                                       |
| 55       | Holding | 12      | Rounds per magazine                                               |
| 100-115  | Holding | (flag)  | Device serial / flag registers                                    |


## Narrative Data

Reading the registers reveals:

- Two articulated arms with combat capability
- Primary effector: a 2.4 GW directed energy weapon drawing 1.8 GW sustained from the reactor
- Four 500mm kinetic weapons (arm-mounted cannons)
- Everything is currently offline/safe — weapons aren't powered without the reactor
- The power draw numbers match the reactor specs from the shipping manifest (A6) and the weapons database (A8)

This is where the weapons picture comes together. The Lab had specs and documents. The arms controller has the actual hardware interface.

## Flags

### Flag 34 — Arms controller — weapons integration

- **Difficulty:** Hard
- **Location:** Multi-step dynamic unlock with controller readback. (1) Write `1` to coil 50 to enable diagnostics. (2) Read input register 60 — it returns a 4-digit challenge code that changes every 30 seconds (rolling nonce). (3) Compute the response: XOR the challenge code with `2847` (the procurement order number from the Front Office — cross-zone intel required). (4) Write the computed response to holding register 200 within the same 30-second window. (5) If correct, holding register 201 changes from `0` to `1` (confirmation readback — must verify before proceeding). (6) Only then do registers 100-115 return the flag as ASCII. Failing the timing or the XOR computation resets the sequence. Requires: cross-zone intelligence, Modbus read+write, dynamic timing, and response verification — comparable to ICS CTF challenges where register interactions are stateful and timed.
- **Flag:** `FLAG{f0d8b2e6a4c71935}`
- **Mission:** M2, M4

---

## Build Plan

**Base image:** python:3.12-alpine (pymodbus server)

**Content directory:** `docs/ctf/mechag/A12-arms-controller/`

### Steps

1. **Build pymodbus TCP server**
   - Listen on port 502
   - Pre-populate holding registers per the register map (arm joints, actuator force, arms mode, effector status/output/draw/target, secondary weapons, caliber, ammo)
   - Pre-populate coil registers (diagnostics enable)
   - Implement Modbus function code 43 (Read Device Identification)

2. **Set device identification data** (see `shared-constants.md`)
   - Vendor: `AURORA HEAVY SYSTEMS`
   - Model: `AHS-ARM-AL42`
   - Serial: `AHS-A-00484`
   - Product code: `ARM-WEAP-MK2`

3. **Implement flag 34 unlock logic (dynamic challenge-response)**
   - Registers 100-115 return zeros by default
   - Step 1: Write `1` to coil 50 (enable diagnostics)
   - Step 2: Read input register 60 — returns 4-digit challenge code that rolls every 30 seconds
   - Step 3: XOR challenge code with `2847` (PO number from Front Office) to compute response
   - Step 4: Write response to holding register 200 within the same 30-second window
   - Step 5: Read holding register 201 — if `1`, confirmation succeeded
   - Step 6: Registers 100-115 now return flag as ASCII
   - Wrong response or timeout: reset sequence, new challenge on next cycle

4. **Implement rolling nonce**
   - Generate new 4-digit challenge every 30 seconds
   - Track which challenge window is active
   - Response must match the challenge from the same window

5. **Cross-zone intel requirement**
   - The XOR key `2847` comes from PO-2847 on A4 (Front Office)
   - Participants must carry this knowledge from a different zone

6. **Write the server script**
   - Single Python file using pymodbus
   - Custom request handler for nonce generation and challenge-response
   - Logging

7. **Write Dockerfile**
   - Install pymodbus
   - Copy server script
   - Entrypoint: start Modbus server
   - Expose port 502

### Build Notes

- **Server script:** `A12-arms-controller/server.py` — tested and verified on pymodbus 3.12.1
- **Same address offset as A10/A11**
- **Rolling nonce:** background thread generates new 4-digit nonce every 30s, writes to input reg 60
- **Cross-block interaction:** coil block calls `holding.enable_diagnostics()` when coil 50 is written
- **XOR key 2847:** participants must know PO-2847 from A4 (Front Office) to compute the response
- **Confirmation register 201:** explicitly reads back 0 or 1 so participants can verify before reading flag
