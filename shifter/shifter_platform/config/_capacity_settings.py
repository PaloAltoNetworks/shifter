"""Portal web capacity-metrics Django settings (#940).

Extracted from ``config/settings.py`` to keep that module under the 500-line cap
(Sonar S104), mirroring ``config/_oidc_settings.py``. These knobs configure the
per-worker ``Shifter/PortalCapacity`` emitter; the design contract lives in
``config/capacity_metrics.py`` and
``docs/architecture/portal-app-saturation-autoscaling-preflight-940.md``.

When enabled, each Uvicorn worker runs a daemon that publishes its in-flight HTTP
request concurrency, worker busy ratio, and terminal-session utilization to
CloudWatch so portal autoscaling and operators can see request-path saturation
that average EC2 CPU misses. ``PORTAL_WORKER_SOFT_CONCURRENCY`` is the busy-ratio
denominator (the soft concurrent-request target per worker; the portal serves ~4
serialized sync requests per worker, so the default sits a little above that).
``PORTAL_CAPACITY_NAME_PREFIX`` is the low-cardinality metric dimension and MUST
match the Terraform name_prefix so the CloudWatch alarms/dashboard match the
series; it is supplied by user_data.sh / deploy_portal.sh. The enable flag and
soft-concurrency are wired through SSM/tfvars like the #930 terminal knobs; the
publish interval is a stable operational default (env-overridable, not
SSM-provisioned).

Importing this module only binds the module-level constants re-exported by
``config.settings``.
"""

from __future__ import annotations

import os

__all__ = [
    "PORTAL_CAPACITY_METRICS_ENABLED",
    "PORTAL_CAPACITY_METRICS_INTERVAL_SECONDS",
    "PORTAL_CAPACITY_NAME_PREFIX",
    "PORTAL_WORKER_SOFT_CONCURRENCY",
]


def _int_env(name: str, default: int) -> int:
    """Parse an integer env var, failing loud on bad input.

    Mirrors ``config.settings._env_int`` but is defined here because importing it
    from ``config.settings`` would create an import cycle (settings imports this
    module).
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


PORTAL_CAPACITY_METRICS_ENABLED = os.environ.get("PORTAL_CAPACITY_METRICS_ENABLED", "False").lower() == "true"
PORTAL_CAPACITY_METRICS_INTERVAL_SECONDS = _int_env("PORTAL_CAPACITY_METRICS_INTERVAL_SECONDS", 60)
PORTAL_WORKER_SOFT_CONCURRENCY = _int_env("PORTAL_WORKER_SOFT_CONCURRENCY", 6)
PORTAL_CAPACITY_NAME_PREFIX = os.environ.get("PORTAL_CAPACITY_NAME_PREFIX", "").strip()
