"""Shifter's ``provisioning-only`` RAES backend manifest (issue #1261).

This module is the canonical source for Shifter's RAES ``backend-manifest-v2``
capability declaration. It builds the manifest from the published ``raes``
contract models so the declaration is validated against the real RAES contract /
profile tooling rather than a Shifter-local approximation (see
``docs/adr/index.yaml`` and the
design source ``...-preflight-1233.md``).

Scope (publication-only slice):

- The only backend profile claim is ``provisioning-only``. Shifter has existing
  orchestration, CTF, experiment, Mission Control, and status surfaces, but they
  are product-specific contracts today, not RAES orchestrator / evaluator /
  participant-runtime / observation protocol implementations. They stay absent
  from the manifest until a later slice adds the required RAES contracts and
  conformance evidence.
- The manifest is a capability/profile source, not runtime configuration. It is
  not Shifter settings, an env file, Terraform input, a Kubernetes manifest, a
  scenario template, or a source of launchability.
- Backend-owned realization (Terraform, cloud provider choices, SSM/bootstrap,
  image ids, machine sizes, subnet allocation, NGFW attachment, secret lookup)
  stays backend-owned. The manifest discloses only coarse provisioning
  capabilities, never provider-specific realization detail.

The ``raes`` dependency was dev/test-scoped through the publication-only
slice (#1261), when nothing at runtime imported this module. The RuntimeTarget
adapter (#1262, :mod:`shared.raes.runtime_target`) imports this module's
builder to construct a live ``RuntimeTarget``, so ``raes`` is now a
``[project]`` runtime dependency.
"""

from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from typing import Any

from raes.artifact_requirements import ArtifactMechanismProfile
from raes_backend_protocols.capabilities import (
    BackendCapabilitySet,
    BackendManifest,
    OperatingSystemCompatibility,
    ProvisionerCapabilities,
)
from raes_backend_protocols.manifest import backend_manifest_payload
from raes_contracts.apparatus import (
    ApparatusIdentity,
    ConceptBinding,
    RealizationObservationCapability,
    RealizationSupportDeclaration,
)
from raes_contracts.contracts import ArtifactAcquisitionTimingModel, ArtifactMechanismCapability
from raes_contracts.realization_envelope import BackendRealizationEnvelopeModel
from raes_contracts.vocabulary import ObservationStrength, RealizationSupportMode, RealizationVerificationScope

from shared.raes.contracts import (
    SHIFTER_BACKEND_NAME,
    SHIFTER_BACKEND_PROFILE,
    SHIFTER_CONFIGURED_CONTRACT_VERSIONS,
    SHIFTER_SUPPORTED_CONTRACT_VERSIONS,
)
from shared.raes.realization import OPERATING_SYSTEMS

