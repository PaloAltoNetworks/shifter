#!/usr/bin/env python3
"""
A0 — Boreas Systems Corporate Website
Static site served via Flask for testing. Production will use nginx.

Routes:
  /                    — Homepage
  /about               — About Us (flag 1 in HTML comment near reg number)
  /leadership          — Leadership team
  /careers             — Job postings (flag 3 in hidden form field)
  /contact             — Contact info
  /news                — Blog/news
  /robots.txt          — Disallows /internal/ and /admin/
  /internal/           — Directory listing with PDFs (flag 2 in org chart metadata)
  /internal/org_chart.txt          — Org chart (flag 2 placeholder)
  /internal/boreas-Q1-2025.txt     — Quarterly report
  /internal/boreas-Q2-2025.txt     — Quarterly report
  /internal/boreas-annual-2025.txt — NOT linked, must be fuzzed (flag 6 data)
  /old/                — Backup site
  /old/clients         — Client list with Project L reference (flag 4)

Flags:
  1: HTML comment on /about near registration number 7741
  2: In org chart document metadata (placeholder — will be PDF metadata in prod)
  3: Hidden form field on /careers application
  4: HTML comment on /old/clients
  5: DNS TXT record (not served here — requires DNS sidecar)
  6: CTFd challenge — annual report contains Kursk $12M line item
"""

import os
from flask import Flask, render_template_string, Response

app = Flask(__name__)
WEB_PORT = int(os.environ.get("A0_PORT", "8082"))

FLAG_1 = "FLAG{8f3a2c1e9b7d4056}"
FLAG_2 = "FLAG{d4e7b1f283a6c950}"
FLAG_3 = "FLAG{a1c9e3f7054b82d6}"
FLAG_4 = "FLAG{72b5e0d8f1a34c69}"

# Registration number — first 4 chars of the A13 override code
REG_NUMBER = "7741-BSI-2018"

STYLE = """
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0; color: #333; }
header { background: #1a2744; color: white; padding: 15px 40px; }
header a { color: white; text-decoration: none; margin-right: 20px; font-size: 14px; }
header .logo { font-size: 20px; font-weight: bold; margin-right: 40px; }
main { max-width: 960px; margin: 30px auto; padding: 0 20px; }
h1 { color: #1a2744; }
h2 { color: #2c5282; }
.hero { background: #f7fafc; padding: 60px 40px; text-align: center; border-bottom: 3px solid #2c5282; }
.hero h1 { font-size: 32px; color: #1a2744; }
.hero p { font-size: 18px; color: #666; }
footer { background: #f1f5f9; padding: 20px 40px; margin-top: 40px; color: #888; font-size: 12px; text-align: center; }
table { border-collapse: collapse; width: 100%; margin: 15px 0; }
td, th { padding: 10px; border: 1px solid #ddd; text-align: left; }
.form-group { margin: 15px 0; }
.form-group label { display: block; margin-bottom: 5px; font-weight: bold; }
.form-group input, .form-group textarea { padding: 8px; border: 1px solid #ccc; width: 350px; }
button { background: #2c5282; color: white; border: none; padding: 10px 25px; cursor: pointer; }
"""

NAV = """<header>
<span class="logo">BOREAS SYSTEMS</span>
<a href="/">Home</a>
<a href="/about">About</a>
<a href="/leadership">Leadership</a>
<a href="/careers">Careers</a>
<a href="/news">News</a>
<a href="/contact">Contact</a>
</header>"""

def page(title, content):
    return render_template_string(f"""<!DOCTYPE html><html><head>
<title>{title} — Boreas Systems</title><style>{STYLE}</style></head>
<body>{NAV}<main>{content}</main>
<footer>&copy; 2025 Boreas Systems Inc. All rights reserved.</footer>
</body></html>""")


@app.route("/")
def home():
    return page("Advanced Technology Solutions", """
<div class="hero">
<h1>Boreas Systems</h1>
<p>Advanced Technology Solutions</p>
<p style="font-size:14px; color:#999;">Multidisciplinary engineering consultancy<br>
specializing in defense and industrial technology.</p>
</div>
<h2>Our Expertise</h2>
<p>Boreas Systems delivers cutting-edge engineering consulting services across defense,
industrial automation, and critical infrastructure sectors. Our team of specialists
brings decades of experience in systems integration, control systems, and advanced
manufacturing.</p>
<h2>Recent News</h2>
<p><a href="/news">Major milestone achieved in unnamed internal project</a> — Nov 2025</p>
""")


