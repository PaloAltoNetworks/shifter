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
