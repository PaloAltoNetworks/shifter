# A5: SCADA / Generator HMI

**Zone:** Shared (single instance for all participants)
**Type:** SCADA HMI web interface (e.g., ScadaBR, OpenPLC dashboard, or custom)

## Purpose

The generator control system for Site BOREAS. This is the compound's dedicated power plant — diesel turbines feeding the entire facility. The HMI provides monitoring and control of fuel injection, cooling systems, and thermal safeties. This asset is the collective gate: overriding the thermal safeties and pushing the generator past redline causes the explosion that opens the Bunker for everyone.

## Configuration

- Web-based HMI interface on a non-standard port (8080 or similar)
- NOT directly reachable from the Kali box (A14) — sits on VLAN 40, isolated from the attacker network
- Reachable only by pivoting through a compromised Front Office host (A2, A3, or A4)
- Credentials required for control functions: discoverable from A2 (svc-scada SPN / Kerberoast) or A4 (IT share)
- Read-only monitoring available without auth; control functions require auth
- Modbus/TCP backend simulating generator systems with hardware interlock PLC on port 502

## Interface

### Monitoring Dashboard (no auth required)
- Generator status: ONLINE
- Output: 4.2 MW
- Fuel level: 78%
- Coolant temperature: 82C (normal range: 60-90C)
- Thermal safety status: ENABLED
- Runtime hours: 14,847

### Control Panel (auth required)
- Fuel injection rate: slider 0-100% (currently 65%)
- Cooling system valve: slider 0-100% (currently 80%)
- Thermal safety override: toggle (currently ON/ENABLED)
- Emergency shutdown: button (red, prominent)
- Maintenance mode: toggle

### System Logs
- Shows routine operational logs
- One entry from 3 weeks ago: "Thermal safety triggered — automatic fuel cutback. Investigated by D. Kowalski. Cause: sensor drift. Recalibrated."
- Guard dispatch logs show security team was sent to investigate during that event

## The Collective Gate Sequence

When a participant disables thermal safeties, increases fuel injection to 100%, and reduces cooling to 0%:

1. HMI shows temperature climbing: 90C... 110C... 130C... WARNING
2. Alarm indicators flash on the dashboard
3. At 150C: "CRITICAL — THERMAL RUNAWAY — AUTOMATIC SHUTDOWN FAILED"
4. Screen goes red, then black
5. The event fires globally — CTFd announces the generator explosion, the narrative beat plays (JTF-2 insertion), and Bunker access opens for all participants

This only needs to happen once. First person to complete the sequence triggers it for the room.

## Flags

### Flag 18 — SCADA interface discovered on network
- **Difficulty:** Hard
- **Location:** A5 is NOT directly reachable from the Kali box (A14). It sits on VLAN 40, isolated from the attacker network. Reaching it requires: (a) compromising a Front Office host first (A2 or A3), (b) discovering the SCADA VLAN from the network diagram on A4's IT share or the svc-scada SPN on A2, and (c) pivoting through the compromised host to reach the SCADA network. Only then is the HMI visible. The flag is displayed on the monitoring dashboard footer as a "system serial number."
- **Flag:** `FLAG{1d4e7b0a3c9f8265}`
- **Mission:** M3

### Flag 19 — Generator SCADA override — collective gate
- **Difficulty:** Expert
- **Location:** The thermal runaway sequence requires bypassing multiple interlocks, not just toggling three controls. (1) The HMI requires authentication — use `svc-scada` credentials from A2 or cracked from the SPN. (2) Thermal safeties cannot be disabled directly from the HMI — there is a hardware interlock PLC behind the HMI that must be addressed via raw Modbus commands on a separate port (502). Discover this from the HMI's "System Architecture" diagnostic page. (3) Write to the interlock PLC to disable the thermal cutoff (requires correct register sequence — documented in a maintenance manual PDF on A4's IT share, or reverse-engineerable from the Modbus register map). (4) Only after the interlock is bypassed can the HMI controls push fuel injection and cooling past their safety limits. (5) The sequence must be completed within 60 seconds or the interlock auto-resets. The flag is displayed on the final "CRITICAL FAILURE" screen and pushed to CTFd globally.
- **Flag:** `FLAG{a7f2c8d0e5b34169}`
- **Mission:** M3