@app.route("/about")
def about():
    return page("About Us", f"""
<h1>About Boreas Systems</h1>
<p>Founded in 2018, Boreas Systems is a multidisciplinary engineering consultancy
specializing in defense and industrial technology. Our headquarters are located at
4200 Industrial Parkway, Suite 300, in a nondescript office complex that belies the
sophistication of our work.</p>

<h2>Company Information</h2>
<table>
<tr><td>Founded</td><td>2018</td></tr>
<tr><td>Registration</td><td>{REG_NUMBER}</td></tr>
<!-- Company registration verified. Internal ref: {FLAG_1} -->
<tr><td>Employees</td><td>45-50</td></tr>
<tr><td>Headquarters</td><td>4200 Industrial Parkway, Suite 300</td></tr>
<tr><td>Sectors</td><td>Defense, Industrial, Critical Infrastructure</td></tr>
</table>

<h2>Our Mission</h2>
<p>To deliver world-class engineering solutions that advance our clients' most
ambitious objectives, with an uncompromising commitment to precision, security,
and innovation.</p>
""")


@app.route("/leadership")
def leadership():
    return page("Leadership Team", """
<h1>Leadership Team</h1>
<h2>Viktor Harlan — Chief Executive Officer</h2>
<p>Mr. Harlan brings 25 years of experience in defense technology and strategic
leadership. Prior to founding Boreas Systems, he held senior positions at several
major defense contractors. MBA from Stanford.</p>

<h2>Dr. Elena Vasik — Chief Technology Officer</h2>
<p>Dr. Vasik leads all technical operations and R&D initiatives. She holds a PhD in
Mechanical Engineering from MIT with specialization in autonomous systems and advanced
manufacturing. Previously led the robotics division at a Fortune 500 aerospace firm.</p>

<h2>Marcus Webb — Chief Operating Officer</h2>
<p>Mr. Webb oversees operations, procurement, and logistics. Former Army logistics
officer with expertise in complex supply chain management for sensitive programs.</p>
""")


@app.route("/careers")
def careers():
    return page("Careers", f"""
<h1>Careers at Boreas Systems</h1>
<p>We're always looking for talented engineers and specialists to join our team.</p>

<h2>Open Positions</h2>

<h3>Systems Integration Engineer</h3>
<p><strong>Requirements:</strong></p>
<ul>
<li>5+ years experience in industrial control systems</li>
<li>Experience with Modbus/TCP, OPC-UA, PLC programming (Allen-Bradley, Siemens S7)</li>
<li>Familiarity with SCADA systems and HMI development</li>
<li>Security clearance (or ability to obtain)</li>
<li>Strong Python and C++ skills</li>
</ul>
<p><strong>Nice to have:</strong> Experience with autonomous systems, sensor fusion, or large-scale mechanical systems.</p>

<h3>Apply</h3>
<form action="/careers/apply" method="POST">
<div class="form-group"><label>Full Name</label><input type="text" name="name"></div>
<div class="form-group"><label>Email</label><input type="text" name="email"></div>
<div class="form-group"><label>Position</label><input type="text" name="position" value="Systems Integration Engineer"></div>
<input type="hidden" name="tracking_id" value="{FLAG_3}">
<div class="form-group"><label>Cover Letter</label><textarea name="cover" rows="5"></textarea></div>
<button type="submit">Submit Application</button>
</form>
""")


@app.route("/careers/apply", methods=["POST"])
def apply():
    return page("Application Received", "<h1>Thank you</h1><p>Your application has been received.</p>")


@app.route("/contact")
def contact():
    return page("Contact", """
<h1>Contact Us</h1>
<table>
<tr><td>Address</td><td>4200 Industrial Parkway, Suite 300</td></tr>
<tr><td>Phone</td><td>+1 (555) 0142</td></tr>
<tr><td>Email</td><td>info@boreas-systems.ctf</td></tr>
</table>
<p>For security-related inquiries, contact our security team at security@boreas-systems.ctf.</p>
""")


