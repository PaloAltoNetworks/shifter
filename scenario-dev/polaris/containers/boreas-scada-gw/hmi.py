"""SCADA HMI front-end — Flask app backed by pymodbus-served registers.

The HMI requires an admin password (the scada-admin user) which is fetched
from an env-supplied credential. Participants reach it via the scada-net
zone (post-pivot through A15).
"""

from __future__ import annotations

import os
from flask import Flask, request, Response

app = Flask(__name__)

HMI_ADMIN_USER = os.environ.get("HMI_ADMIN_USER", "scada-admin")
HMI_ADMIN_PASSWORD = os.environ.get("HMI_ADMIN_PASSWORD", "change-me")


def _auth() -> bool:
    auth = request.authorization
    if not auth:
        return False
    return auth.username == HMI_ADMIN_USER and auth.password == HMI_ADMIN_PASSWORD


@app.route("/")
def index() -> Response:
    if not _auth():
        return Response(
            "auth required",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="scada-hmi"'},
        )
    return Response(
        "<html><body><h1>SCADA HMI</h1><p>System status: NOMINAL</p></body></html>",
        content_type="text/html",
    )


@app.route("/api/status")
def status() -> Response:
    if not _auth():
        return Response('{"error":"auth"}', status=401, content_type="application/json")
    return Response('{"thermal":"nominal","interlock":"armed"}', content_type="application/json")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
