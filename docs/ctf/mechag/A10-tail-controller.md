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
