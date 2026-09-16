"""Backend artifact inventory → availability facts for the resolution seam (#1580).

The tenant image registry (:class:`engine.models.RaesImageMapping`, evolved by
#1580 to carry a portable ``ArtifactIdentity`` + admission evidence) is the
backend-owned artifact inventory. This module turns those rows plus the authored
artifact requirements into the ``ArtifactRequirementAvailability`` facts the
:mod:`shared.raes.artifact_resolution` seam consumes -- it is the "Shifter owns
the facts, RAES owns the schema" boundary the Step 2.5 preflight named.

It is layer-clean and depends only on the upstream contracts + a provider-neutral
:class:`BackendArtifact` value the caller projects from its own registry rows, so
``shared.raes`` never imports ``engine``. It performs no I/O and evaluates no
semantics of its own: an artifact is *available* only when the backend owns it by
exact portable identity (digest), and a constrained requirement's constraints
count as satisfied only when an author-admitted candidate is present -- the author
already vouched that an admitted candidate conforms. Integrity and provenance
references are echoed straight from the owning registry row so a disclosure never
asserts trust the registry did not record (trust stays a separate decision, AC9).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from raes.artifact_requirements import ArtifactIdentity, ArtifactRequirement
from raes_contracts.apparatus import ApparatusIdentity
from raes_contracts.contracts import (
    ArtifactAcquisitionTimingModel,
    ArtifactMechanismCapability,
    ArtifactRequirementAvailability,
)

from shared.raes.artifact_binding import ArtifactBinding
from shared.raes.artifact_resolution import (
    ArtifactResolution,
    ArtifactResolutionStatus,
    resolve_artifact_requirement,
)
from shared.raes.prepared_artifacts import VerifiedMaterialization

__all__ = [
    "ArtifactRequirements",
    "ArtifactSatisfactionError",
    "BackendArtifact",
    "build_artifact_availability",
    "resolve_plan_artifact_bindings",
]

_NODE_RESOURCE_TYPE = "node"

# Public type for callers outside ``shared.raes``. It keeps the upstream RAES
# requirement class behind the repository's shared contract boundary.
ArtifactRequirements = Mapping[str, ArtifactRequirement]


class ArtifactSatisfactionError(Exception):
    """An authored artifact requirement could not be satisfied at launch (fail-closed)."""


@dataclass(frozen=True)
class BackendArtifact:
    """One portable artifact the backend owns, with its admission evidence + image.

    The identity is the *complete* portable ``ArtifactIdentity`` -- ``artifact_id``,
    ``version``, ``digest`` (canonical ``sha256:``), and ``media_type`` -- because an
    artifact is matched on all four, never on bytes (digest) alone: two distinct
    authored identities can share a digest, so a digest-only match could satisfy the
    wrong requirement. ``integrity_ref`` and ``provenance_ref`` are the verified
    evidence references the registry recorded when the mapping was admitted; both are
    required for the artifact to be admissibly available (the disclosure contract
    refuses less). ``image_ref`` (+ optional sizing) is the concrete backend image the
    resolved binding realizes.
    """

    artifact_id: str
    version: str
    digest: str
    media_type: str
    integrity_ref: str
    provenance_ref: str
    image_ref: str = ""
    machine_type: str = ""
    disk_size_gb: int | None = None
    disk_type: str = ""
    image_id: str = ""
    materialization: VerifiedMaterialization | None = None


@dataclass(frozen=True)
class ArtifactSupply:
    """Native inventory facts beside, never hidden inside, the portable availability schema."""

    availability: Mapping[str, ArtifactRequirementAvailability]
    capabilities: tuple[ArtifactMechanismCapability, ...]
    materializations: tuple[VerifiedMaterialization, ...]


def build_artifact_supply(
    requirements: Mapping[str, ArtifactRequirement | None],
    inventory: Sequence[BackendArtifact],
    *,
    capabilities: Iterable[ArtifactMechanismCapability] = (),
) -> ArtifactSupply:
    """Join qualified facts to their exact inventory image and portable identity."""
    qualified = tuple(
        item.materialization for item in inventory if item.materialization is not None and _qualified(item)
    )
    declared = list(capabilities)
    for facts in qualified:
        capability = ArtifactMechanismCapability(
            mechanism=facts.specification.profile,
            supported_requirement_kinds=["source-artifact"],
            supported_routes=[ArtifactAcquisitionTimingModel(acquisition="none", timing="backend-preparation")],
        )
        if capability not in declared:
            declared.append(capability)
    return ArtifactSupply(build_artifact_availability(requirements, inventory), tuple(declared), qualified)


def _qualified(item: BackendArtifact) -> bool:
    """Handle qualified."""
    facts = item.materialization
    return facts is not None and (
        item.artifact_id,
        item.version,
        item.digest,
        item.media_type,
        item.image_ref,
        item.image_id,
        item.integrity_ref,
        item.provenance_ref,
    ) == (
        facts.artifact.artifact_id,
        facts.artifact.version,
        facts.artifact.digest,
        facts.artifact.media_type,
        facts.image_ref,
        facts.image_id,
        facts.integrity_ref,
        facts.provenance_ref,
    )


def build_artifact_availability(
    requirements: Mapping[str, ArtifactRequirement | None],
    inventory: Sequence[BackendArtifact],
) -> dict[str, ArtifactRequirementAvailability]:
    """Project backend inventory into per-requirement availability facts.

    Availability carries only facts the backend can independently establish from
    its admitted inventory: an artifact (exact or an authored candidate) is
    available only when the **complete** portable identity matches an admitted row,
    and the admitting integrity/provenance evidence is echoed from that row. It
    never synthesizes ``satisfied_constraint_ids`` or ``verified_locked_input_ids``
    from mere presence -- constraint satisfaction and locked-input verification are
    author-controlled claims that require an independent verifier, so absent that
    verifier they stay empty and a constrained or locked requirement fails closed
    (ADR-034-R8; codex #1580 review).

    Args:
        requirements: Authored requirements keyed by compiled address (a ``None``
            value marks an ambiguous address and is skipped -- it has no facts).
        inventory: The backend-owned portable artifacts (only admitted rows).

    Returns:
        One ``ArtifactRequirementAvailability`` per resolvable requirement address.
    """
    availability: dict[str, ArtifactRequirementAvailability] = {}
    for address, requirement in requirements.items():
        if requirement is None:
            continue
        availability[address] = _availability_for(address, requirement, inventory)
    return availability


def _availability_for(
    address: str,
    requirement: ArtifactRequirement,
    inventory: Sequence[BackendArtifact],
) -> ArtifactRequirementAvailability:
    """Build one requirement's availability by complete-identity match against inventory."""
    matched: list[BackendArtifact] = []
    digests: list[str] = []
    candidate_ids: list[str] = []

    exact = requirement.exact_artifact
    if exact is not None and (owned := _match_identity(inventory, exact)) is not None:
        matched.append(owned)
        digests.append(exact.digest)

    for candidate in requirement.candidates:
        owned = _match_identity(inventory, candidate.artifact)
        if owned is not None:
            matched.append(owned)
            candidate_ids.append(candidate.candidate_id)
            digests.append(candidate.artifact.digest)

    return ArtifactRequirementAvailability(
        address=address,
        available_artifact_digests=_unique(digests),
        available_candidate_ids=candidate_ids,
        # satisfied_constraint_ids / verified_locked_input_ids are deliberately
        # NOT populated: those are author claims that need an independent verifier,
        # never inferred from inventory presence, so they stay empty (fail closed).
        verified_integrity_refs=_unique(a.integrity_ref for a in matched if a.integrity_ref),
        verified_provenance_refs=_unique(a.provenance_ref for a in matched if a.provenance_ref),
    )


def _match_identity(inventory: Sequence[BackendArtifact], identity: ArtifactIdentity) -> BackendArtifact | None:
    """Return the admitted artifact whose COMPLETE portable identity equals ``identity``.

    All four identity fields must match -- a digest (bytes) collision across two
    distinct authored identities must not let one satisfy the other.
    """
    for artifact in inventory:
        if (
            artifact.artifact_id == identity.artifact_id
            and artifact.version == identity.version
            and artifact.digest == identity.digest
            and artifact.media_type == identity.media_type
        ):
            return artifact
    return None


def _unique(values: Iterable[str]) -> list[str]:
    """Return the values de-duplicated in stable sorted order."""
    return sorted(set(values))


def resolve_plan_artifact_bindings(
    plan: Mapping[str, object],
    *,
    inventory: Sequence[BackendArtifact],
    capabilities: Sequence[ArtifactMechanismCapability],
    backend: ApparatusIdentity,
) -> tuple[ArtifactBinding, ...]:
    """Resolve a compiled plan's authored artifact requirements into fenced bindings.

    Each plan node that carries an authored artifact requirement is resolved
    against the backend inventory; a ``SATISFIED`` resolution becomes an
    :class:`~shared.raes.artifact_binding.ArtifactBinding` keyed by the **plan node
    address** (exactly the address the provisioner's ``parse_plan`` assigns, so the
    provisioner matches it without any address translation). An ``UNRESOLVABLE``
    requirement fails the launch closed (ADR-034: an exact requirement is never
    substituted, so a node whose artifact cannot be satisfied must not silently
    fall through to legacy source-alias resolution). An ``open`` requirement the
    backend may realize at apply time (``DELEGATED``) fences no concrete image.

    The requirement is read from the compiled plan's ``spec.node.source.artifact_requirement``
    and reconstructed through the upstream ``ArtifactRequirement`` model, so this
    consumes the governed contract rather than reparsing SDL or copying address rules.
    """
    requirements = _plan_artifact_requirements(plan)
    if not requirements:
        return ()
    supply = build_artifact_supply(requirements, inventory, capabilities=capabilities)
    bindings: list[ArtifactBinding] = []
    for address, requirement in requirements.items():
        resolution = resolve_artifact_requirement(
            requirement,
            address=address,
            capabilities=supply.capabilities,
            availability=supply.availability.get(address),
            prepared_materializations=supply.materializations,
            backend=backend,
        )
        if resolution.status is ArtifactResolutionStatus.UNRESOLVABLE:
            raise ArtifactSatisfactionError(f"artifact requirement at {address} is unsatisfiable: {resolution.code}")
        # DELEGATED (open, realized at apply time) and SKIPPED fence no concrete image.
        if resolution.status is ArtifactResolutionStatus.SATISFIED:
            bindings.append(_fenced_binding(address, resolution, inventory))
    return tuple(bindings)


def _fenced_binding(
    address: str,
    resolution: ArtifactResolution,
    inventory: Sequence[BackendArtifact],
) -> ArtifactBinding:
    """Build the generation-fenced binding for a SATISFIED resolution, or fail closed.

    Joins the disclosed artifact back to its owned inventory row by COMPLETE
    identity (never digest alone) so the fenced ``image_ref`` is the one admitted
    for exactly that identity. Either guard fails the launch closed rather than
    emit a binding built from incomplete data (defensive: a SATISFIED resolution
    from :func:`resolve_artifact_requirement` always carries a disclosure whose
    artifact is owned, so neither guard trips on that path).
    """
    disclosure = resolution.disclosure
    if disclosure is None:
        raise ArtifactSatisfactionError(f"satisfied artifact requirement at {address} has no disclosure")
    eligible = inventory
    if disclosure.materialization_specification_id is not None:
        eligible = [
            item
            for item in inventory
            if _qualified(item)
            and item.materialization is not None
            and item.materialization.specification.specification_id == disclosure.materialization_specification_id
            and item.materialization.specification.digest == disclosure.materialization_specification_digest
            and item.integrity_ref in disclosure.integrity_refs
            and item.provenance_ref in disclosure.provenance_refs
        ]
    owned = _match_identity(eligible, disclosure.artifact)
    if owned is None:
        raise ArtifactSatisfactionError(f"satisfied artifact for {address} is not in inventory")
    return ArtifactBinding(
        target=address,
        requirement_id=disclosure.requirement_id,
        artifact_id=disclosure.artifact.artifact_id,
        version=disclosure.artifact.version,
        digest=disclosure.artifact.digest,
        media_type=disclosure.artifact.media_type,
        mechanism=disclosure.mechanism.mechanism,
        acquisition=disclosure.acquisition,
        timing=disclosure.timing,
        image_ref=owned.image_ref,
        image_id=owned.image_id,
        machine_type=owned.machine_type,
        disk_size_gb=owned.disk_size_gb,
        disk_type=owned.disk_type,
    )


def _plan_artifact_requirements(plan: Mapping[str, object]) -> dict[str, ArtifactRequirement]:
    """Return each plan node's authored artifact requirement, keyed by node address.

    Walks the serialized ProvisioningPlan's node resources and reconstructs the
    upstream ``ArtifactRequirement`` from ``spec.node.source.artifact_requirement``.
    The node address is the resource entry's ``address`` field -- the same value the
    provisioner's ``parse_plan`` uses -- so a fenced binding keyed by it matches at
    realization. Nodes with no artifact requirement are absent concerns and skipped.
    """
    resources = _nested_get(plan, "resources")
    if not isinstance(resources, Mapping):
        return {}
    requirements: dict[str, ArtifactRequirement] = {}
    for entry in resources.values():
        if not isinstance(entry, Mapping) or entry.get("resource_type") != _NODE_RESOURCE_TYPE:
            continue
        address = entry.get("address")
        raw = _nested_get(entry, "payload", "spec", "node", "source", "artifact_requirement")
        if raw is None or not isinstance(address, str) or not address:
            continue
        requirements[address] = ArtifactRequirement.model_validate(raw)
    return requirements


def _nested_get(mapping: object, *keys: str) -> object:
    """Walk a chain of mapping keys, returning None if any level is absent or not a mapping."""
    current = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current
