#!/usr/bin/env python3
"""
A5 — SCADA Generator HMI + Modbus PLC Backend
Combined Flask web HMI and pymodbus interlock PLC.

Web HMI (port 8080):
  /              — Monitoring dashboard (no auth)
  /control       — Control panel (requires svc-scada auth)
  /architecture  — System architecture page (reveals Modbus on 502)
  /logs          — System logs
  /login         — Login form
  /api/status    — JSON API for dashboard data

Modbus PLC (port 5050 for testing, 502 in production):
  Holding 0:   Generator status (1=online)
  Holding 1:   Output MW (42 = 4.2 MW)
  Holding 2:   Fuel level percent (78)
  Holding 3:   Coolant temperature C (82)
  Holding 4:   Thermal safety (1=enabled, 0=disabled)
  Holding 5:   Runtime hours (14847)
  Holding 10:  Fuel injection rate percent (65)
  Holding 11:  Cooling valve percent (80)
  Holding 100: Interlock (1=engaged, 0=bypassed) — write-protected
  Holding 200: Maintenance key register (write 7734 to unlock interlock writes)

Flags:
  18: System serial number in HMI footer
  19: Displayed after thermal runaway sequence
"""

import logging
import os
import threading
import time
from functools import wraps

from flask import Flask, request, session, redirect, url_for, jsonify, render_template_string

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("a5-scada")

# --- Constants ---
AUTH_USER = "svc-scada"
AUTH_PASS = "Sc@da#2025!"
FLAG_18 = "FLAG{1d4e7b0a3c9f8265}"
FLAG_19 = "FLAG{a7f2c8d0e5b34169}"
MAINTENANCE_KEY = 7734
INTERLOCK_TIMEOUT_S = 60
MODBUS_PORT = int(os.environ.get("MODBUS_PORT", "5050"))
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))

# --- Shared generator state ---
state = {
    "status": 1,         # 1=online
    "output_mw": 42,     # 4.2 MW (stored as 42, display divides by 10)
    "fuel_level": 78,    # percent
    "coolant_temp": 82,  # celsius
    "thermal_safety": 1, # 1=enabled
    "runtime_hours": 14847,
    "fuel_injection": 65, # percent
    "cooling_valve": 80,  # percent
    "interlock": 1,       # 1=engaged (thermal safety hardware interlock)
    "maint_key_time": None,
    "runaway_active": False,
    "runaway_complete": False,
}
state_lock = threading.Lock()

# ============================================
# MODBUS PLC BACKEND
# ============================================
from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.pdu.device import ModbusDeviceIdentification
from pymodbus.server import StartTcpServer


