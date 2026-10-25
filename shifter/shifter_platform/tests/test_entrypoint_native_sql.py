"""Exercise the real entrypoint across its secret-fetch/process boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def test_native_entrypoint_hydrates_app_secrets_without_fetching_database_passwords(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    dispatcher = binary / "python"
    dispatcher.write_text(
        f"#!{sys.executable}\n"
        "import json, os, subprocess, sys\n"
        "if sys.argv[1] == '-':\n"
        "    sys.stdin.read()\n"
        "    if sys.argv[2] != 'projects/synthetic-project/secrets/app': sys.exit(83)\n"
        "    print(json.dumps({'django_secret_key': 'synthetic-app-key', 'field_encryption_key': 'eA=='}))\n"
        "elif sys.argv[1] == '-c' and 'psycopg.connect(' in sys.argv[2]:\n"
        "    assert not os.environ.get('DB_PASSWORD')\n"
        "else:\n"
        f"    sys.exit(subprocess.call([{sys.executable!r}, *sys.argv[1:]]))\n"
    )
    dispatcher.chmod(0o700)
    capture = tmp_path / "capture.py"
    output = tmp_path / "observed.json"
    capture.write_text(
        "import json, os\nfrom pathlib import Path\n"
        f"Path({str(output)!r}).write_text(json.dumps({{k: os.environ.get(k) for k in "
        "['DJANGO_SECRET_KEY', 'DB_AUTH_MODE', 'DB_PASSWORD', 'PROVISIONER_DB_USER', 'PROVISIONER_DB_PASSWORD']}))\n"
    )
    result = subprocess.run(  # noqa: S603 -- fixed repository entrypoint with local synthetic process fixtures
        ["/bin/bash", str(ENTRYPOINT), sys.executable, str(capture)],
        env={
            "PATH": str(binary) + os.pathsep + os.defpath,
            "CLOUD_PROVIDER": "gcp",
            "DB_AUTH_MODE": "cloud-sql-proxy",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "5432",
            "DB_NAME": "shifter",
            "DB_USER": "synthetic-portal@synthetic-project.iam",
            "APP_SECRET_ID": "projects/synthetic-project/secrets/app",
            "SKIP_MIGRATIONS": "1",
            "SHIFTER_PROVISIONER_LAUNCHER": "true",
            "PROVISIONER_DB_HOST": "127.0.0.1",
            "PROVISIONER_DB_PORT": "5432",
            "PROVISIONER_DB_NAME": "shifter",
            "PROVISIONER_DB_USER": "synthetic-provisioner@synthetic-project.iam",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(output.read_text())
    assert observed["DJANGO_SECRET_KEY"] == "synthetic-app-key"
    assert observed["DB_AUTH_MODE"] == "cloud-sql-proxy"
    assert observed["DB_PASSWORD"] is None and observed["PROVISIONER_DB_PASSWORD"] is None
    assert observed["PROVISIONER_DB_USER"] == "synthetic-provisioner@synthetic-project.iam"
    assert "synthetic-app-key" not in result.stdout + result.stderr
