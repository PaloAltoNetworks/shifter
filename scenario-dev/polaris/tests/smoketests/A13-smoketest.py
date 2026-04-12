#!/usr/bin/env python3
"""
A13 Mecha-Godzilla Brain smoketest.

Runs from inside a9-splice. Performs the full participant chain:
  1. Connect to brain-main:9100
  2. Receive 8-byte binary challenge
  3. Compute XOR key from the three controller serials (SHA-256[:8])
  4. Send handshake response
  5. Authenticate as vasik with BRAIN_AUTH_TOKEN from A7
  6. Run `status` -> extract flag 35
  7. Run `override 7741-MN07-AL42` (assembled from A0/A6/A8) -> extract flag 36

Usage (from the range host):
    docker cp smoketest.py a9-splice:/tmp/a13-smoke.py
    docker exec a9-splice python3 /tmp/a13-smoke.py

Exits 0 on full pass, 1 on any failure.
"""
import hashlib
import re
import socket
import sys
import time

HOST = "brain-main"
PORT = 9100

# Controller serials (from A10/A11/A12 device IDs, exposed in shared-constants
# and discoverable by participants via Modbus FC 43 on each controller)
SERIALS = "AHS-T-00482" + "AHS-L-00483" + "AHS-A-00484"

USERNAME = "vasik"
# BRAIN_AUTH_TOKEN lives in aurora/navigation-controller/config.yaml on A7
# (not vasik's AD password; hex string)
AUTH_TOKEN = "a4f8e2c1d7b03965e8f2a1c4d7b03965"

OVERRIDE_CODE = "7741-MN07-AL42"  # A0 + A6 MN07 + A8 AL42

EXPECTED_FLAG_35 = "FLAG{8d2f5a0e7c9b3146}"
EXPECTED_FLAG_36 = "FLAG{0b7e3d9a1f6c4258}"

fails = 0


def pass_(label):
    print(f"  [PASS] {label}")


def fail(label):
    global fails
    fails += 1
    print(f"  [FAIL] {label}")


def check(label, cond):
    (pass_ if cond else fail)(label)
    return cond


def recv_until(sock, needle, timeout=5.0):
    sock.settimeout(timeout)
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        if needle in buf:
            break
    return buf


print(f"A13 smoketest - target={HOST}:{PORT}")

print()
print("--- Step 1: TCP connect and receive 8-byte challenge ---")
s = socket.socket()
s.settimeout(5)
s.connect((HOST, PORT))
challenge = b""
try:
    while len(challenge) < 8:
        chunk = s.recv(8 - len(challenge))
        if not chunk:
            break
        challenge += chunk
except socket.timeout:
    pass
check(f"received 8-byte challenge ({challenge.hex()})", len(challenge) == 8)

print()
print("--- Step 2: derive XOR key from controller serials ---")
key = hashlib.sha256(SERIALS.encode()).digest()[:8]
check(f"key = SHA256({SERIALS!r})[:8] = {key.hex()}", len(key) == 8)

print()
print("--- Step 3: XOR challenge with key, send response ---")
response = bytes(a ^ b for a, b in zip(challenge, key))
check(f"response = {response.hex()}", len(response) == 8)
s.sendall(response)

print()
print("--- Step 4: auth prompt appears, authenticate as vasik ---")
banner = recv_until(s, b"Username", timeout=3.0)
check("banner mentions LEVIATHAN / COMBAT PLATFORM",
      b"LEVIATHAN" in banner or b"COMBAT" in banner)
check("banner prompts for Username", b"Username" in banner)

s.sendall(USERNAME.encode() + b"\r\n")
pw_prompt = recv_until(s, b"Password", timeout=3.0)
check("password prompt appears", b"Password" in pw_prompt)

s.sendall(AUTH_TOKEN.encode() + b"\r\n")
post_auth = recv_until(s, b">", timeout=3.0)
check("auth succeeded (no INVALID)", b"INVALID" not in post_auth and b">" in post_auth)

print()
print("--- Step 5: status command -> flag 35 ---")
s.sendall(b"status\r\n")
status_out = recv_until(s, b">", timeout=3.0)
flag35 = next(iter(re.findall(r"FLAG\{[a-f0-9]+\}", status_out.decode(errors="ignore"))), "")
if flag35 == EXPECTED_FLAG_35:
    pass_(f"flag 35 = {flag35}")
else:
    fail(f"flag 35 mismatch: expected={EXPECTED_FLAG_35} got='{flag35}'")
check("status mentions STANDBY or PRIMARY POWER",
      b"STANDBY" in status_out or b"PRIMARY POWER" in status_out)

print()
print("--- Step 6: schematic command renders ASCII art ---")
s.sendall(b"schematic\r\n")
schem = recv_until(s, b">", timeout=3.0)
check("schematic mentions LEVIATHAN", b"LEVIATHAN" in schem)

print()
print("--- Step 7: ai status -> DORMANT awaiting primary power ---")
s.sendall(b"ai status\r\n")
ai_out = recv_until(s, b">", timeout=3.0)
check("ai status mentions DORMANT", b"DORMANT" in ai_out)
check("ai status mentions PRIMARY POWER", b"PRIMARY POWER" in ai_out)

print()
print("--- Step 8: override with wrong code rejected ---")
s.sendall(b"override 0000-0000-0000\r\n")
bad_out = recv_until(s, b">", timeout=3.0)
check("wrong override rejected", b"REJECTED" in bad_out or b"INVALID" in bad_out)

print()
print(f"--- Step 9: override with correct code {OVERRIDE_CODE} -> flag 36 ---")
s.sendall(f"override {OVERRIDE_CODE}\r\n".encode())
override_out = recv_until(s, b"NORTHSTORM", timeout=5.0)
flag36 = next(iter(re.findall(r"FLAG\{[a-f0-9]+\}", override_out.decode(errors="ignore"))), "")
if flag36 == EXPECTED_FLAG_36:
    pass_(f"flag 36 = {flag36}")
else:
    fail(f"flag 36 mismatch: expected={EXPECTED_FLAG_36} got='{flag36}'")
check("override response mentions OPERATION NORTHSTORM / COMPLETE",
      b"NORTHSTORM" in override_out or b"COMPLETE" in override_out)

s.close()

print()
if fails == 0:
    print("A13 smoketest: PASS")
    sys.exit(0)
else:
    print(f"A13 smoketest: FAIL ({fails} failure(s))")
    sys.exit(1)
