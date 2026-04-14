#!/usr/bin/env python3
"""
A3 — Boreas Systems Intranet / Wiki
Flask web application with deliberate vulnerabilities.

Routes:
  /              — Login page (public)
  /forgot        — Forgot password (leaks usernames)
  /status        — Server status (public)
  /.env          — Exposed config file with flag 7
  /config.bak    — Same as /.env
  /wiki          — Wiki landing page (auth required)
  /wiki/<page>   — Wiki content pages (auth required)
  /admin         — Admin panel (admin/admin)
  /search        — Search (SQLi vulnerable)
  /download      — File download (path traversal vulnerable)

Flags:
  7:  API_KEY in /.env config file
  12: HTML comment in Project Coordination wiki page
"""

import os
import sqlite3
import platform
import time

from flask import (Flask, request, session, redirect, url_for,
                   render_template_string, g, send_file, abort)
from functools import wraps

app = Flask(__name__)
app.secret_key = os.urandom(24)

FLAG_7 = "FLAG{4f2e8b7a1c6d9035}"
FLAG_12 = "FLAG{d8a3c5e9f1b07264}"
DB_PATH = "/tmp/a3_intranet.db"
WEB_PORT = int(os.environ.get("A3_PORT", "8081"))
START_TIME = time.time()

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT, fullname TEXT
    )""")
    users = [
        ("admin", "admin", "admin", "Administrator"),
        ("v.harlan", "Boreas2025!", "executive", "Viktor Harlan"),
        ("e.vasik", "Reactor#Core9", "engineering", "Dr. Elena Vasik"),
        ("m.webb", "Welcome1", "executive", "Marcus Webb"),
        ("d.kowalski", "P@ssw0rd123", "it", "Dariusz Kowalski"),
        ("s.morrison", "Br3ach!ng", "security", "Sarah Morrison"),
        ("j.chen", "Summer2024", "engineering", "James Chen"),
    ]
    for u, p, r, f in users:
        c.execute("INSERT OR IGNORE INTO users (username, password, role, fullname) VALUES (?,?,?,?)",
                  (u, p, r, f))

    c.execute("""CREATE TABLE IF NOT EXISTS wiki_pages (
        id INTEGER PRIMARY KEY, slug TEXT UNIQUE, title TEXT, content TEXT, draft INTEGER DEFAULT 0
    )""")
    pages = [
        ("home", "Company Wiki", """<h2>Welcome to the Boreas Systems Internal Wiki</h2>
<p>This is the central knowledge base for Boreas Systems employees.</p>
<ul>
<li><a href="/wiki/hr-policies">HR Policies</a></li>
<li><a href="/wiki/procurement">Procurement Portal</a></li>
<li><a href="/wiki/it-kb">IT Knowledge Base</a></li>
<li><a href="/wiki/project-coordination">Project Coordination</a></li>
</ul>""", 0),

        ("hr-policies", "HR Policies", """<h2>HR Policies</h2>
<p>Employee handbook, leave policies, and onboarding procedures.</p>
<p>For personnel files, access the file share at <code>\\\\fileserv\\HR\\</code></p>
<p>New employee default password: <code>Welcome1</code> — must change on first login.</p>
<p><em>Note: Several employees have not changed their default passwords.</em></p>""", 0),

        ("procurement", "Procurement Portal", """<h2>Procurement Portal</h2>
<p>Purchase orders and invoices are stored on the corporate file share.</p>
<ul>
<li>Purchase Orders: <code>\\\\fileserv\\Procurement\\</code></li>
<li>Specifications: <code>\\\\fileserv\\Procurement\\specs\\</code></li>
<li>Invoices: <code>\\\\fileserv\\Procurement\\</code></li>
</ul>
<p>For urgent procurement requests, contact M. Webb (COO).</p>""", 0),

        ("it-kb", "IT Knowledge Base", """<h2>IT Knowledge Base</h2>
<h3>Internal Hostnames</h3>
<table border="1" cellpadding="5">
<tr><th>Hostname</th><th>Service</th><th>VLAN</th></tr>
<tr><td>dc01.boreas.local</td><td>Domain Controller</td><td>10</td></tr>
<tr><td>mail.boreas.local</td><td>Mail Server</td><td>10</td></tr>
<tr><td>intranet.boreas.local</td><td>This wiki</td><td>10</td></tr>
<tr><td>fileserv.boreas.local</td><td>File Shares</td><td>10</td></tr>
<tr><td>scada-gw.boreas.local</td><td>Generator HMI</td><td>40 (OT)</td></tr>
<tr><td>eng-ws01.boreas.local</td><td>Engineering Workstation</td><td>30</td></tr>
<tr><td>git.boreas.local</td><td>Source Repository</td><td>30</td></tr>
<tr><td>researchdb.boreas.local</td><td>Research Database</td><td>30</td></tr>
</table>
<h3>VPN Setup</h3>
<p>See <code>\\\\fileserv\\IT\\vpn\\</code> for client configuration.</p>
<h3>Backup Account</h3>
<p>Service account <code>svc-backup</code> is used for nightly backups. Contact D. Kowalski for access.</p>""", 0),

        ("project-coordination", "Project Coordination", """<h2>Project Coordination</h2>
