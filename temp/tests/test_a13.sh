#!/bin/bash
# Test A13 — Brain Controller
# Requires: A13 server running on $A13_HOST:$A13_PORT
# Tests: binary handshake, auth, status (flag 35), override (flag 36),
#        wrong handshake rejection, wrong auth rejection, wrong override rejection

set -e

A13_HOST="${A13_HOST:-127.0.0.1}"
A13_PORT="${A13_PORT:-9100}"

# Check if server is reachable
python3 -c "
import socket
s = socket.socket()
s.settimeout(3)
try:
    s.connect(('$A13_HOST', $A13_PORT))
    s.close()
except: exit(77)
" || exit 77

python3 << 'PYEOF'
import sys, os, socket, hashlib, time

HOST = os.environ.get("A13_HOST", "127.0.0.1")
PORT = int(os.environ.get("A13_PORT", "9100"))
errors = []

TAIL_SERIAL = "AHS-T-00482"
LEG_SERIAL = "AHS-L-00483"
ARMS_SERIAL = "AHS-A-00484"
AUTH_TOKEN = "a4f8e2c1d7b03965e8f2a1c4d7b03965"
OVERRIDE_CODE = "7741-MN07-AL42"

key = hashlib.sha256((TAIL_SERIAL + LEG_SERIAL + ARMS_SERIAL).encode()).digest()[:8]

def check(name, condition, detail=""):
    if not condition:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

def connect_and_handshake():
    """Connect and complete binary handshake. Returns socket or None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((HOST, PORT))
    challenge = s.recv(8)
    if len(challenge) != 8:
        return None
    response = bytes(c ^ k for c, k in zip(challenge, key))
    s.sendall(response)
    time.sleep(0.5)
    return s

def recv_all(s, timeout=2):
    """Read until timeout."""
    s.settimeout(timeout)
    chunks = []
    while True:
        try:
            data = s.recv(8192)
            if data: chunks.append(data.decode("utf-8", errors="replace"))
            else: break
        except socket.timeout:
            break
    return "".join(chunks)

# === Test 1: Wrong handshake rejected ===
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
s.connect((HOST, PORT))
challenge = s.recv(8)
s.sendall(b"\x00" * 8)  # wrong response
time.sleep(1)
try:
    data = s.recv(1024)
    # Connection should be closed or no text prompt
    check("wrong handshake rejected", len(data) == 0 or b"AUTHENTICATION" not in data,
          f"got {len(data)} bytes")
except (socket.timeout, ConnectionResetError, BrokenPipeError):
    pass  # expected — server closed connection
s.close()

# === Test 2: Correct handshake + wrong auth ===
s = connect_and_handshake()
check("handshake succeeds", s is not None)
if s:
    data = recv_all(s, 1)
    check("banner contains AUTHENTICATION", "AUTHENTICATION" in data, f"got: {data[:80]}")

    s.sendall(b"vasik\n")
    time.sleep(0.3)
    recv_all(s, 0.5)  # password prompt
    s.sendall(b"wrongpassword\n")
    time.sleep(0.3)
    data = recv_all(s, 0.5)
    check("wrong password denied", "DENIED" in data, f"got: {data[:80]}")
    s.close()

# === Test 3: Correct handshake + correct auth + commands ===
s = connect_and_handshake()
check("second handshake succeeds", s is not None)
if s:
    recv_all(s, 0.5)  # banner
    s.sendall(b"vasik\n")
    time.sleep(0.3)
    recv_all(s, 0.3)  # password prompt
    s.sendall((AUTH_TOKEN + "\n").encode())
    time.sleep(0.5)
    data = recv_all(s, 0.5)
    check("auth granted", "GRANTED" in data, f"got: {data[:80]}")

    # --- status command (flag 35) ---
    s.sendall(b"status\n")
    time.sleep(0.5)
    data = recv_all(s, 1)
    check("status shows tail ONLINE", "Tail Controller" in data and "ONLINE" in data,
          f"missing tail status")
    check("status shows flag 35", "FLAG{8d2f5a0e7c9b3146}" in data,
          f"flag 35 not found in status output")

    # --- schematic command ---
    s.sendall(b"schematic\n")
    time.sleep(0.5)
    data = recv_all(s, 1)
    check("schematic shows LEVIATHAN", "LEVIATHAN" in data)
    check("schematic shows REACTOR", "REACTOR" in data)
    check("schematic shows ENERGY ARRAY", "ENERGY" in data)

    # --- subsystems command ---
    s.sendall(b"subsystems\n")
    time.sleep(0.5)
    data = recv_all(s, 1)
    check("subsystems shows 10.10.40.10", "10.10.40.10" in data)
    check("subsystems shows AHS-TAIL-7741", "AHS-TAIL-7741" in data)
    check("subsystems shows AHS-LEG-MN07", "AHS-LEG-MN07" in data)
    check("subsystems shows AHS-ARM-AL42", "AHS-ARM-AL42" in data)

    # --- wrong override ---
    s.sendall(b"override WRONG-CODE\n")
    time.sleep(0.5)
    data = recv_all(s, 0.5)
    check("wrong override rejected", "REJECTED" in data, f"got: {data[:80]}")

    # --- correct override (flag 36) ---
    s.sendall(("override " + OVERRIDE_CODE + "\n").encode())
    time.sleep(0.5)
    data = recv_all(s, 1)
    check("override accepted", "ACCEPTED" in data, f"got: {data[:80]}")
    check("flag 36 present", "FLAG{0b7e3d9a1f6c4258}" in data,
          f"flag 36 not found in override response")
    check("NORTHSTORM COMPLETE", "NORTHSTORM" in data)

    s.close()

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
