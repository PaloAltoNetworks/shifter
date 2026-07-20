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

#: Shifter's honest provisioning capability envelope (issue #1563: a realizability
#: ledger, not an aspiration). Shifter provisions virtual machine instances
#: (EC2 / GDC / GCE) running Linux and Windows guests, realizes authored networks
#: (``switch`` nodes) as backend networks/subnets, realizes authored node ACLs as
#: backend firewall rules, and realizes authored composition as guest effect:
#: ``file`` and ``directory`` content placements, feature bindings, and account
#: placements (groups/shell/home/disabled/auth_method) plus range-local Active
#: Directory accounts and SPNs. Every declared term must be backed by a real
#: guest effect (ADR-031 / ADR-032); a term realized only structurally or as a
#: marker file is dropped until its sibling issue lands genuine realization plus
#: cross-boundary evidence. ``file`` and ``directory`` are re-declared by #1564:
#: every admitted shape now has a genuine guest effect -- an inline ``text`` file
#: is written by the guest bootstrap, an empty ``directory`` is created, and a
#: source-backed ``file`` / ``directory`` is genuinely delivered into the guest
#: (materialized from the digest-verified pack, promoted content-addressed to
#: object storage, transferred over the authenticated guest channel, and confirmed
#: by an in-guest digest readback that fails the range apply on mismatch,
#: ADR-032-R3 / ADR-034-R6). ``mail`` (no common provider) and ``dataset`` (its
#: item-only and generator-format shapes have no deterministic materializer +
#: readback yet) stay out entirely rather than admit an unrealized shape. ``switch``
#: is required for any networked scenario: the aces-sdl planner rejects every
#: network resource unless the backend declares switch support (matches the
#: libvirt/reference backends).
#: The apply-time account-feature realization gate (``shared.aces.realization_ledger``
#: consumed by ``shared.aces.composition_envelope``) is an INDEPENDENT evidence
#: envelope: re-declaring a term here does not by itself make a plan admissible.
#:
#: The ``constraints`` map qualifies ``switch``: Shifter's range-cell substrate is
#: IPv4-only across planning, addressing, firewall posture, and outputs, so the
#: backend realizes IPv4 networks only. ACES SDL accepts IPv6/dual-stack, so this
#: narrower support is published as ``network-address-family = ipv4-only`` (issue
#: #1568). IPv6-only and mixed IPv4/IPv6 topologies are unsupported and rejected at
#: admission (``shared.aces.runtime_target``); the provisioner ``_usable_host_ips``
#: check is the separate backstop for persisted/replayed plans. The key is
#: provider-neutral by design -- the publication guard forbids provider/subnet/CIDR
#: detail in the manifest.
SHIFTER_PROVISIONER_CAPABILITIES = ProvisionerCapabilities(
    name="shifter-provisioner",
    supported_node_types=frozenset({"vm", "switch"}),
    supported_os_families=frozenset({"linux", "windows"}),
    supported_content_types=frozenset({"file", "directory"}),
    supported_account_features=frozenset({"groups", "shell", "home", "disabled", "auth_method", "spn"}),
    # #1561 realizes the bounded first ACES identity-domain profile: one
    # range-local Windows AD controller, Windows member joins, domain accounts,
    # uniqueness-preserving SPN registration, and directory readback.
    supported_domain_profiles=frozenset({"active_directory"}),
    max_total_nodes=None,
    supports_acls=True,
    supports_accounts=True,
    constraints={"network-address-family": "ipv4-only"},
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
