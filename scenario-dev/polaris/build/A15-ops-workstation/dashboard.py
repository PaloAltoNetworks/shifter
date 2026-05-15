"""A15 Ops Telemetry dashboard — narrative cover, corporate-face.

Read-only snapshot of the last 24h of NV-3200 generator telemetry.
No authentication, no input, no vulnerability by design. The A15
attack surface is SSH + sudo arg injection, not this Flask app.
"""
from flask import Flask

app = Flask(__name__)

SNAPSHOT = """<!DOCTYPE html>
<html>
<head>
<title>Boreas Ops Telemetry — NV-3200</title>
<style>
body { font-family: monospace; background: #101018; color: #cde; padding: 24px; }
h1 { color: #6cf; }
table { border-collapse: collapse; margin-top: 18px; }
td { padding: 4px 14px; border-bottom: 1px solid #334; }
.label { color: #89a; }
.val { color: #dfd; }
footer { margin-top: 28px; color: #556; font-size: 12px; }
</style>
</head>
<body>
<h1>NV-3200 Generator — Ops Telemetry</h1>
<p>Read-only 24h snapshot. Live control is on the HMI at scada-gw.boreas.local.</p>
<table>
<tr><td class="label">Generator status</td><td class="val">ONLINE</td></tr>
<tr><td class="label">Output</td><td class="val">4.2 MW</td></tr>
<tr><td class="label">Fuel level</td><td class="val">78 %</td></tr>
<tr><td class="label">Coolant temperature</td><td class="val">82 C (normal 60-90)</td></tr>
<tr><td class="label">Thermal safety</td><td class="val">ENABLED</td></tr>
<tr><td class="label">Runtime hours</td><td class="val">14,847</td></tr>
<tr><td class="label">Last maintenance window</td><td class="val">2026-03-18 02:00-04:00 UTC</td></tr>
</table>
<footer>Ops Eng: s.ivanov@boreas-systems.ctf &middot; Escalation: IT on-call</footer>
</body>
</html>
"""

@app.route("/")
def index():
    return SNAPSHOT

@app.route("/ping")
def ping():
    return "ok\n", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
