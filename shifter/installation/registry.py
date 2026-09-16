"""The Shifter backend bundle registry.

This is the single source of truth for which backends an OSS deployment can select
(PLAT-2002) and what each one exposes (the :mod:`installation.contract` shape,
PLAT-2003). The root schema (:mod:`installation.schema`) derives backend and profile
validation from the data here, and :mod:`installation.loader` runs each backend's
``settings`` and secret-reference checks against the selected bundle — so adding a
backend or a profile is a registry entry, not a schema change or a branch router. There
is exactly one such table in the repo; Django, workflows, bootstrap scripts, and CI
consume *this* one rather than maintaining their own.

The ``aws`` (#1116 / GH #728) and ``gcp`` (#1117 / GH #729) entries are both migrated
backend bundles, defined in :mod:`installation.bundle_aws` and
:mod:`installation.bundle_gcp` (split out for the SonarCloud S104 file-size budget and
backend symmetry, alongside the ``settings_*`` / ``runtime_inventory_*`` modules; shared
primitives live in :mod:`installation._bundle_common`). Each carries a closed
``settings_model`` (:class:`installation.settings_aws.AwsSettings` /
:class:`installation.settings_gcp.GcpBackendSettings`), machine-readable
``RequiredSecret.reference_pattern`` secret grammars, the full generated runtime-env
projection, the deployment profiles its deploy paths actually use, and the backend identity,
owned repo roots, required tools, validation checks, and portal health probe. Describing
these contracts does not move Terraform/state, rewrite workflows, or build a renderer —
those stay in their existing owners (branch-routing replacement is #730); constrained by
ADR-011-R5.

``range_egress`` is a *shared, cross-backend* platform setting owned and validated by
:mod:`installation.range_egress` (verbatim, non-secret CIDR diagnostics, #775). It is not a
backend-owned key, so the closed ``settings_model`` classes deliberately do not declare it;
the loader strips it out of ``settings`` and validates it separately for every backend. The
``local`` backend is #1119. Constrained by ADR-011.
"""

from __future__ import annotations

from .bundle_aws import AWS_BUNDLE
from .bundle_gcp import GCP_BUNDLE
from .contract import BackendBundle

# Re-exported so existing importers keep resolving ``installation.registry.AwsSettings``.
from .settings_aws import AwsSettings

__all__ = [
    "ALLOWED_PROFILES",
    "BACKEND_BUNDLES",
    "KNOWN_BACKENDS",
    "KNOWN_PROFILES",
    "AwsSettings",
    "get_backend_bundle",
]

#: The backend bundle registry: backend name -> bundle. Adding a backend is a new entry
#: here (plus its per-backend module and worked example under ``examples/``) and nothing else.
BACKEND_BUNDLES: dict[str, BackendBundle] = {
    AWS_BUNDLE.name: AWS_BUNDLE,
    GCP_BUNDLE.name: GCP_BUNDLE,
}


def get_backend_bundle(name: str) -> BackendBundle | None:
    """Return the backend bundle named ``name``, or ``None`` if no such backend exists."""
    return BACKEND_BUNDLES.get(name)


#: Backend names the root installation config accepts (derived from the registry).
KNOWN_BACKENDS: frozenset[str] = frozenset(BACKEND_BUNDLES)

#: Every deployment profile any backend supports (derived from the registry).
KNOWN_PROFILES: frozenset[str] = frozenset().union(*(bundle.supported_profiles for bundle in BACKEND_BUNDLES.values()))

#: Each backend mapped to the deployment profiles it supports (derived from the
#: registry). This is the lookup the root schema uses for the profile/backend
#: combination check; it carries over the ``ALLOWED_PROFILES`` data from the pre-#1113
#: ``installation.backends`` module unchanged.
ALLOWED_PROFILES: dict[str, frozenset[str]] = {
    name: bundle.supported_profiles for name, bundle in BACKEND_BUNDLES.items()
}