class GeneratorHoldingBlock(ModbusSequentialDataBlock):
    """Holding registers with interlock protection and state sync."""

    def __init__(self, address, values):
        super().__init__(address, values)

    def getValues(self, address, count):
        """Sync state to registers before read."""
        with state_lock:
            self._sync_from_state()
        return super().getValues(address, count)

    def setValues(self, address, values):
        reg = address - 1  # wire address

        # Maintenance key (reg 200)
        if reg == 200 and len(values) == 1:
            with state_lock:
                if values[0] == MAINTENANCE_KEY:
                    state["maint_key_time"] = time.time()
                    log.info("Maintenance key accepted — interlock writes unlocked for %ds", INTERLOCK_TIMEOUT_S)
                else:
                    log.info("Wrong maintenance key: %d", values[0])
            return

        # Interlock register (reg 100) — write-protected unless maintenance key active
        if reg == 100 and len(values) == 1:
            with state_lock:
                if state["maint_key_time"] and (time.time() - state["maint_key_time"]) <= INTERLOCK_TIMEOUT_S:
                    state["interlock"] = values[0]
                    if values[0] == 0:
                        log.info("INTERLOCK BYPASSED — thermal safety can now be disabled")
                        state["thermal_safety"] = 0
                    else:
                        log.info("Interlock re-engaged")
                        state["thermal_safety"] = 1
                    state["maint_key_time"] = None
                else:
                    log.info("Interlock write rejected — maintenance key not active")
            return

        # Fuel injection (reg 10)
        if reg == 10 and len(values) == 1:
            with state_lock:
                state["fuel_injection"] = min(max(values[0], 0), 100)
                log.info("Fuel injection set to %d%%", state["fuel_injection"])
                self._check_runaway()
            super().setValues(address, values)
            return

        # Cooling valve (reg 11)
        if reg == 11 and len(values) == 1:
            with state_lock:
                state["cooling_valve"] = min(max(values[0], 0), 100)
                log.info("Cooling valve set to %d%%", state["cooling_valve"])
                self._check_runaway()
            super().setValues(address, values)
            return

        # Thermal safety toggle (reg 4) — only works if interlock bypassed
        if reg == 4 and len(values) == 1:
            with state_lock:
                if state["interlock"] == 0:
                    state["thermal_safety"] = values[0]
                    log.info("Thermal safety set to %d", values[0])
                else:
                    log.info("Thermal safety write blocked by interlock")
            return

        super().setValues(address, values)

    def _sync_from_state(self):
        """Write current state values into registers."""
        s = state
        super().setValues(1, [s["status"]])
        super().setValues(2, [s["output_mw"]])
        super().setValues(3, [s["fuel_level"]])
        super().setValues(4, [s["coolant_temp"]])
        super().setValues(5, [s["thermal_safety"]])
        super().setValues(6, [s["runtime_hours"]])
        super().setValues(11, [s["fuel_injection"]])
        super().setValues(12, [s["cooling_valve"]])
        super().setValues(101, [s["interlock"]])

    def _check_runaway(self):
        """Check if conditions for thermal runaway are met."""
        s = state
        if (s["thermal_safety"] == 0 and s["interlock"] == 0
                and s["fuel_injection"] >= 100 and s["cooling_valve"] <= 0
                and not s["runaway_active"] and not s["runaway_complete"]):
            log.info("THERMAL RUNAWAY CONDITIONS MET — starting sequence")
            s["runaway_active"] = True
            threading.Thread(target=self._runaway_sequence, daemon=True).start()

    def _runaway_sequence(self):
        """Simulate thermal runaway over ~10 seconds."""
        temps = [90, 100, 110, 120, 130, 140, 150]
        for t in temps:
            with state_lock:
                state["coolant_temp"] = t
                log.info("Temperature: %dC%s", t, " — WARNING" if t >= 130 else "")
            time.sleep(1.5)

        with state_lock:
            state["coolant_temp"] = 999
            state["status"] = 0
            state["runaway_active"] = False
            state["runaway_complete"] = True
            log.info("CRITICAL — THERMAL RUNAWAY — GENERATOR DESTROYED")


def start_modbus():
    """Start the Modbus PLC server in a background thread."""
    hr = [0] * 256
    holding = GeneratorHoldingBlock(0, hr)
    store = ModbusDeviceContext(
        di=ModbusSequentialDataBlock(0, [0] * 17),
        co=ModbusSequentialDataBlock(0, [0] * 17),
        hr=holding,
        ir=ModbusSequentialDataBlock(0, [0] * 17),
    )
    context = ModbusServerContext(devices=store, single=True)
    identity = ModbusDeviceIdentification()
    identity.VendorName = "BOREAS INDUSTRIAL SYSTEMS"
    identity.ProductCode = "GEN-CTRL-MK3"
    identity.ProductName = "Generator Controller"
    identity.MajorMinorRevision = "3.1.0"

    log.info("Modbus PLC starting on port %d", MODBUS_PORT)
    StartTcpServer(context=context, identity=identity, address=("0.0.0.0", MODBUS_PORT))


# ============================================
# FLASK WEB HMI
# ============================================
app = Flask(__name__)
app.secret_key = os.urandom(24)

