"""Minimal Boreas intranet Flask app — intentionally vulnerable.

Exposes:

* ``/search`` — UNION-based SQL injection against a seeded users table.
* ``/download?file=``  — path traversal LFI.
* ``/.env`` — served as a static file (information disclosure).
* ``/`` — landing page.
* ``/wiki/<page>`` — static pages served from /srv/intranet/wiki/.

The seeded .env and wiki pages are delivered via the backend's volume mount
at runtime; the app reads them from the filesystem on each request.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import Flask, request, send_from_directory, Response

app = Flask(__name__)

DB_PATH = os.environ.get("INTRANET_DB", "/var/lib/intranet/intranet.sqlite")
ENV_PATH = "/srv/intranet/.env"
WIKI_DIR = "/srv/intranet/wiki"


def _ensure_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, password_hash TEXT)"
        )
        cur = conn.execute("SELECT COUNT(*) FROM users")
        (count,) = cur.fetchone()
        if count == 0:
            conn.executemany(
                "INSERT INTO users (name, password_hash) VALUES (?, ?)",
                [
                    ("v.harlan", "sha1$placeholder$"),
                    ("e.vasik", "sha1$placeholder$"),
                    ("m.webb", "sha1$placeholder$"),
                    ("admin", "sha1$placeholder$"),
                ],
            )
        conn.commit()
    finally:
        conn.close()


@app.route("/")
def index() -> str:
    return """
    <html><body>
      <h1>Boreas Systems Intranet</h1>
      <ul>
        <li><a href="/wiki/index">Wiki</a></li>
        <li><a href="/search?q=">Search</a></li>
      </ul>
    </body></html>
    """


@app.route("/search")
def search() -> Response:
    # Intentional SQL injection: query string concatenated directly.
    q = request.args.get("q", "")
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(f"SELECT id, name FROM users WHERE name LIKE '%{q}%'")
        rows = cur.fetchall()
    finally:
        conn.close()
    html = "<ul>" + "".join(f"<li>{r[0]}: {r[1]}</li>" for r in rows) + "</ul>"
    return Response(html, content_type="text/html")


@app.route("/download")
def download() -> Response:
    # Intentional path traversal: no sanitisation.
    filename = request.args.get("file", "")
    try:
        with open(filename, "rb") as f:
            data = f.read()
        return Response(data, content_type="application/octet-stream")
    except FileNotFoundError:
        return Response("not found", status=404)


@app.route("/.env")
def dotenv() -> Response:
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            return Response(f.read(), content_type="text/plain")
    except FileNotFoundError:
        return Response("", content_type="text/plain")


@app.route("/wiki/<page>")
def wiki(page: str) -> Response:
    try:
        return send_from_directory(WIKI_DIR, f"{page}.html")
    except FileNotFoundError:
        return Response(f"no wiki page: {page}", status=404)


if __name__ == "__main__":
    _ensure_db()
    app.run(host="0.0.0.0", port=80)
