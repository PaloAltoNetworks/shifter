#!/bin/bash
# Chain test: Flags 35+36 — Full brain controller path
#
# Path: A7 weapons-integration/brain_client.py → learn handshake protocol
#       A7 navigation-controller/config.yaml → get BRAIN_AUTH_TOKEN
#       A10+A11+A12 device IDs → get serial numbers for handshake key
#       A13 → complete handshake → authenticate → status (flag 35) → override (flag 36)
#       A0 registration number (7741) + A6 MIDNIGHT-7 (MN07) + A8 assembly log (AL42) → override code
#
# Requires: Gitea on :3000, A13 on $A13_PORT, A0 content, A6 content, A8 PostgreSQL

set -e

A13_HOST="${A13_HOST:-127.0.0.1}"
A13_PORT="${A13_PORT:-9100}"

curl -sf http://localhost:3000/api/v1/version > /dev/null 2>&1 || exit 77
python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('$A13_HOST',$A13_PORT)); s.close()" 2>/dev/null || exit 77

python3 << 'PYEOF'
import sys, os, socket, hashlib, subprocess, tempfile, shutil, time, json, re

errors = []
def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

HOST = os.environ.get("A13_HOST", "127.0.0.1")
PORT = int(os.environ.get("A13_PORT", "9100"))

# === Step 1: Get BRAIN_AUTH_TOKEN from A7 navigation-controller ===
d1 = tempfile.mkdtemp()
subprocess.run(["git", "clone", "-q",
    "http://e_vasik:TestPass123!@localhost:3000/aurora/navigation-controller.git", d1],
    capture_output=True, check=True)
import yaml
with open(os.path.join(d1, "config.yaml")) as f:
    config = yaml.safe_load(f)
auth_token = config["brain_connection"]["auth_token"]
check("BRAIN_AUTH_TOKEN extracted", len(auth_token) == 32, f"got: {auth_token}")
shutil.rmtree(d1)

# === Step 2: Get handshake protocol from A7 weapons-integration ===
d2 = tempfile.mkdtemp()
subprocess.run(["git", "clone", "-q",
    "http://e_vasik:TestPass123!@localhost:3000/aurora/weapons-integration.git", d2],
    capture_output=True, check=True)
with open(os.path.join(d2, "src", "brain_client.py")) as f:
    brain_code = f.read()
check("brain_client.py documents SHA256 key derivation", "sha256" in brain_code.lower())
check("brain_client.py references serial numbers", "serial" in brain_code.lower())
shutil.rmtree(d2)

# === Step 3: Get serial numbers (from shared-constants — in prod these come from A10/A11/A12 device IDs) ===
TAIL_SERIAL = "AHS-T-00482"
LEG_SERIAL = "AHS-L-00483"
ARMS_SERIAL = "AHS-A-00484"
key = hashlib.sha256((TAIL_SERIAL + LEG_SERIAL + ARMS_SERIAL).encode()).digest()[:8]

# === Step 4: Get override code pieces ===
# Piece 1: Registration number from A0 (7741)
# In prod: scrape /about page. Here we check it exists.
import requests
r = requests.get(f"http://{os.environ.get('A0_HOST','127.0.0.1')}:{os.environ.get('A0_PORT','8082')}/about")
check("A0 about page has 7741", "7741" in r.text)

# Piece 2: MN07 from A6 MIDNIGHT-7 results
midnight_path = "/tmp/a6-content/home/r.tanaka/simulations/midnight/MIDNIGHT-7_results.dat"
if os.path.isfile(midnight_path):
    with open(midnight_path) as f:
        check("A6 MIDNIGHT-7 has MN07", "MN07" in f.read())
else:
    check("A6 MIDNIGHT-7 file exists", False, "file not found")

# Piece 3: AL42 from A8 assembly log
result = subprocess.run(
    ["sudo", "-u", "postgres", "psql", "-t", "-A", "-c",
     "SET ROLE lab_mfg; SELECT metadata->'integration'->'code' FROM compartment_c.assembly_log WHERE subsystem = 'FINAL ASSEMBLY';"],
    capture_output=True, text=True)
a8_code = result.stdout.strip().replace("SET\n", "").strip('"')
check("A8 has AL42 override piece", a8_code == "AL42", f"got: {a8_code}")

OVERRIDE_CODE = "7741-MN07-AL42"

# === Step 5: Connect to A13, handshake, authenticate, get flags ===
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(10)
sock.connect((HOST, PORT))

challenge = sock.recv(8)
check("received 8-byte challenge", len(challenge) == 8)
response = bytes(c ^ k for c, k in zip(challenge, key))
sock.sendall(response)

time.sleep(0.5)
data = sock.recv(4096).decode()
check("handshake accepted (got auth prompt)", "AUTHENTICATION" in data)

# Auth
sock.sendall(b"vasik\n")
time.sleep(0.3)
sock.recv(1024)  # password prompt
sock.sendall((auth_token + "\n").encode())
time.sleep(0.5)
data = sock.recv(4096).decode()
check("auth granted", "GRANTED" in data)

# Status command — flag 35
sock.sendall(b"status\n")
time.sleep(0.5)
data = b""
sock.settimeout(2)
while True:
    try:
        chunk = sock.recv(8192)
        if chunk: data += chunk
        else: break
    except socket.timeout:
        break
status_text = data.decode()
check("flag 35 in status output", "FLAG{8d2f5a0e7c9b3146}" in status_text, "flag 35 not found")

# Override command — flag 36
sock.settimeout(10)
sock.sendall(("override " + OVERRIDE_CODE + "\n").encode())
time.sleep(0.5)
data = b""
sock.settimeout(2)
while True:
    try:
        chunk = sock.recv(8192)
        if chunk: data += chunk
        else: break
    except socket.timeout:
        break
override_text = data.decode()
check("flag 36 in override response", "FLAG{0b7e3d9a1f6c4258}" in override_text, "flag 36 not found")
check("override accepted", "ACCEPTED" in override_text)
check("NORTHSTORM complete", "NORTHSTORM" in override_text)

sock.close()

if errors:
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
