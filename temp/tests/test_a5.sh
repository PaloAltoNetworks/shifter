#!/bin/bash
# Test A5 — SCADA Generator HMI + Modbus PLC
# Requires: A5 server running (Web on $A5_WEB_PORT, Modbus on $A5_MODBUS_PORT)
# Tests:
#   - Monitoring dashboard accessible without auth, contains flag 18
#   - Control panel requires auth
#   - Architecture page reveals Modbus on port 502
#   - System logs accessible
#   - Modbus registers readable
#   - Interlock write protected without maintenance key
#   - Maintenance key unlocks interlock
#   - Thermal runaway sequence produces flag 19
#   - Auth with svc-scada credentials works

set -e

A5_HOST="${A5_HOST:-127.0.0.1}"
A5_WEB_PORT="${A5_WEB_PORT:-8080}"
A5_MODBUS_PORT="${A5_MODBUS_PORT:-5050}"

# Check if web server is reachable
curl -sf "http://${A5_HOST}:${A5_WEB_PORT}/" > /dev/null 2>&1 || exit 77

python3 << 'PYEOF'
import sys, os, time, requests
from pymodbus.client import ModbusTcpClient

HOST = os.environ.get("A5_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("A5_WEB_PORT", "8080"))
MODBUS_PORT = int(os.environ.get("A5_MODBUS_PORT", "5050"))
BASE_URL = f"http://{HOST}:{WEB_PORT}"
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

# === Web HMI Tests ===
# Dashboard (no auth)
r = requests.get(f"{BASE_URL}/")
check("dashboard accessible (200)", r.status_code == 200, f"status={r.status_code}")
check("flag 18 in dashboard footer", "FLAG{1d4e7b0a3c9f8265}" in r.text, "flag not in page")
check("dashboard shows generator data", "4.2 MW" in r.text or "ONLINE" in r.text, "no generator data")

# Architecture page (no auth)
r = requests.get(f"{BASE_URL}/architecture")
check("architecture page accessible", r.status_code == 200)
check("architecture reveals Modbus port 502", "port 502" in r.text or "502" in r.text)
check("architecture shows register map", "HR 100" in r.text or "register" in r.text.lower())

# Logs page
r = requests.get(f"{BASE_URL}/logs")
check("logs page accessible", r.status_code == 200)
check("logs mention sensor drift incident", "sensor drift" in r.text.lower() or "Kowalski" in r.text)

# Control panel requires auth
r = requests.get(f"{BASE_URL}/control", allow_redirects=False)
check("control panel redirects to login", r.status_code in (302, 303), f"status={r.status_code}")

# Login with correct creds
sess = requests.Session()
r = sess.post(f"{BASE_URL}/login", data={"username": "svc-scada", "password": "Sc@da#2025!"})
check("login succeeds", r.status_code == 200, f"status={r.status_code}")

r = sess.get(f"{BASE_URL}/control")
check("control panel accessible after login", r.status_code == 200 and "CONTROL PANEL" in r.text.upper(),
      f"status={r.status_code}")

# Login with wrong creds
r = requests.post(f"{BASE_URL}/login", data={"username": "admin", "password": "wrong"})
check("wrong login rejected", "Invalid" in r.text or "invalid" in r.text.lower())

# === Modbus PLC Tests ===
c = ModbusTcpClient(HOST, port=MODBUS_PORT)
check("Modbus connection", c.connect())

# Read generator status registers
r = c.read_holding_registers(address=0, count=6)
check("generator online", r.registers[0] == 1, f"status={r.registers[0]}")
check("output ~4.2MW", r.registers[1] == 42, f"got {r.registers[1]}")
check("fuel level 78%", r.registers[2] == 78, f"got {r.registers[2]}")
check("coolant temp ~82C", r.registers[3] == 82, f"got {r.registers[3]}")
check("thermal safety enabled", r.registers[4] == 1, f"got {r.registers[4]}")

# Interlock engaged
r = c.read_holding_registers(address=100, count=1)
check("interlock engaged", r.registers[0] == 1, f"got {r.registers[0]}")

# Interlock write without key — should be rejected
c.write_register(address=100, value=0)
time.sleep(0.3)
r = c.read_holding_registers(address=100, count=1)
check("interlock write rejected without key", r.registers[0] == 1, f"got {r.registers[0]}")

# Maintenance key → interlock bypass
c.write_register(address=200, value=7734)
time.sleep(0.3)
c.write_register(address=100, value=0)
time.sleep(0.3)
r = c.read_holding_registers(address=100, count=1)
check("interlock bypassed with key", r.registers[0] == 0, f"got {r.registers[0]}")

# Thermal safety should now be disabled
r = c.read_holding_registers(address=4, count=1)
check("thermal safety disabled after interlock bypass", r.registers[0] == 0, f"got {r.registers[0]}")

# Trigger thermal runaway: fuel 100%, cooling 0%
c.write_register(address=10, value=100)
c.write_register(address=11, value=0)

# Wait for runaway sequence (~12 seconds)
time.sleep(14)

# Check flag 19 on web dashboard
r = requests.get(f"{BASE_URL}/")
check("flag 19 on destroyed dashboard", "FLAG{a7f2c8d0e5b34169}" in r.text, "flag 19 not in page")
check("dashboard shows CRITICAL", "CRITICAL" in r.text or "THERMAL RUNAWAY" in r.text)

c.close()

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
