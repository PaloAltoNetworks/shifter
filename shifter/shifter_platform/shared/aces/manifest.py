"""Shifter's ``provisioning-only`` ACES backend manifest (issue #1261).

This module is the canonical source for Shifter's ACES ``backend-manifest-v2``
capability declaration. It builds the manifest from the published ``aces-sdl``
contract models so the declaration is validated against the real ACES contract /
profile tooling rather than a Shifter-local approximation (see
``docs/architecture/aces-backend-manifest-publication-preflight-1261.md`` and the
design source ``...-preflight-1233.md``).

Scope (publication-only slice):

- The only backend profile claim is ``provisioning-only``. Shifter has existing
  orchestration, CTF, experiment, Mission Control, and status surfaces, but they
  are product-specific contracts today, not ACES orchestrator / evaluator /
  participant-runtime / observation protocol implementations. They stay absent
  from the manifest until a later slice adds the required ACES contracts and
  conformance evidence.
- The manifest is a capability/profile source, not runtime configuration. It is
  not Shifter settings, an env file, Terraform input, a Kubernetes manifest, a
  scenario template, or a source of launchability.
- Backend-owned realization (Terraform, cloud provider choices, SSM/bootstrap,
  image ids, machine sizes, subnet allocation, NGFW attachment, secret lookup)
  stays backend-owned. The manifest discloses only coarse provisioning
  capabilities, never provider-specific realization detail.

The ``aces-sdl`` dependency was dev/test-scoped through the publication-only
slice (#1261), when nothing at runtime imported this module. The RuntimeTarget
adapter (#1262, :mod:`shared.aces.runtime_target`) imports this module's
builder to construct a live ``RuntimeTarget``, so ``aces-sdl`` is now a
``[project]`` runtime dependency.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from typing import Any

from aces_backend_protocols.capabilities import (
    BackendCapabilitySet,
    BackendManifest,
    ProvisionerCapabilities,
)
from aces_backend_protocols.manifest import backend_manifest_payload
from aces_contracts.apparatus import ConceptBinding, RealizationSupportDeclaration
from aces_contracts.vocabulary import RealizationSupportMode

from shared.aces.contracts import (
    SHIFTER_BACKEND_NAME,
    SHIFTER_BACKEND_PROFILE,
    SHIFTER_SUPPORTED_CONTRACT_VERSIONS,
)

__all__ = [
    "SHIFTER_BACKEND_NAME",
    "SHIFTER_BACKEND_PROFILE",
    "SHIFTER_SUPPORTED_CONTRACT_VERSIONS",
    "create_shifter_backend_manifest",
    "render_shifter_backend_manifest_payload",
]

#: Shifter's honest provisioning capability envelope. Shifter provisions virtual
#: machine instances (EC2 / GDC) running Linux and Windows guests. Account,
#: ACL, and content-placement realization are not exposed as authored ACES
#: scenario semantics in this slice, so they stay off -- every declared term is
#: backed by real capability, so the manifest cannot over-claim.
SHIFTER_PROVISIONER_CAPABILITIES = ProvisionerCapabilities(
    name="shifter-provisioner",
    supported_node_types=frozenset({"vm"}),
    supported_os_families=frozenset({"linux", "windows"}),
    max_total_nodes=None,
    supports_acls=False,
    supports_accounts=False,
)


def _current_backend_version() -> str:
    """Return the installed shifter-platform version, or a sentinel if absent."""
    try:
        return distribution_version("shifter-platform")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def create_shifter_backend_manifest(**_config: Any) -> BackendManifest:
    """Return Shifter's ``provisioning-only`` ACES backend manifest.

    The manifest declares exactly the ``provisioning-only`` profile's required
    contracts and Shifter's honest provisioning capability envelope. It claims no
    orchestrator, evaluator, participant-runtime, or observation capability, so
    it infers as ``BackendCapabilityProfile.PROVISIONING_ONLY``.

    Accepts and ignores arbitrary keyword config so it satisfies
    ``aces_runtime.registry.BackendRegistry``'s ``manifest_factory(**config)``
    contract -- the registry always calls the manifest factory with whatever
    config the caller passed to ``registry.create()``/``registry.manifest()``
    (e.g. the ``port`` kwarg ``shared.aces.runtime_target`` passes for the
    components factory), even though this manifest itself takes no config.
    """
    return BackendManifest(
        name=SHIFTER_BACKEND_NAME,
        version=_current_backend_version(),
        supported_contract_versions=SHIFTER_SUPPORTED_CONTRACT_VERSIONS,
        compatible_processors=frozenset({"aces-reference-processor"}),
        concept_bindings=(
            ConceptBinding(scope="capabilities.provisioner.supported_node_types", family="assets"),
            ConceptBinding(scope="capabilities.provisioner.supported_os_families", family="assets"),
        ),
        realization_support=(
            RealizationSupportDeclaration(
                domain="runtime-realization",
                support_mode=RealizationSupportMode.CONSTRAINED,
                supported_constraint_kinds=frozenset({"node-type", "os-family"}),
                supported_exact_requirement_kinds=frozenset({"declared-capability-match"}),
                disclosure_kinds=frozenset(
                    {
                        "backend-manifest-v2",
                        "operation-status-v1",
                        "runtime-snapshot-v1",
                    }
                ),
            ),
        ),
        capabilities=BackendCapabilitySet(provisioner=SHIFTER_PROVISIONER_CAPABILITIES),
    )


def render_shifter_backend_manifest_payload() -> dict[str, Any]:
    """Return the JSON-serialisable ``backend-manifest-v2`` payload for Shifter.

    The ``version`` field is normalised to ``0.0.0`` so the published artifact is
    deterministic and does not churn with the shifter-platform package version.
    """
    payload = backend_manifest_payload(create_shifter_backend_manifest())
    payload["identity"]["version"] = "0.0.0"
    return payload