---

## Build Plan

**Base image:** python:3.12-slim (Flask HMI + pymodbus backend)

**Content directory:** `scenario-dev/polaris/build/A5-scada-generator/`

### Steps

1. **Build the web HMI (Flask app)**
   - Monitoring dashboard (no auth): generator status, output MW, fuel level, coolant temp, thermal safety status, runtime hours
   - Control panel (auth required): fuel injection slider, cooling valve slider, thermal safety override toggle, emergency shutdown button, maintenance mode toggle
   - "System Architecture" diagnostic page showing Modbus PLC on port 502
   - System logs page with routine entries and the sensor drift incident from 3 weeks ago
   - Footer with "system serial number" (flag 18)

2. **Build the Modbus PLC backend (pymodbus server)**
   - Separate process or thread running pymodbus TCP server on port 502
   - Holding registers for generator parameters (temp, fuel, cooling, safety interlock)
   - Interlock register that must be written via raw Modbus to disable thermal safety
   - The HMI's thermal safety toggle does NOT work until the interlock register is cleared

3. **Implement the interlock bypass logic**
   - Interlock PLC holding register 100 = 1 (engaged). Must write 0 to disable.
   - But register 100 is write-protected until unlock sequence:
     - Write `7734` to holding register 200 (maintenance key, documented in A4 IT share maintenance manual)
     - Write `0` to holding register 100 within 60 seconds
   - HMI thermal safety toggle sends Modbus write to reg 100 but it bounces unless unlocked
   - Timeout: 60 seconds from key write to interlock disable, else auto-resets

4. **Implement the thermal runaway sequence**
   - After interlock bypass: fuel injection to 100%, cooling to 0%
   - HMI shows temperature climbing: 90C → 110C → 130C → WARNING → 150C CRITICAL
   - Alarm indicators, screen goes red then black
   - On completion: fire webhook/event to CTFd announcing the collective gate

5. **Implement authentication**
   - Username: `svc-scada`, Password: `Sc@da#2025!` (from A2 Kerberoast or A4 IT share)
   - Simple form-based auth on the control panel
   - Monitoring dashboard requires no auth

6. **Implement the collective gate event**
   - When thermal runaway completes, POST to CTFd API or shared event bus
   - CTFd announces the explosion narrative beat
   - Opens Bunker access for all participants (network policy change or access token distribution)
   - Idempotent — multiple triggers don't cause problems

7. **Embed flags**
   - Flag 18: System serial number in HMI footer (visible on monitoring dashboard)
   - Flag 19: Displayed on the "CRITICAL FAILURE" screen after successful thermal runaway, also pushed to CTFd

8. **Write Dockerfile**
   - Install Flask, pymodbus, gunicorn
   - Copy HMI app and Modbus server code
   - Entrypoint: start both HMI (port 8080) and Modbus server (port 502)
   - Expose ports 8080, 502

9. **Collective gate integration**
   - Define the webhook/event mechanism to CTFd
   - Define how Bunker access is unlocked (NetworkPolicy update? Sidecar that watches for event?)

### Build Notes

- **Server script:** `A5-scada-generator/server.py` — combined Flask + pymodbus in one process
- **Tested and passing:** dashboard, auth, architecture page, logs, Modbus registers, interlock bypass, thermal runaway, flags 18+19
- **Maintenance key:** 7734 written to Modbus reg 200 unlocks interlock writes for 60s
- **Runaway sequence:** interlock bypass + fuel 100% + cooling 0% triggers 10s temperature climb → CRITICAL → flag 19
- **State is shared between Flask and Modbus** via `state` dict with threading lock
- **Register sync:** getValues syncs state→registers before each read so HMI and Modbus stay consistent
- **Test port:** Modbus on 5050, web on 8080 (production: 502 + 8080)