__all__ = [
    "SHIFTER_BACKEND_NAME",
    "SHIFTER_BACKEND_PROFILE",
    "SHIFTER_SUPPORTED_CONTRACT_VERSIONS",
    "create_shifter_backend_manifest",
    "exact_artifact_profile",
    "render_shifter_backend_manifest_payload",
    "shifter_artifact_mechanism_capabilities",
    "shifter_backend_apparatus",
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
#: is required for any networked scenario: the raes planner rejects every
#: network resource unless the backend declares switch support (matches the
#: libvirt/reference backends).
#: The public RAES ``RealizerConfigurationModel`` consumed by
#: ``shared.raes.composition_envelope`` is the INDEPENDENT apply-time evidence
#: surface: re-declaring a term here does not by itself make a plan admissible.
#:
#: The ``constraints`` map qualifies ``switch``: Shifter's range-cell substrate is
#: IPv4-only across planning, addressing, firewall posture, and outputs, so the
#: backend realizes IPv4 networks only. RAES SDL accepts IPv6/dual-stack, so this
#: narrower support is published as ``network-address-family = ipv4-only`` (issue
#: #1568). IPv6-only and mixed IPv4/IPv6 topologies are unsupported and rejected at
#: admission (``shared.raes.runtime_target``); the provisioner ``_usable_host_ips``
#: check is the separate backstop for persisted/replayed plans. The key is
#: provider-neutral by design -- the publication guard forbids provider/subnet/CIDR
#: detail in the manifest.
SHIFTER_PROVISIONER_CAPABILITIES = ProvisionerCapabilities(
    name="shifter-provisioner",
    supported_node_types=frozenset({"compute", "switch"}),
    supported_os_families=frozenset({"linux", "windows"}),
    operating_systems=tuple(
        OperatingSystemCompatibility(row["family"], row["distribution"], frozenset(row["versions"]))
        for row in OPERATING_SYSTEMS
    ),
    supported_content_types=frozenset({"file", "directory"}),
    supported_account_features=frozenset({"groups", "shell", "home", "disabled", "auth_method", "spn"}),
    # #1561 realizes the bounded first RAES identity-domain profile: one
    # range-local Windows AD controller, Windows member joins, domain accounts,
    # uniqueness-preserving SPN registration, and directory readback.
    supported_domain_profiles=frozenset({"active_directory"}),
    # Completion carries one OS and substrate observation per instance. Keep
    # provider mutation within the closed evidence transport admitted below.
    max_total_nodes=64,
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


def create_shifter_backend_manifest(
    *, realization_envelope: BackendRealizationEnvelopeModel | None = None, **_config: Any
) -> BackendManifest:
    """Return Shifter's ``provisioning-only`` RAES backend manifest.

    The generic published manifest declares exactly the ``provisioning-only``
    profile's required contracts. A runtime-selected ``realization_envelope``
    adds that contract to the configured target. Both variants claim no
    orchestrator, evaluator, participant-runtime, or observation capability, so
    they infer as ``BackendCapabilityProfile.PROVISIONING_ONLY``.

    Accepts and ignores arbitrary keyword config so it satisfies
    ``raes_runtime.registry.BackendRegistry``'s ``manifest_factory(**config)``
    contract -- the registry always calls the manifest factory with whatever
    config the caller passed to ``registry.create()``/``registry.manifest()``
    (e.g. the ``port`` kwarg ``shared.raes.runtime_target`` passes for the
    components factory). ``realization_envelope`` is the one consumed setting.
    """
    return BackendManifest(
        name=SHIFTER_BACKEND_NAME,
        version=_current_backend_version(),
        supported_contract_versions=(
            SHIFTER_CONFIGURED_CONTRACT_VERSIONS
            if realization_envelope is not None
            else SHIFTER_SUPPORTED_CONTRACT_VERSIONS
        ),
        compatible_processors=frozenset({"raes-reference-processor"}),
        realization_envelope=realization_envelope,
        concept_bindings=(
            ConceptBinding(scope="capabilities.provisioner.supported_node_types", family="assets"),
            ConceptBinding(scope="capabilities.provisioner.supported_os_families", family="assets"),
        ),
        realization_support=(
            RealizationSupportDeclaration(
                domain="runtime-realization",
                support_mode=RealizationSupportMode.CONSTRAINED,
                supported_constraint_kinds=frozenset({"node-type", "os-family", "source-artifact"}),
                supported_exact_requirement_kinds=frozenset({"declared-capability-match", "source-artifact"}),
                artifact_mechanisms=shifter_artifact_mechanism_capabilities(),
                observation_capabilities={
                    "operating-system": RealizationObservationCapability(
                        RealizationVerificationScope.CONFIGURATION, ObservationStrength.GUEST_OBSERVED
                    ),
                    "compute-substrate": RealizationObservationCapability(
                        RealizationVerificationScope.CONFIGURATION, ObservationStrength.DAEMON_OBSERVED
                    ),
                },
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


def shifter_backend_apparatus() -> ApparatusIdentity:
    """Return the selected-backend identity recorded in artifact satisfaction disclosures.

    The version is normalised to ``0.0.0`` to match the deterministic published
    manifest identity (:func:`render_shifter_backend_manifest_payload`).
    """
    return ApparatusIdentity(name=SHIFTER_BACKEND_NAME, version="0.0.0")


# Shifter's artifact-satisfaction mechanism profile (#1580, ADR-034-R2/R8). The
# mechanism NAME is the upstream governed vocabulary; the profile id + version
# identify Shifter's one realization contract (the tenant image registry) and the
# digest binds that exact contract (a deterministic hash of the identity, so it
# changes only when the contract does). Shifter declares ONLY ``exact-artifact``:
# an exact requirement is satisfied when the registry owns the exact authored
# identity (all four ArtifactIdentity fields) with recorded admission evidence.
# ``constrained`` (candidate + constraint verification) is NOT declared -- it needs
# an independent constraint verifier Shifter does not yet have, so a constrained
# requirement fails closed rather than trusting author-declared membership (codex
# #1580 review). Open realization and dynamic composition stay undeclared too.
_EXACT_ARTIFACT_MECHANISM = "exact-artifact"
_INVENTORY_PROFILE = "shifter-backend-inventory"
_INVENTORY_VERSION = "1"


def exact_artifact_profile() -> ArtifactMechanismProfile:
    """Return Shifter's ``exact-artifact`` mechanism profile with a stable digest."""
    identity = f"{_EXACT_ARTIFACT_MECHANISM}/{_INVENTORY_PROFILE}/{_INVENTORY_VERSION}"
    return ArtifactMechanismProfile(
        mechanism=_EXACT_ARTIFACT_MECHANISM,
        profile=_INVENTORY_PROFILE,
        version=_INVENTORY_VERSION,
        digest="sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
    )


def shifter_artifact_mechanism_capabilities() -> tuple[ArtifactMechanismCapability, ...]:
    """Return the artifact-satisfaction mechanisms Shifter's backend can execute.

    Exactly one, truthfully: ``exact-artifact``. The genuine adapter is the tenant
    image registry carrying the complete portable ``ArtifactIdentity`` + admission
    evidence (:class:`engine.models.RaesImageMapping`, #1580); an ``exact``
    requirement is satisfied when the registry owns that exact identity. Acquisition
    is ``local-lookup`` (the image is already present -- nothing is pulled, copied,
    or built on the provisioning path) and timing is ``backend-preparation`` (never
    realization), which keeps long-running image construction off the critical path.
    Constrained, open, and dynamic-composition mechanisms stay undeclared
    (fail-closed) until their own verifiers/adapters exist.
    """
    return (
        ArtifactMechanismCapability(
            mechanism=exact_artifact_profile(),
            supported_requirement_kinds=["source-artifact"],
            supported_routes=[ArtifactAcquisitionTimingModel(acquisition="local-lookup", timing="backend-preparation")],
        ),
    )


def render_shifter_backend_manifest_payload() -> dict[str, Any]:
    """Return the JSON-serialisable ``backend-manifest-v2`` payload for Shifter.

    The ``version`` field is normalised to ``0.0.0`` so the published artifact is
    deterministic and does not churn with the shifter-platform package version.
    """
    payload = backend_manifest_payload(create_shifter_backend_manifest())
    payload["identity"]["version"] = "0.0.0"
    return payload
