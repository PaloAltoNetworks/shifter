"""Provisional registry of known Shifter backends.

The root installation config (:mod:`installation.schema`) validates the ``backend``
selector and the ``deployment.profile``/``backend`` combination against the data
here. This is intentionally a small, hard-coded set covering the backends that have
real infrastructure in the repository today; the backend *bundle* contract and a
proper registry land in issue #1113 and supersede this module. The ``local`` backend
is defined by issue #1119.

Keeping the contents minimal keeps the root schema decoupled from per-backend
settings: the root parser only needs to know which backend names exist and which
deployment profiles each one supports. Everything else (required settings, generated
outputs, infrastructure entrypoints, health checks, docs) belongs to the backend
bundle, not here.
"""

from __future__ import annotations

#: The single source of truth: each known backend mapped to the deployment profiles
#: it supports. Issue #1113 replaces this dict with the backend bundle registry; the
#: schema validates ``backend``, ``deployment.profile``, and the profile/backend
#: combination entirely against this data, so a future backend or profile only needs
#: to be added here.
ALLOWED_PROFILES: dict[str, frozenset[str]] = {
    "aws": frozenset({"prod", "dev"}),
    "gcp": frozenset({"prod", "dev"}),
}

#: Backend names the root installation config currently accepts (derived).
KNOWN_BACKENDS: frozenset[str] = frozenset(ALLOWED_PROFILES)

#: Deployment profiles the schema understands at all, independent of backend (derived).
KNOWN_PROFILES: frozenset[str] = frozenset().union(*ALLOWED_PROFILES.values())
