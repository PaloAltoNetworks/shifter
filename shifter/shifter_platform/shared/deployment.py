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

import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

__all__ = ["resolve_audit_deployment_scope", "resolve_deployment_scope"]

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


def resolve_audit_deployment_scope() -> str:
    """Return the stable identity used by the tamper-evident audit chain.

    Deployed runtimes must receive an explicit identity from their cloud
    renderer. Local development and tests may use the deterministic sentinel,
    while an older GCP deployment remains safely identified by its project.
    """
    explicit = str(getattr(settings, "AUDIT_DEPLOYMENT_SCOPE", "") or "").strip()
    if explicit:
        return explicit

    inherited = resolve_deployment_scope()
    if inherited != _UNSCOPED_DEPLOYMENT:
        return inherited

    deployed_secret_refs = (
        "DB_SECRET_ID",
        "DB_SECRET_ARN",
        "APP_SECRET_ID",
        "APP_SECRET_ARN",
    )
    if any(os.environ.get(name, "").strip() for name in deployed_secret_refs):
        raise ImproperlyConfigured("AUDIT_DEPLOYMENT_SCOPE is required for deployed audit logging")
    return inherited