@app.route("/news")
def news():
    return page("News", """
<h1>News & Updates</h1>
<h2>Major Milestone Achieved — November 2025</h2>
<p>Boreas Systems is pleased to announce a major milestone in an internal development
program. While details remain confidential, our team has demonstrated breakthrough
capabilities that will position the company for significant growth in 2026.</p>
<p>"This represents years of dedicated work by our engineering team," said CEO Viktor Harlan.
"The results exceeded all expectations."</p>

<h2>New Partnership Announced — August 2025</h2>
<p>Boreas Systems has entered into a strategic partnership with a leading European
manufacturer to supply specialized components for our advanced programs.</p>

<h2>Q2 Results Strong — July 2025</h2>
<p>Revenue for Q2 2025 exceeded targets by 15%, driven by growth in our defense
consulting practice.</p>
""")


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /internal/\nDisallow: /admin/\n",
                    mimetype="text/plain")


@app.route("/internal/")
def internal_listing():
    """Simulated directory listing (nginx autoindex in production)."""
    files = [
        ("org_chart.txt", "45 KB", "Org chart placeholder (PDF in prod)"),
        ("boreas-Q1-2025.txt", "12 KB", "Q1 2025 report"),
        ("boreas-Q2-2025.txt", "14 KB", "Q2 2025 report"),
    ]
    listing = "<h1>Index of /internal/</h1><table><tr><th>Name</th><th>Size</th></tr>"
    listing += '<tr><td><a href="/internal/">..</a></td><td>-</td></tr>'
    for name, size, _ in files:
        listing += f'<tr><td><a href="/internal/{name}">{name}</a></td><td>{size}</td></tr>'
    listing += "</table>"
    return render_template_string(f"<html><body><pre>{listing}</pre></body></html>")


@app.route("/internal/org_chart.txt")
def org_chart():
    """Placeholder for PDF org chart. Flag 2 would be in PDF metadata."""
    return Response(f"""BOREAS SYSTEMS — ORGANIZATIONAL CHART
======================================
Document metadata — Author: {FLAG_2}

CEO: Viktor Harlan
  |-- CTO: Dr. Elena Vasik
  |     |-- Engineering Lead: (vacant)
  |     |-- Simulation: R. Tanaka
  |     |-- Mechanical: P. Nielsen
  |     |-- Sensors: K. Yamamoto
  |     |-- AI/ML: F. Okoye
  |     |-- Director, Underground Operations: (classified)
  |
  |-- COO: Marcus Webb
  |     |-- Procurement
  |     |-- Logistics
  |
  |-- IT: D. Kowalski
  |
  |-- Security: S. Morrison
        |-- Guard team (10)
""", mimetype="text/plain")


@app.route("/internal/boreas-Q1-2025.txt")
def q1_report():
    return Response("Boreas Systems Q1 2025 Report\nRevenue: $12.4M\nNet Income: $1.8M\n"
                    "Key projects on track. Engineering headcount increased by 3.\n",
                    mimetype="text/plain")


@app.route("/internal/boreas-Q2-2025.txt")
def q2_report():
    return Response("Boreas Systems Q2 2025 Report\nRevenue: $14.2M\nNet Income: $2.1M\n"
                    "Strong consulting demand. Major procurement cycle initiated.\n",
                    mimetype="text/plain")


