"""Server-owned deployment scope for the public retry identity (#2086, ADR-063-R1).

One BigRAE deployment is one customer security/administration boundary backed by
one PostgreSQL database and one cloud project (ADR-054). The deployment scope is
the strongest stable, server-owned *resource-ownership* identity available -- the
cloud project, else a configured deployment name -- and is deliberately NOT a
hostname, ``ENVIRONMENT`` label, workspace UUID, or catalog deployment id (those
are not stable resource-ownership boundaries). It is recorded on every retry
binding so a database restored or cloned into a different deployment is detected
before its bindings dispatch against the original deployment's resources.
"""

from __future__ import annotations

from django.conf import settings

__all__ = ["resolve_deployment_scope"]

# Stable, non-empty fallback for environments with no cloud project configured
# (tests, local dev). Never used where a real GCP project or deployment name is
# set, so it cannot mask a production identity.
_UNSCOPED_DEPLOYMENT = "shifter-local-deployment"


def resolve_deployment_scope() -> str:
    """Return the server-owned stable deployment namespace (ADR-063-R1)."""
    for attr in ("GCP_PROJECT_ID", "WARM_POOL_DEPLOYMENT_NAME"):
        value = str(getattr(settings, attr, "") or "").strip()
        if value:
            return value
    return _UNSCOPED_DEPLOYMENT