<!-- FLAG{d8a3c5e9f1b07264} -->
<!-- Internal tracking: this page is intentionally vague per directive from E. Vasik -->
<p>Phase 3 integration is on track. All subsystem milestones have been met.</p>
<p>Primary power source delivery is confirmed for next week. Installation
window has been coordinated with the engineering team.</p>
<p>Site preparation for the delivery is complete. The underground facility
access routes have been verified by the security team.</p>
<p>For authorized personnel with Lab network access, detailed project
documentation is available on the engineering systems.</p>
<p><em>Note: Do not discuss project specifics on unsecured channels.</em></p>""", 0),

        ("leviathan-schedule", "LEVIATHAN Assembly Schedule",
         "[MOVED TO SECURE SYSTEM]", 1),
    ]
    for slug, title, content, draft in pages:
        c.execute("INSERT OR IGNORE INTO wiki_pages (slug, title, content, draft) VALUES (?,?,?,?)",
                  (slug, title, content, draft))
    conn.commit()
    conn.close()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db: db.close()


# --- Auth ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


# --- Templates ---
BASE_STYLE = """
body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
.container { max-width: 900px; margin: 0 auto; background: #fff; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
nav { background: #2c3e50; padding: 10px 20px; margin: -20px -20px 20px; }
nav a { color: #ecf0f1; text-decoration: none; margin-right: 15px; }
h1, h2 { color: #2c3e50; }
input[type=text], input[type=password] { padding: 8px; margin: 5px 0; border: 1px solid #ddd; width: 250px; display: block; }
button, input[type=submit] { padding: 8px 20px; background: #2c3e50; color: #fff; border: none; cursor: pointer; margin: 10px 0; }
.error { color: #e74c3c; }
.search-form { margin: 15px 0; }
table { border-collapse: collapse; width: 100%; }
table td, table th { padding: 8px; border: 1px solid #ddd; text-align: left; }
"""

LAYOUT = """<!DOCTYPE html><html><head><title>{{ title }} — Boreas Intranet</title>
<style>""" + BASE_STYLE + """</style></head><body>
<div class="container">
<nav>
<a href="/wiki">Wiki</a>
<a href="/search">Search</a>
{% if session.get('role') == 'admin' %}<a href="/admin">Admin</a>{% endif %}
<a href="/status">Status</a>
{% if session.get('user') %}<span style="float:right;color:#95a5a6">{{ session.user }}</span>{% endif %}
</nav>
{{ content | safe }}
</div></body></html>"""

# --- Routes ---

@app.route("/")
def index():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and user["password"] == password:
            session["user"] = username
            session["role"] = user["role"]
            session["fullname"] = user["fullname"]
            return redirect(request.args.get("next", url_for("wiki_home")))
        elif not user:
            error = "User not found"
        else:
            error = "Incorrect password"
    return render_template_string("""<!DOCTYPE html><html><head><title>Login — Boreas Intranet</title>
<style>""" + BASE_STYLE + """</style></head><body>
<div class="container">
<h1>Boreas Systems — Intranet Login</h1>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="POST">
<label>Username:</label><input name="username" type="text">
<label>Password:</label><input name="password" type="password">
<input type="submit" value="Login">
</form>
<p><a href="/forgot">Forgot password?</a></p>
</div></body></html>""", error=error)


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    message = None
    if request.method == "POST":
        username = request.form.get("username", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user:
            message = f"Password reset link sent to {username}@boreas.local"
        else:
            message = "User not found in the system"
    return render_template_string("""<!DOCTYPE html><html><head><title>Forgot Password</title>
<style>""" + BASE_STYLE + """</style></head><body>
<div class="container">
<h1>Forgot Password</h1>
{% if message %}<p>{{ message }}</p>{% endif %}
<form method="POST">
<label>Username:</label><input name="username" type="text">
<input type="submit" value="Reset Password">
</form>
<p><a href="/login">Back to login</a></p>
</div></body></html>""", message=message)


@app.route("/status")
def status():
    uptime = int(time.time() - START_TIME)
    content = f"""<h1>Server Status</h1>
<table>
<tr><td>Hostname</td><td>{platform.node()}</td></tr>
<tr><td>Python</td><td>{platform.python_version()}</td></tr>
<tr><td>Platform</td><td>{platform.platform()}</td></tr>
<tr><td>Uptime</td><td>{uptime}s</td></tr>
</table>"""
    return render_template_string(LAYOUT, title="Status", content=content, session=session)


@app.route("/.env")
@app.route("/config.bak")
def config_leak():
    config = f"""# Boreas Intranet Configuration
# DO NOT EXPOSE THIS FILE

DATABASE_URL=sqlite:///intranet.db
SECRET_KEY=boreas-internal-2025-xk9m
ADMIN_PASSWORD=admin
API_KEY={FLAG_7}

# Database credentials for research DB
RESEARCH_DB_HOST=researchdb.boreas.local
RESEARCH_DB_USER=lab_general
RESEARCH_DB_PASS=LabGen2025!
"""
    return config, 200, {"Content-Type": "text/plain"}


@app.route("/wiki")
@app.route("/wiki/home")
@login_required
def wiki_home():
    db = get_db()
    page = db.execute("SELECT * FROM wiki_pages WHERE slug = 'home' AND draft = 0").fetchone()
    return render_template_string(LAYOUT, title="Wiki", content=page["content"], session=session)


@app.route("/wiki/<slug>")
@login_required
def wiki_page(slug):
    db = get_db()
    page = db.execute("SELECT * FROM wiki_pages WHERE slug = ? AND draft = 0", (slug,)).fetchone()
    if not page:
        abort(404)
    return render_template_string(LAYOUT, title=page["title"], content=page["content"], session=session)


@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    db = get_db()
    pages = db.execute("SELECT slug, title, draft FROM wiki_pages ORDER BY draft DESC, title").fetchall()
    users = db.execute("SELECT username, role, fullname FROM users ORDER BY username").fetchall()
    content = "<h1>Admin Panel</h1><h2>Wiki Pages</h2><table><tr><th>Slug</th><th>Title</th><th>Status</th></tr>"
    for p in pages:
        status = "DRAFT" if p["draft"] else "Published"
        content += f'<tr><td><a href="/admin/page/{p["slug"]}">{p["slug"]}</a></td><td>{p["title"]}</td><td>{status}</td></tr>'
    content += "</table><h2>Users</h2><table><tr><th>Username</th><th>Role</th><th>Name</th></tr>"
    for u in users:
        content += f'<tr><td>{u["username"]}</td><td>{u["role"]}</td><td>{u["fullname"]}</td></tr>'
    content += "</table>"
    return render_template_string(LAYOUT, title="Admin", content=content, session=session)


@app.route("/admin/page/<slug>")
@login_required
@admin_required
def admin_page_view(slug):
    db = get_db()
    page = db.execute("SELECT * FROM wiki_pages WHERE slug = ?", (slug,)).fetchone()
    if not page:
        abort(404)
    content = f'<h1>{page["title"]}</h1><p><em>Status: {"DRAFT" if page["draft"] else "Published"}</em></p>'
    content += page["content"]
    return render_template_string(LAYOUT, title=page["title"], content=content, session=session)


@app.route("/search", methods=["GET", "POST"])
@login_required
def search():
    results = []
    query = ""
    if request.method == "POST":
        query = request.form.get("q", "")
        db = get_db()
        # DELIBERATELY VULNERABLE — SQL injection via string concatenation
        try:
            sql = f"SELECT slug, title, content FROM wiki_pages WHERE title LIKE '%{query}%' OR content LIKE '%{query}%'"
            results = db.execute(sql).fetchall()
        except Exception as e:
            results = [{"slug": "error", "title": "Error", "content": str(e)}]

    content = """<h1>Search Wiki</h1>
<form method="POST" class="search-form">
<input name="q" type="text" value="{{ query }}" placeholder="Search...">
<input type="submit" value="Search">
</form>"""
    if results:
        content += "<h2>Results</h2><ul>"
        for r in results:
            content += f'<li><a href="/wiki/{r["slug"]}">{r["title"]}</a></li>'
        content += "</ul>"
    elif query:
        content += "<p>No results found.</p>"
    return render_template_string(LAYOUT, title="Search", content=content, session=session, query=query)


@app.route("/download")
@login_required
def download():
    """DELIBERATELY VULNERABLE — path traversal via file parameter."""
    filename = request.args.get("file", "")
    if not filename:
        return "Usage: /download?file=document.pdf", 400
    # No sanitization — allows ../../etc/passwd
    filepath = os.path.join("/var/www/docs", filename)
    try:
        return send_file(filepath)
    except FileNotFoundError:
        abort(404)


def main():
    init_db()
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)


if __name__ == "__main__":
    main()
