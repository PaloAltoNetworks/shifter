"""OpenFGA runtime binding for the S2 authorization stack (#2315).

The runtime receives store/model identifiers and paths to mounted secrets.  It
does not receive model/store administration credentials and never publishes a
model.  S8 will enable this binding after the protected surfaces are migrated.
"""

from __future__ import annotations

import os

OPENFGA_ENABLED = os.environ.get("OPENFGA_ENABLED", "false").strip().lower() == "true"
OPENFGA_API_URL = os.environ.get("OPENFGA_API_URL", "").strip()
OPENFGA_STORE_ID = os.environ.get("OPENFGA_STORE_ID", "").strip()
OPENFGA_MODEL_ID = os.environ.get("OPENFGA_MODEL_ID", "").strip()
OPENFGA_API_TOKEN_FILE = os.environ.get("OPENFGA_API_TOKEN_FILE", "").strip()
OPENFGA_CA_CERT_PATH = os.environ.get("OPENFGA_CA_CERT_PATH", "").strip()
OPENFGA_TIMEOUT_MS = int(os.environ.get("OPENFGA_TIMEOUT_MS", "1500"))

__all__ = [
    "OPENFGA_API_TOKEN_FILE",
    "OPENFGA_API_URL",
    "OPENFGA_CA_CERT_PATH",
    "OPENFGA_ENABLED",
    "OPENFGA_MODEL_ID",
    "OPENFGA_STORE_ID",
    "OPENFGA_TIMEOUT_MS",
]
