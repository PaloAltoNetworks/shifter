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
