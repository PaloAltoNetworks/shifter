#!/usr/bin/env python3
"""daily_integration_report.py — Priya Shah's daily report generator.

Pulls unclassified research metrics from compartment_a and compartment_c,
rsyncs report artifacts from the engineering workstation, and POSTs a
summary to the internal reporting API. Scheduled via cron every morning
at 06:30 UTC.

The auth token for the reporting API is stored in ~/.reports/ANALYST_TOKEN
(deliberately separate from the .pgpass / SSH key so the individual
credentials can be rotated without touching the token).
"""
import os
import subprocess
from pathlib import Path

HOME = Path.home()

# Postgres credential comes from ~/.pgpass automatically.
PG_HOST = "researchdb.boreas.local"
PG_USER = "lab_general"
PG_DB = "postgres"

# SSH config alias — see ~/.ssh/config for the eng-ws01 entry.
ENG_HOST = "eng-ws01"
ENG_REMOTE_DIR = "/opt/builds/latest"
LOCAL_REPORTS = HOME / "reports"

# Reporting API token lives in a separate file so credentials are
# rotatable independently.
TOKEN_FILE = HOME / ".reports" / "ANALYST_TOKEN"


def fetch_metrics():
    """Pull today's metric row counts from compartment_a + compartment_c."""
    cmd = [
        "psql", "-h", PG_HOST, "-U", PG_USER, "-d", PG_DB,
        "-A", "-t", "-c",
        "SELECT 'specs', COUNT(*) FROM compartment_a.structural_specs "
        "UNION ALL SELECT 'assembly', COUNT(*) FROM compartment_c.assembly_log;"
    ]
    return subprocess.check_output(cmd, text=True)


def pull_report_artifacts():
    """rsync the published artifacts from the engineering workstation."""
    LOCAL_REPORTS.mkdir(exist_ok=True)
    subprocess.run([
        "rsync", "-av", "--delete",
        f"{ENG_HOST}:{ENG_REMOTE_DIR}/",
        str(LOCAL_REPORTS / "eng-latest") + "/",
    ], check=True)


def auth_token():
    return TOKEN_FILE.read_text().strip()


def main():
    metrics = fetch_metrics()
    pull_report_artifacts()
    token = auth_token()
    print(f"[daily_integration_report] metrics:\n{metrics}")
    print(f"[daily_integration_report] token (first 8 chars): {token[:8]}...")
    print("[daily_integration_report] ready to POST summary to reporting API")


if __name__ == "__main__":
    main()