SYSTEM_LOGS = """2025-11-05 14:22:01 [INFO] Generator startup sequence initiated
2025-11-05 14:22:15 [INFO] Fuel system pressurized
2025-11-05 14:22:28 [INFO] Turbine spinning — 1200 RPM
2025-11-05 14:22:45 [INFO] Generator online — output 4.2 MW
2025-11-10 09:15:33 [INFO] Scheduled maintenance check — all parameters nominal
2025-11-15 02:47:12 [WARN] Thermal safety triggered — automatic fuel cutback
2025-11-15 02:47:15 [INFO] Coolant temp was 91C — safety threshold 90C
2025-11-15 03:12:44 [INFO] Investigated by D. Kowalski. Cause: sensor drift. Recalibrated.
2025-11-15 03:15:01 [INFO] Security team dispatched to generator room per protocol
2025-11-15 03:30:22 [INFO] All clear — generator nominal
2025-11-20 08:00:00 [INFO] Runtime: 14,847 hours
2025-11-20 08:00:01 [INFO] Fuel level: 78% — next refuel in ~45 days"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html><head><title>Generator Control System</title>
<style>
body { background: #0a0a1a; color: #00ff88; font-family: monospace; margin: 20px; }
h1 { color: #00ff88; border-bottom: 1px solid #333; padding-bottom: 10px; }
.panel { background: #111; border: 1px solid #333; padding: 15px; margin: 10px 0; border-radius: 5px; }
.value { color: #fff; font-size: 18px; }
.warn { color: #ff8800; }
.crit { color: #ff0000; }
.ok { color: #00ff88; }
table { border-collapse: collapse; width: 100%; }
td { padding: 8px; border-bottom: 1px solid #222; }
.label { color: #888; width: 250px; }
a { color: #4488ff; }
footer { margin-top: 30px; color: #444; font-size: 11px; border-top: 1px solid #222; padding-top: 10px; }
.destroyed { background: #ff0000; color: #fff; padding: 40px; text-align: center; font-size: 24px; }
</style></head><body>
{% if state.runaway_complete %}
<div class="destroyed">
<h1>CRITICAL — THERMAL RUNAWAY — AUTOMATIC SHUTDOWN FAILED</h1>
<p>Generator offline. Catastrophic thermal failure.</p>
<p>{{ flag_19 }}</p>
</div>
{% else %}
<h1>BOREAS SITE POWER — Generator Monitoring</h1>
<div class="panel">
<table>
<tr><td class="label">Generator Status</td><td class="value {% if state.status %}ok{% else %}crit{% endif %}">{{ "ONLINE" if state.status else "OFFLINE" }}</td></tr>
<tr><td class="label">Output</td><td class="value">{{ "%.1f"|format(state.output_mw / 10) }} MW</td></tr>
<tr><td class="label">Fuel Level</td><td class="value">{{ state.fuel_level }}%</td></tr>
<tr><td class="label">Coolant Temperature</td><td class="value {% if state.coolant_temp > 130 %}crit{% elif state.coolant_temp > 90 %}warn{% else %}ok{% endif %}">{{ state.coolant_temp }}°C{% if state.coolant_temp > 130 %} — WARNING{% endif %}</td></tr>
<tr><td class="label">Thermal Safety</td><td class="value {% if state.thermal_safety %}ok{% else %}crit{% endif %}">{{ "ENABLED" if state.thermal_safety else "DISABLED" }}</td></tr>
<tr><td class="label">Runtime Hours</td><td class="value">{{ "{:,}".format(state.runtime_hours) }}</td></tr>
<tr><td class="label">Fuel Injection Rate</td><td class="value">{{ state.fuel_injection }}%</td></tr>
<tr><td class="label">Cooling Valve</td><td class="value">{{ state.cooling_valve }}%</td></tr>
</table>
</div>
<p><a href="/control">Control Panel</a> | <a href="/architecture">System Architecture</a> | <a href="/logs">System Logs</a></p>
{% endif %}
<footer>Boreas Industrial Systems — Generator Controller MK3 — S/N: {{ flag_18 }}</footer>
</body></html>"""

CONTROL_HTML = """<!DOCTYPE html>
<html><head><title>Generator Control Panel</title>
<style>
body { background: #0a0a1a; color: #00ff88; font-family: monospace; margin: 20px; }
h1 { color: #ff8800; }
.panel { background: #111; border: 1px solid #333; padding: 15px; margin: 10px 0; }
label { display: block; margin: 10px 0 5px; color: #888; }
input[type=range] { width: 300px; }
button { background: #333; color: #fff; border: 1px solid #666; padding: 10px 20px; cursor: pointer; margin: 5px; }
button:hover { background: #555; }
.danger { background: #ff0000; }
a { color: #4488ff; }
footer { margin-top: 30px; color: #444; font-size: 11px; }
</style></head><body>
<h1>GENERATOR CONTROL PANEL — AUTHORIZED ACCESS ONLY</h1>
<div class="panel">
<p>Thermal Safety: {{ "ENABLED" if state.thermal_safety else "DISABLED" }} | Interlock: {{ "ENGAGED" if state.interlock else "BYPASSED" }}</p>
<p>Note: Thermal safety cannot be toggled while hardware interlock is engaged. Interlock bypass requires maintenance key via Modbus register 200.</p>
</div>
<p><a href="/">Back to Monitoring</a></p>
<footer>S/N: {{ flag_18 }}</footer>
</body></html>"""

