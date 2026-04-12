# A11: Leg Controller

**Zone:** Bunker (per participant)
**Type:** Simulated PLC (Modbus/TCP)

## Purpose

Industrial controller for PROJECT LEVIATHAN's bipedal locomotion system. Controls hydraulic actuators for two legs — hip, knee, and ankle joints on each. The register data describes a walking machine. Joint angles, hydraulic pressures, and gait cycle parameters paint a picture of something enormous taking steps.

## Configuration

- Modbus/TCP server on port 502
- Simulated PLC (pymodbus or similar)
- Holding registers pre-populated with operational data
- No authentication

## Modbus Register Map

| Register | Type | Value | Description |
|---|---|---|---|
| 0-5 | Holding | Various | Left leg joint angles (hip, knee, ankle: position, target) |
| 6-11 | Holding | Various | Right leg joint angles (hip, knee, ankle: position, target) |
| 20-25 | Holding | Various | Hydraulic pressure per joint (MPa) |
| 30 | Holding | 0 | Gait mode: 0=stationary, 1=walk, 2=run, 3=combat stance |
| 31 | Holding | 4200 | Step length (mm) — 4.2 meter stride |
| 32 | Holding | 85 | Step cycle time (seconds per step) |
| 33 | Holding | 24000 | Per-leg mass (metric tons) |
| 34 | Holding | 200 | Max actuator force (tons) — matches PO-2847 from A4 |
| 100-115 | Holding | (flag) | Device serial / flag registers |

## Narrative Data

Reading the registers reveals:
- Bipedal system — two legs, three joints each
- Each leg masses 24,000 metric tons
- Hydraulic actuators rated for 200 tons of force (matches the procurement orders found in the Front Office)
- 4.2-meter stride length at walking speed
- Currently in "stationary" mode — the legs are built but the machine isn't walking yet
- The gait cycle math implies a platform roughly 120m tall (stride length / leg ratio)

## Flags

### Flag 33 — Leg joint actuator data
- **Difficulty:** Hard
- **Location:** Different unlock mechanism from A10. The leg controller uses a timed sequence: (1) write the gait mode register (30) through a specific sequence of values (0→1→2→0) within 10 seconds — simulating a calibration walk cycle. This sequence is documented in the `deploy_combat_ai.yml` Ansible playbook on A7, under a "pre-flight leg calibration" task. (2) After the correct sequence, input register 60 changes from 0 to a 4-digit code. (3) Write that code to holding register 99. (4) Registers 100-115 unlock with the flag. Requires reading OT process logic, performing timed Modbus writes, and reading back a dynamic value — a materially different skill from A10's static challenge-response.
- **Flag:** `FLAG{c7a1e3f9d0b52864}`
- **Mission:** M2, M4

---

## Build Plan

**Base image:** python:3.12-alpine (pymodbus server)

**Content directory:** `scenario-dev/polaris/build/A11-leg-controller/`

### Steps

1. **Build pymodbus TCP server**
   - Listen on port 502
   - Pre-populate holding registers per the register map (joint angles, hydraulic pressures, gait mode, step length, cycle time, mass, actuator force)
   - Implement Modbus function code 43 (Read Device Identification)

2. **Set device identification data** (see `shared-constants.md`)
   - Vendor: `AURORA HEAVY SYSTEMS`
   - Model: `AHS-LEG-MN07`
   - Serial: `AHS-L-00483`
   - Product code: `LEG-BIPED-MK2`
   - Calibration code (written to input reg 60 after sequence): `4783` (static per instance)

3. **Implement flag 33 unlock logic (timed sequence)**
   - Registers 100-115 return zeros by default
   - Step 1: Write gait mode register (30) through sequence 0→1→2→0 within 10 seconds
   - Step 2: After correct sequence, input register 60 changes from 0 to a 4-digit code
   - Step 3: Write that code to holding register 99
   - On correct sequence: registers 100-115 return flag as ASCII
   - Wrong sequence, wrong code, or timeout: reset everything

4. **Implement timed state machine**
   - Track sequence state: idle / step1 (wrote 1) / step2 (wrote 2) / step3 (wrote 0) / code-presented / unlocked
   - 10-second window for the 0→1→2→0 sequence
   - Code in input register 60 only valid for N seconds after sequence completes
   - Once unlocked, stays unlocked

5. **Calibration sequence source**
   - The 0→1→2→0 sequence is documented in `deploy_combat_ai.yml` on A7 under "pre-flight leg calibration"
   - Participants must find this in the Lab before they can unlock the flag

6. **Write the server script**
   - Single Python file using pymodbus
   - Custom request handler for timed stateful logic
   - Logging

7. **Write Dockerfile**
   - Install pymodbus
   - Copy server script
   - Entrypoint: start Modbus server
   - Expose port 502

### Build Notes

- **Server script:** `A11-leg-controller/server.py` — tested and verified on pymodbus 3.12.1
- **Same address offset as A10:** prepend dummy value at index 0, internal addr = wire addr + 1
- **Timed sequence state machine:** tracks 0→1→2→0 progression, resets on wrong value or timeout
- **Input register 60:** written by the holding block (cross-block write via reference to input_block)
- **Calibration code 4783:** static per instance, written to input reg 60 only after correct sequence