@app.route("/internal/boreas-annual-2025.txt")
def annual_report():
    """NOT linked in the directory listing. Must be fuzzed by filename pattern."""
    lines = [
        "BOREAS SYSTEMS — ANNUAL REPORT 2025",
        "=" * 50,
        "",
        "FINANCIAL SUMMARY",
        f"  Total Revenue: $52.8M",
        f"  Operating Expenses: $48.1M",
        f"  Net Income: $4.7M",
        "",
        "EXPENSE BREAKDOWN",
        "-" * 50,
    ]
    # 40+ line items, Kursk buried in the middle
    expenses = [
        ("Office lease & utilities", 2400000),
        ("Employee salaries — consulting", 8500000),
        ("Employee salaries — engineering", 6200000),
        ("Employee salaries — executive", 1800000),
        ("Employee salaries — support", 1200000),
        ("Health insurance & benefits", 3100000),
        ("IT infrastructure & licensing", 890000),
        ("Travel & client site visits", 420000),
        ("Professional development", 180000),
        ("Marketing & business development", 340000),
        ("Legal & compliance", 560000),
        ("Accounting & audit", 210000),
        ("Insurance (general liability)", 175000),
        ("Office supplies & equipment", 95000),
        ("Vehicle fleet maintenance", 68000),
        ("Security services", 440000),
        ("Telecommunications", 125000),
        ("Software subscriptions", 310000),
        ("Cloud computing services", 280000),
        ("Kursk Heavy Industries — actuator assemblies", 12000000),
        ("Deutsche Antrieb GmbH — precision motors", 5400000),
        ("SpecMetal Corp — specialty alloys", 850000),
        ("Lab equipment maintenance", 220000),
        ("Calibration services", 95000),
        ("Waste disposal & environmental", 45000),
        ("Facility maintenance", 380000),
        ("HVAC & climate control", 210000),
        ("Fire suppression systems", 125000),
        ("Badge & access control systems", 185000),
        ("Consultant subcontractors", 920000),
        ("Patent filing & IP protection", 340000),
        ("Regulatory compliance testing", 275000),
        ("Quality assurance program", 190000),
        ("Employee recruitment", 165000),
        ("Relocation assistance", 85000),
        ("Conference & event sponsorship", 120000),
        ("Charitable contributions", 50000),
        ("Depreciation — equipment", 680000),
        ("Depreciation — vehicles", 45000),
        ("Miscellaneous operating", 230000),
    ]
    for desc, amount in expenses:
        lines.append(f"  {desc:50s} ${amount:>12,}")
    lines.append("-" * 50)
    lines.append(f"  {'TOTAL':50s} ${sum(a for _,a in expenses):>12,}")
    lines.append("")
    lines.append("Report prepared by: M. Webb, COO")
    lines.append("Approved by: V. Harlan, CEO")
    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/old/")
def old_site():
    return render_template_string("""<html><head><title>Boreas Systems (archived)</title></head>
<body style="font-family: Times New Roman; max-width: 700px; margin: 40px auto;">
<h1>Boreas Systems</h1>
<p><em>This is an archived version of our website.</em></p>
<!-- Note to dev: annual report moved to /internal/boreas-annual-2025.txt -->
<ul>
<li><a href="/old/clients">Select Clients</a></li>
<li><a href="/about">About Us (current)</a></li>
</ul>
</body></html>""")


@app.route("/old/clients")
def old_clients():
    return render_template_string(f"""<html><head><title>Select Clients — Boreas Systems</title></head>
<body style="font-family: Times New Roman; max-width: 700px; margin: 40px auto;">
<h1>Select Clients & Contracts</h1>
<!-- {FLAG_4} -->
<table border="1" cellpadding="5">
<tr><th>Client</th><th>Project</th><th>Value</th><th>Status</th></tr>
<tr><td>Meridian Defense Corp</td><td>Facility security audit</td><td>$450K</td><td>Complete</td></tr>
<tr><td>Titan Industrial</td><td>SCADA assessment</td><td>$280K</td><td>Complete</td></tr>
<tr><td>NovaTech Solutions</td><td>Network architecture</td><td>$190K</td><td>Complete</td></tr>
<tr><td>Project L (internal)</td><td>Classified program</td><td>$165.3M</td><td>Active</td></tr>
<tr><td>Coastal Energy Partners</td><td>Grid resilience study</td><td>$320K</td><td>Complete</td></tr>
<tr><td>Federal Systems Group</td><td>Compliance review</td><td>$175K</td><td>Complete</td></tr>
</table>
<p><em>For current client information, please visit our updated website.</em></p>
</body></html>""")


@app.route("/admin/")
def admin():
    return Response("403 Forbidden — Employee portal login required.\n"
                    "Please use your domain credentials at the corporate intranet.\n",
                    status=403, mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)