ARCH_HTML = """<!DOCTYPE html>
<html><head><title>System Architecture</title>
<style>
body { background: #0a0a1a; color: #00ff88; font-family: monospace; margin: 20px; }
pre { background: #111; padding: 15px; border: 1px solid #333; }
a { color: #4488ff; }
footer { margin-top: 30px; color: #444; font-size: 11px; }
</style></head><body>
<h1>GENERATOR CONTROL SYSTEM — ARCHITECTURE</h1>
<pre>
+---------------------------+       +------------------------+
|     WEB HMI (port 8080)   |       |  HARDWARE INTERLOCK    |
|  Monitoring + Control UI  | <---> |  Modbus/TCP port 502   |
|  Auth: svc-scada          |       |  Holding registers     |
+---------------------------+       +------------------------+
                                           |
                                    +------+------+
                                    |  GENERATOR  |
                                    |  Diesel     |
                                    |  4.2 MW     |
                                    |  Fuel/Cool  |
                                    +-------------+

MODBUS REGISTER MAP:
  HR 0:   Generator status (1=online)
  HR 1:   Output (MW x10)
  HR 2:   Fuel level (%)
  HR 3:   Coolant temperature (C)
  HR 4:   Thermal safety (1=enabled, 0=disabled)
  HR 5:   Runtime hours
  HR 10:  Fuel injection rate (%)
  HR 11:  Cooling valve (%)
  HR 100: Hardware interlock (1=engaged, 0=bypassed)
  HR 200: Maintenance key register

NOTE: The hardware interlock PLC runs independently of the HMI.
Direct Modbus access to the PLC is available on port 502.
The interlock cannot be bypassed through the web interface alone.
</pre>
<p><a href="/">Back to Monitoring</a></p>
<footer>S/N: {{ flag_18 }}</footer>
</body></html>"""

LOGS_HTML = """<!DOCTYPE html>
<html><head><title>System Logs</title>
<style>
body { background: #0a0a1a; color: #00ff88; font-family: monospace; margin: 20px; }
pre { background: #111; padding: 15px; border: 1px solid #333; font-size: 12px; }
a { color: #4488ff; }
footer { margin-top: 30px; color: #444; font-size: 11px; }
</style></head><body>
<h1>SYSTEM LOGS</h1>
<pre>{{ logs }}</pre>
<p><a href="/">Back to Monitoring</a></p>
<footer>S/N: {{ flag_18 }}</footer>
</body></html>"""

LOGIN_HTML = """<!DOCTYPE html>
<html><head><title>Login</title>
<style>
body { background: #0a0a1a; color: #00ff88; font-family: monospace; margin: 20px; }
input { background: #111; color: #fff; border: 1px solid #333; padding: 8px; margin: 5px 0; display: block; }
button { background: #333; color: #fff; border: 1px solid #666; padding: 10px 20px; cursor: pointer; }
.error { color: #ff0000; }
</style></head><body>
<h1>AUTHENTICATION REQUIRED</h1>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="POST">
<label>Username:</label><input name="username" type="text">
<label>Password:</label><input name="password" type="password">
<button type="submit">Login</button>
</form>
</body></html>"""


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def dashboard():
    with state_lock:
        s = dict(state)
    return render_template_string(DASHBOARD_HTML, state=s, flag_18=FLAG_18, flag_19=FLAG_19)


@app.route("/control")
@login_required
def control():
    with state_lock:
        s = dict(state)
    return render_template_string(CONTROL_HTML, state=s, flag_18=FLAG_18)


@app.route("/architecture")
def architecture():
    return render_template_string(ARCH_HTML, flag_18=FLAG_18)


@app.route("/logs")
def logs():
    return render_template_string(LOGS_HTML, logs=SYSTEM_LOGS, flag_18=FLAG_18)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("username") == AUTH_USER and request.form.get("password") == AUTH_PASS:
            session["authenticated"] = True
            return redirect(request.args.get("next", url_for("dashboard")))
        error = "Invalid credentials"
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/api/status")
def api_status():
    with state_lock:
        s = dict(state)
    return jsonify(s)


def start_web():
    """Start the Flask web HMI."""
    log.info("Web HMI starting on port %d", WEB_PORT)
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)


# ============================================
# MAIN
# ============================================
def main():
    log.info("A5 SCADA Generator HMI + PLC starting")
    log.info("  Web HMI: port %d", WEB_PORT)
    log.info("  Modbus PLC: port %d", MODBUS_PORT)
    log.info("  Auth: %s / %s", AUTH_USER, AUTH_PASS)
    log.info("  Flag 18: %s (in footer)", FLAG_18)
    log.info("  Flag 19: %s (after runaway)", FLAG_19)
    log.info("  Maintenance key: %d", MAINTENANCE_KEY)

    # Start Modbus in background thread
    modbus_thread = threading.Thread(target=start_modbus, daemon=True)
    modbus_thread.start()

    # Start Flask in main thread
    start_web()


if __name__ == "__main__":
    main()
