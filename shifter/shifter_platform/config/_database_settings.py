"""Database connection and SECRET_KEY-rotation settings.

Split out of ``config.settings`` to keep that module under Sonar S104's
500-line cap (the same split pattern as the other ``config/_*.py`` modules).
Re-exported via ``from config._database_settings import *`` so
``config.settings.DATABASES`` / ``SECRET_KEY_FALLBACKS`` continue to resolve.

The ``DB_IAM_AUTH`` path (issue #159) connects with an RDS IAM token instead of
a stored password; see ``config.db_backends.rds_iam``. SSL is enforced because
RDS rejects IAM authentication over an unencrypted link.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from config._runtime_env import required_runtime_env

__all__ = [
    "DATABASES",
    "SECRET_KEY_FALLBACKS",
    "SECRET_KEY_FALLBACKS_MAX",
    "parse_secret_key_fallbacks",
]

_BASE_DIR = Path(__file__).resolve().parent.parent

# Maximum number of previous signing keys honoured during a SECRET_KEY
# rotation. Bounded so a stale/oversized fallback list cannot turn every
# signature check into an unbounded scan.
SECRET_KEY_FALLBACKS_MAX = 5


def parse_secret_key_fallbacks(raw: str) -> list[str]:
    """Parse the ``DJANGO_SECRET_KEY_FALLBACKS`` value into a bounded list.

    Accepts a JSON array of strings (the shape the entrypoint hydrates from the
    app secret bundle) and falls back to newline-separated values. Older
    SECRET_KEYs may contain commas, so newlines (not commas) separate the
    fallback form. Returns at most ``SECRET_KEY_FALLBACKS_MAX`` non-empty keys.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    keys: list[str]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        keys = [line.strip() for line in raw.splitlines()]
    else:
        if not isinstance(parsed, list):
            raise ValueError("DJANGO_SECRET_KEY_FALLBACKS JSON must be an array of strings")
        keys = [str(item).strip() for item in parsed]
    keys = [key for key in keys if key]
    if len(keys) > SECRET_KEY_FALLBACKS_MAX:
        raise ValueError(f"DJANGO_SECRET_KEY_FALLBACKS has {len(keys)} keys; the maximum is {SECRET_KEY_FALLBACKS_MAX}")
    return keys


# Previous signing keys kept valid during a SECRET_KEY rotation so existing
# signed sessions/cookies survive the rollout (zero forced logout). Empty in
# steady state; populated from the app secret bundle only while rotating.
SECRET_KEY_FALLBACKS = parse_secret_key_fallbacks(os.environ.get("DJANGO_SECRET_KEY_FALLBACKS", ""))


def _build_databases() -> dict[str, dict[str, object]]:
    """Return the DATABASES setting (SQLite under TESTING, else PostgreSQL)."""
    if os.environ.get("TESTING") == "1":
        return {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": _BASE_DIR / "db.sqlite3",
            }
        }

    # When DB_IAM_AUTH is enabled the running app connects with an RDS IAM
    # token instead of a stored password. The entrypoint turns this on for the
    # AWS runtime *after* migrations have run as the password-authenticated
    # owner, so migrations keep using the stock backend and the runtime
    # connection holds no long-lived password. DB_SSLMODE defaults to
    # "require" (encrypted; the private-VPC RDS is not publicly reachable) and
    # can be raised to "verify-full" with DB_SSL_ROOT_CERT pointing at the RDS
    # CA bundle.
    iam_auth = os.environ.get("DB_IAM_AUTH", "false").lower() == "true"
    options: dict[str, object] = {"connect_timeout": 10}
    if iam_auth:
        engine = "config.db_backends.rds_iam"
        options["sslmode"] = os.environ.get("DB_SSLMODE", "require")
        ssl_root_cert = os.environ.get("DB_SSL_ROOT_CERT", "").strip()
        if ssl_root_cert:
            options["sslrootcert"] = ssl_root_cert
    else:
        engine = "django.db.backends.postgresql"
    name = required_runtime_env("DB_NAME", dev_default="shifter")
    user = required_runtime_env("DB_USER", dev_default="postgres")
    host = required_runtime_env("DB_HOST", dev_default="localhost")
    port = required_runtime_env("DB_PORT", dev_default="5432")
    password = None if iam_auth else required_runtime_env("DB_PASSWORD", dev_default="postgres")
    return {
        "default": {
            "ENGINE": engine,
            "NAME": name,
            "USER": user,
            # Ignored under IAM auth (the backend mints a token); retained for
            # the password path (local/dev and the migration owner).
            "PASSWORD": password,
            "HOST": host,
            "PORT": port,
            # Connection settings (can tune CONN_MAX_AGE for connection reuse)
            "CONN_MAX_AGE": 0,
            "OPTIONS": options,
        }
    }


DATABASES = _build_databases()
