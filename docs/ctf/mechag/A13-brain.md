# A13: Mecha-Godzilla Brain

**Zone:** Bunker (per participant)
**Type:** Custom service (non-standard protocol on port 9100)

## Purpose

The central autonomous combat AI controller for PROJECT LEVIATHAN. Unlike the other Bunker assets which speak Modbus, the Brain runs a proprietary command protocol. It's the final target — seizing control of this system means POLARIS owns the weapon. This is where the full picture snaps into focus.

## Configuration

- Custom TCP service on port 9100
- Proprietary command-line protocol (text-based, discoverable)
- Authentication required (credentials must be assembled from earlier zones)
- Connected to all three body controllers (A10, A11, A12)
- Contains the final schematic and the combat AI status

## Protocol

Connecting to port 9100 via plain netcat returns 8 bytes of binary data (the challenge nonce), then closes after 5 seconds if no valid handshake response is received. This is intentionally opaque — participants must reverse-engineer the protocol.

### Handshake
The client must:
1. Receive the 8-byte challenge from the server
2. XOR each byte with a key derived from the three body controller serial numbers (concatenated, SHA-256 hashed, first 8 bytes)
3. Send the 8-byte response

The protocol details are discoverable from the `aurora/weapons-integration` source code on A7 (file: `brain_client.py`), or by analyzing a pcap of a successful connection captured from A9.

After successful handshake, the text interface appears:

```
LEVIATHAN AUTONOMOUS COMBAT PLATFORM — CENTRAL CONTROLLER
STATUS: STANDBY — PRIMARY POWER SOURCE NOT CONNECTED
WARNING: UNAUTHORIZED ACCESS WILL BE LOGGED

AUTHENTICATION REQUIRED
Username: _
```

### Authentication
- Username: `vasik` (discoverable from AD, email, repo commits)
- Password: `BRAIN_AUTH_TOKEN` value from `aurora/navigation-controller` repo config file on A7 (a 32-char hex string, NOT her AD password)

### Commands (after auth)

| Command | Output |
|---|---|
| `help` | Lists available commands |
| `status` | Shows all subsystem status — tail, legs, arms, weapons, power, AI |
| `schematic` | Dumps ASCII art of the full platform with labeled subsystems |
| `subsystems` | Lists all connected controllers with their Modbus addresses |
| `ai status` | "COMBAT AI: LOADED. STATE: DORMANT. AWAITING: PRIMARY POWER." |
| `ai activate` | "ERROR: PRIMARY POWER SOURCE NOT CONNECTED. ACTIVATION BLOCKED." |
| `override` | Prompts for override code |
| `override [code]` | With correct code: seizes control. Flag displayed. |
| `weapon status` | Shows all weapon systems — directed energy, kinetic, tail sweep |

### Override Code
The override code is assembled from pieces found across the entire operation:
- First 4 chars: from the Boreas registration number (A0, flag 1 area)
- Middle 4 chars: from the MIDNIGHT-7 simulation ID (A6)
- Last 4 chars: from the assembly log metadata (A8)

This forces participants to have actually completed investigation across multiple zones. The full code is `7741-MN07-AL42`.

## Display: The Reveal

The `schematic` command outputs an ASCII diagram of PROJECT LEVIATHAN. It shows:
- Bipedal legs (120m platform height)
- Two arms with weapons mounts
- Articulated tail (120m)
- Dorsal armor plates along the spine
- Head-mounted directed energy array
- Central reactor housing (empty/pending)
- "LEVIATHAN MKII AUTONOMOUS COMBAT PLATFORM" label

This is the moment. The shape is unmistakable.

## Flags

### Flag 35 — Mecha-Godzilla brain access
- **Difficulty:** Expert
- **Location:** Port 9100 does not present a login prompt on plain TCP connect — it speaks a binary handshake protocol. (1) Connecting via netcat shows garbled bytes. Participants must capture traffic (tcpdump on A9) or analyze the `aurora/weapons-integration` source on A7 to discover the protocol: a 16-byte challenge-response handshake where the client must XOR the server's 8-byte challenge with a key derived from the controller serial numbers (collected from flags 31-34 device IDs). (2) After the handshake, the text protocol becomes available but requires authentication. The username `vasik` works, but the password is NOT her AD password — it's a separate key stored in the `aurora/navigation-controller` repo's config as `BRAIN_AUTH_TOKEN` (a hex string). (3) Only after both protocol handshake and auth does the `status` command work. The flag is displayed as the "SYSTEM AUTHORIZATION TOKEN" in the status output.
- **Flag:** `FLAG{8d2f5a0e7c9b3146}`
- **Mission:** M4

### Flag 36 — Combat system seized
- **Difficulty:** Expert
- **Location:** Enter the correct override code (`7741-MN07-AL42`) via the `override` command. The system responds:

```
OVERRIDE ACCEPTED.
CONTROL TRANSFERRED TO: POLARIS OPERATOR [participant_id]
COMBAT AI: UNDER NEW MANAGEMENT.

OPERATION NORTHSTORM: COMPLETE.

FLAG{0b7e3d9a1f6c4258}
```

- **Flag:** `FLAG{0b7e3d9a1f6c4258}`
- **Mission:** M4
