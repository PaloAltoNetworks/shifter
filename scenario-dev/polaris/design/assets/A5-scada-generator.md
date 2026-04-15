# A5: SCADA / Generator HMI

**Zone:** SCADA (per participant)
**Type:** SCADA HMI web interface (e.g., ScadaBR, OpenPLC dashboard, or custom)

## Purpose

The generator control system for Site BOREAS. This is the compound's dedicated power plant — diesel turbines feeding the entire facility. The HMI provides monitoring and control of fuel injection, cooling systems, and thermal safeties. This asset is the splice trigger: overriding the thermal safeties and pushing the generator past redline causes the meltdown that lets the participant's Polaris VM activate the local A14 -> A9 splice.

## Configuration

- Web-based HMI interface on TCP 8080
- NOT directly reachable from the Kali box (A14) — sits on VLAN 40, isolated from the attacker network
- Reachable only by pivoting through **A15 (Ops Engineer Workstation)** — the only Front Office asset multi-homed onto the SCADA VLAN. Previous design had A3 filling this role; that was topologically indefensible and is corrected by A15.
- Credentials required for control functions: discovered from `/root/.scada/hmi.json` on A15 (readable only after achieving root via the A15 sudo-arg-injection chain — see A15 spec and flag 37). The legacy A4 `service_account_vault.pdf` source is removed as part of the A15 change so `svc-scada` is single-sourced through A15.
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

## The Splice Trigger Sequence

When a participant disables thermal safeties, increases fuel injection to 100%, and reduces cooling to 0%:

1. HMI shows temperature climbing: 90C... 110C... 130C... WARNING
2. Alarm indicators flash on the dashboard
3. At 150C: "CRITICAL — THERMAL RUNAWAY — AUTOMATIC SHUTDOWN FAILED"
4. Screen goes red, then black
5. A durable local failure state is exposed from A5. The participant's Polaris VM observes it, the narrative beat plays (JTF Polaris uses the blackout window to establish the splice), and the host locally enables A14 -> A9 for that range

This is per-range, not global. Every participant must earn the meltdown in their own range. CTFd challenge unlocks can happen independently of the network splice.

## Flags

### Flag 18 — Control Room
- **Difficulty:** Hard
- **Location:** A5 is NOT directly reachable from the Kali box (A14). It sits on VLAN 40, isolated from the attacker network. Reaching it requires **prior compromise of A15 (flag 37)** — A15 is the only Front Office host multi-homed onto the scada VLAN. The flag 18 chain is: earn A15 root via the chain in A15's spec → discover the SCADA VLAN from the network diagram on A4's IT share or from A15's own Flask Ops Telemetry dashboard → fetch the HMI from inside the A15 shell. The flag is displayed on the monitoring dashboard footer as a "system serial number."
- **Flag:** `FLAG{1d4e7b0a3c9f8265}`
- **Mission:** Mission 4 — Lights Out
- **Prerequisite flag:** 37 (A15 privesc)

### Flag 19 — Lights Out
- **Difficulty:** Expert
- **Location:** The thermal runaway sequence requires bypassing multiple interlocks, not just toggling three controls. (1) The HMI requires authentication — `svc-scada` credentials come from `/root/.scada/hmi.json` on A15 (requires flag 37 privesc). (2) Thermal safeties cannot be disabled directly from the HMI — there is a hardware interlock PLC behind the HMI that must be addressed via raw Modbus commands on a separate port (502). Discover this from the HMI's "System Architecture" diagnostic page. (3) Write to the interlock PLC to disable the thermal cutoff (requires the vendor maintenance key `7734`, documented in `generator_maintenance_manual.pdf` on A4's IT share). (4) Only after the interlock is bypassed can the HMI controls push fuel injection and cooling past their safety limits. (5) The sequence must be completed within the interlock timeout window or the interlock auto-resets. The flag is displayed on the final "CRITICAL FAILURE" screen, and the same meltdown state is what the Polaris VM watches to activate the local splice. Executed from inside the A15 shell using the preinstalled `pymodbus`.
- **Flag:** `FLAG{a7f2c8d0e5b34169}`
- **Mission:** Mission 4 — Lights Out
- **Prerequisite flag:** 37 (A15 privesc)

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
   - On completion: emit a durable local "meltdown complete" signal that the Polaris VM can observe

5. **Implement authentication**
   - Username: `svc-scada`, Password: `Sc@da#2025!` (single-sourced from `/root/.scada/hmi.json` on A15 after the flag 37 privesc)
   - Simple form-based auth on the control panel
   - Monitoring dashboard requires no auth

6. **Implement the local splice trigger**
   - When thermal runaway completes, persist a local signal on the range host or expose a container state transition that survives page refreshes
   - The participant's Polaris VM watches that signal and performs the local network mutation needed for A14 to reach A9
   - CTFd challenge gating remains separate from the range-side splice
   - Idempotent — repeated triggers do not rewire or flap the range

7. **Embed flags**
   - Flag 18: System serial number in HMI footer (visible on monitoring dashboard)
   - Flag 19: Displayed on the "CRITICAL FAILURE" screen after successful thermal runaway; the same state also drives the local splice trigger

8. **Write Dockerfile**
   - Install Flask, pymodbus, gunicorn
   - Copy HMI app and Modbus server code
   - Entrypoint: start both HMI (port 8080) and Modbus server (port 502)
   - Expose ports 8080, 502

9. **Local splice integration**
   - Define the durable state signal exposed by A5 on successful meltdown
   - Define the host-side watcher on the Polaris VM that observes that signal and enables A14 -> A9
   - Avoid a direct dependency on CTFd for range networking

### Build Notes

- **Server script:** `A5-scada-generator/server.py` — combined Flask + pymodbus in one process
- **Tested and passing:** dashboard, auth, architecture page, logs, Modbus registers, interlock bypass, thermal runaway, flags 18+19
- **Maintenance key:** 7734 written to Modbus reg 200 unlocks interlock writes for 60s
- **Runaway sequence:** interlock bypass + fuel 100% + cooling 0% triggers 10s temperature climb → CRITICAL → flag 19
- **State is shared between Flask and Modbus** via `state` dict with threading lock
- **Register sync:** getValues syncs state→registers before each read so HMI and Modbus stay consistent
- **Test port:** Modbus on 5050, web on 8080 (production: 502 + 8080)
