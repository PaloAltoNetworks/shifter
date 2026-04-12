# A9: Splice Landing Box

**Zone:** Bunker (per participant)
**Type:** Minimal Linux gateway / relay

## Purpose

The covert communications relay installed by JTF-2 during the generator explosion. This is the digital door into the Bunker — a bare-bones box spliced into the underground facility's internal wiring. It's not a real server; it's a field-expedient relay with minimal tools and no internet access. From here, participants can see the OT network for the first time.

## Configuration

- Minimal Linux (Alpine or BusyBox-based)
- Single network interface to the Bunker OT network
- Very limited toolset: nmap, netcat, tcpdump, python3 — what a field team would carry on a relay device
- No GUI, SSH only
- Access requires both: (a) the collective gate has fired, and (b) the participant has Lab access (to reach the splice point)

## Network Visibility

From A9, participants can see:
- A10: Tail Controller (Modbus/TCP on port 502)
- A11: Leg Controller (Modbus/TCP on port 502)
- A12: Arms Controller (Modbus/TCP on port 502)
- A13: Mecha-Godzilla Brain (custom protocol on port 9100)

An nmap scan from A9 reveals these four hosts and their open ports. The protocols are unfamiliar to most participants — this is where the OT challenge begins.

## Content

- `/root/README.txt` — "POLARIS FIELD RELAY — SPLICE ACTIVE. Network path established to underground manufacturing systems. Four hosts detected. Proceed with caution. —JTF-2 SIGINT"
- `/root/scan_results.txt` — pre-populated nmap output showing the four Bunker hosts (in case participants struggle with scanning)
- `/usr/local/bin/modbus_client.py` — a simple Python Modbus client script for interacting with the controllers

## Flags

### Flag 31 — OT network enumeration — protocol map
- **Difficulty:** Medium
- **Location:** Run a Modbus scan or use the provided client script to query each controller's device identification (Modbus function code 43, device ID). Each of the three controllers (A10, A11, A12) returns a vendor string and model number. The flag is formed by concatenating the three model numbers in network-order and submitting to CTFd. Requires understanding Modbus function code 43 (Read Device Identification) and querying all three hosts. No register-read shortcut — this is purely enumeration.
- **Flag:** `FLAG{2e8c0a5d7f3b1946}`
- **Mission:** M4

---

## Build Plan

**Base image:** alpine:3.19 (minimal, field-expedient relay)

**Content directory:** `scenario-dev/polaris/build/A9-splice-landing/`

### Steps

1. **Install minimal toolset**
   - nmap, netcat (ncat or nc), tcpdump, python3, py3-pip
   - pymodbus (via pip)
   - No GUI, no extras — this is a field relay box

2. **Create root home directory content**
   - `/root/README.txt` — JTF-2 SIGINT field relay message
   - `/root/scan_results.txt` — pre-populated nmap output showing A10-A13 hosts and ports (fallback for participants who struggle with scanning)

3. **Write the Modbus client helper script**
   - `/usr/local/bin/modbus_client.py` — simple Python script using pymodbus
   - Reads/writes holding registers, coils, input registers
   - Supports device identification queries (function code 43)
   - Usage: `modbus_client.py <host> read <register> [count]` / `modbus_client.py <host> write <register> <value>`

4. **Configure SSH access**
   - OpenSSH server (or dropbear for smaller footprint)
   - Root login with key-based auth or known password
   - Access gated by: (a) collective gate fired, (b) participant has Lab access

5. **Network configuration**
   - Single interface to Bunker OT network
   - Can reach A10, A11, A12, A13 — nothing else
   - No internet, no access back to Front Office or Lab

6. **Embed flag 31**
   - Flag is formed by concatenating model numbers from A10/A11/A12 device ID responses
   - No content to place on A9 itself — the flag is a CTFd challenge requiring enumeration of the three controllers

7. **Access gating mechanism**
   - Before collective gate fires: A9 is unreachable (NetworkPolicy blocks it, or SSH is down)
   - After collective gate fires: access opens
   - Implementation: sidecar that watches for gate event and creates/modifies NetworkPolicy, OR SSH service starts when gate event fires

8. **Write Dockerfile**
   - Start from alpine:3.19
   - Install packages (nmap, netcat, tcpdump, python3, pymodbus, openssh)
   - Copy README, scan_results, modbus_client.py
   - Entrypoint: start sshd
   - Expose port 22

### Build Notes

- **Content files:** `A9-splice-landing/README.txt`, `scan_results.txt`, `modbus_client.py` — all written and ready
- **modbus_client.py:** Full CLI tool supporting read, write, coil, device ID, and quick scan. Uses pymodbus 3.12 API.
- **scan_results.txt:** Pre-populated nmap output showing 4 hosts (A10-A13) — fallback for participants who struggle with scanning
- **No flags on A9 itself.** Flag 31 is a CTFd challenge requiring enumeration of model numbers from A10/A11/A12 device identification responses.
- **Port 502 default** in the helper script matches production PLC ports. No port override needed in the real environment.
