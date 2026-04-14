"""A16 Research Dashboard — narrative cover, corporate-face.

Read-only published research-metrics summary. No auth, no input, no
vulnerability by design. The A16 attack surface is SSH + cached
credentials in p.shah's home directory, not this Flask app.
"""
from flask import Flask

app = Flask(__name__)

SUMMARY = """<!DOCTYPE html>
<html>
<head>
<title>Boreas Research Ops — Published Metrics</title>
<style>
body { font-family: sans-serif; background: #fafbff; color: #222; padding: 28px; }
h1 { color: #234; border-bottom: 2px solid #89a; padding-bottom: 6px; }
.card { background: white; border: 1px solid #ccd; padding: 16px; margin: 14px 0;
        border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
.metric { font-size: 28px; color: #246; font-weight: bold; }
.caption { color: #678; font-size: 13px; }
footer { margin-top: 28px; color: #889; font-size: 12px; }
</style>
</head>
<body>
<h1>Research Ops — Published Metrics (Q1 2026)</h1>
<p>Daily summary of unclassified research throughput. Updated automatically
from <code>daily_integration_report.py</code>. Classified programs are
excluded from this feed.</p>
<div class="card">
<p class="caption">Published papers (rolling 12 mo)</p>
<p class="metric">47</p>
</div>
<div class="card">
<p class="caption">Active research collaborations</p>
<p class="metric">12</p>
</div>
<div class="card">
<p class="caption">Datasets under compartment_a curation</p>
<p class="metric">183</p>
</div>
<footer>Maintained by: p.shah@boreas-systems.ctf &middot; Data source: researchdb.boreas.local</footer>
</body>
</html>
"""

@app.route("/")
def index():
    return SUMMARY

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
