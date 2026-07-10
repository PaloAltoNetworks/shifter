"""Guacamole connection and bootstrap runtime settings.

Extracted from ``config/settings.py`` to keep that module under the
500-line cap (Sonar S104). Reads the same environment variables as the
old inline block; importing this module has no side effects beyond
binding the module-level constants used in the re-export.
"""

from __future__ import annotations

import os

__all__ = [
    "GUACAMOLE_API_BASE_URL",
    "GUACAMOLE_BASE_URL",
    "GUACAMOLE_BOOTSTRAP_INLINE",
    "GUACAMOLE_BOOTSTRAP_PRUNE_BATCH_SIZE",
    "GUACAMOLE_BOOTSTRAP_PRUNE_INTERVAL_SECONDS",
    "GUACAMOLE_BOOTSTRAP_TTL_SECONDS",
    "GUACAMOLE_BOOTSTRAP_WORKERS",
    "GUACAMOLE_JSON_AUTH_SECRET",
]

# JSON auth secret key for signing RDP session URLs. Must match the
# JSON_SECRET_KEY configured in Guacamole's ECS task definition; a hex string
# key (64-character/256-bit preferred) stored in Secrets Manager.
GUACAMOLE_JSON_AUTH_SECRET = os.environ.get("GUACAMOLE_JSON_AUTH_SECRET", "")
# Public URL for browser (returned to client).
GUACAMOLE_BASE_URL = os.environ.get("GUACAMOLE_BASE_URL", "/guacamole")
# Internal URL for server-to-server API calls (defaults to base URL if not set).
GUACAMOLE_API_BASE_URL = os.environ.get("GUACAMOLE_API_BASE_URL", "") or GUACAMOLE_BASE_URL
# Bounded async bootstrap workers for Guacamole token creation. Each worker may
# hold a blocking Guacamole /api/tokens request, so keep this intentionally low
# and scale with portal instance count.
GUACAMOLE_BOOTSTRAP_WORKERS = int(os.environ.get("GUACAMOLE_BOOTSTRAP_WORKERS", "4"))
GUACAMOLE_BOOTSTRAP_TTL_SECONDS = int(os.environ.get("GUACAMOLE_BOOTSTRAP_TTL_SECONDS", "300"))
GUACAMOLE_BOOTSTRAP_INLINE = os.environ.get("GUACAMOLE_BOOTSTRAP_INLINE", "False").lower() == "true"
# Cadence and bounded batch size for the dedicated bootstrap pruning service
# (run_guacamole_bootstrap_prune). Non-secret integers; the prune deletes
# expired bootstrap rows so abandoned token URLs do not persist at rest.
GUACAMOLE_BOOTSTRAP_PRUNE_INTERVAL_SECONDS = int(os.environ.get("GUACAMOLE_BOOTSTRAP_PRUNE_INTERVAL_SECONDS", "60"))
GUACAMOLE_BOOTSTRAP_PRUNE_BATCH_SIZE = int(os.environ.get("GUACAMOLE_BOOTSTRAP_PRUNE_BATCH_SIZE", "500"))
