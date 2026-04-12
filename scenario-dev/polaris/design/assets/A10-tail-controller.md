# A10: Tail Controller

**Zone:** Bunker (per participant)
**Type:** Simulated PLC (Modbus/TCP)

## Purpose

Industrial controller for PROJECT LEVIATHAN's tail assembly. Controls the motor systems that drive tail articulation — stabilization during movement and a kinetic weapon capability (tail sweep). The Modbus registers tell the story: holding registers contain motor positions, torque values, and operational parameters for something that is clearly not industrial manufacturing equipment.

## Configuration

- Modbus/TCP server on port 502
- Simulated PLC (pymodbus or similar)
- Holding registers pre-populated with operational data
- No authentication (realistic for OT — Modbus has no auth)
- Coil registers control motor enable/disable

## Modbus Register Map

| Register | Type | Value | Description |
|---|---|---|---|
| 0-9 | Holding | Various | Motor positions (degrees) for 10 tail segments |
| 10-19 | Holding | Various | Torque readings (kN-m) per segment |
| 20 | Holding | 1 | Tail mode: 0=stowed, 1=balance, 2=combat |
| 21 | Holding | 120 | Total tail length (meters) |
| 22 | Holding | 8500 | Tail mass (metric tons) |
| 30-39 | Coil | ON | Motor enable per segment |
| 100 | Holding | (flag) | Device serial / flag register |

## Narrative Data

Reading the registers reveals:
- 10 individually articulated tail segments
- Combined length: 120 meters
- Mass: 8,500 metric tons
- Current mode: "balance" — the tail is actively counterbalancing something
- Torque values are enormous — these motors move something with the mass of a naval destroyer

## Flags

### Flag 32 — Tail motor controller data
- **Difficulty:** Hard
- **Location:** Registers 100-115 return zeros by default. To unlock them: (1) set the tail mode register (20) to value `3` (a diagnostic/maintenance mode not listed in the standard mode table — discoverable from a maintenance comment string in the device identification response, or from the manufacturing-orchestrator Ansible playbooks on A7). (2) Then write the controller's own serial number (from device ID query in flag 31) to holding register 99 as a challenge-response. (3) Only then do registers 100-115 return the flag as ASCII. Requires chaining OT enumeration knowledge from flag 31 with write operations and out-of-band information from the Lab.
- **Flag:** `FLAG{9b3e7c1d0f5a2846}`
- **Mission:** M2, M4

---

## Build Plan

**Base image:** python:3.12-alpine (pymodbus server)

**Content directory:** `scenario-dev/polaris/build/A10-tail-controller/`

### Steps

1. **Build pymodbus TCP server**
   - Listen on port 502
   - Pre-populate holding registers per the register map (motor positions, torque, mode, length, mass)
   - Pre-populate coil registers (motor enables)
   - Implement Modbus function code 43 (Read Device Identification) returning vendor string and model number

2. **Set device identification data** (see `shared-constants.md`)
   - Vendor: `AURORA HEAVY SYSTEMS`
   - Model: `AHS-TAIL-7741`
   - Serial: `AHS-T-00482`
   - Product code: `TAIL-10SEG-MK2`
   - User application name: `Tail Articulation Controller v2.4 — maintenance mode: write reg 20=3`

3. **Implement flag 32 unlock logic**
   - Registers 100-115 return zeros by default
   - Step 1: Write value `3` to holding register 20 (tail mode → diagnostic/maintenance)
   - Step 2: Write integer derived from serial `AHS-T-00482` → use `482` (last 3 digits as int) to holding register 99
   - On correct sequence: registers 100-115 return `FLAG{9b3e7c1d0f5a2846}` as ASCII character codes
   - On incorrect value in reg 99: reset mode to previous value, registers stay zeros
   - Timeout: 30 seconds from mode 3 write to reg 99 write, else auto-reset

4. **Implement state machine**
   - Track current state: normal / diagnostic-pending / unlocked
   - Timeout: if register 99 not written within N seconds of mode change, reset
   - Once unlocked, stays unlocked for the session

5. **Write the server script**
   - Single Python file using pymodbus
   - Custom request handler for the stateful flag logic
   - Logging for debugging

6. **Write Dockerfile**
   - Install pymodbus
   - Copy server script
   - Entrypoint: start Modbus server
   - Expose port 502

### Build Notes

- **Server script:** `A10-tail-controller/server.py` — tested and verified on pymodbus 3.12.1
- **pymodbus 3.12 address quirk:** `ModbusDeviceContext.setValues` adds +1 to the wire address before calling the data block. Must prepend a dummy value at index 0 in the register array so wire address N maps to array index N+1.
- **Flag is 22 chars** — need 24 registers (100-123) not just 16
- **Port 502 requires root** — use 5020 for testing, 502 in container (runs as root)
- **Device identification** works via `ReadDeviceInformationRequest(read_code=1)` — returns vendor, product code, revision. `UserApplicationName` contains the diagnostic mode hint but requires `read_code=3` (extended) or `read_code=4` (all) to retrieve.
