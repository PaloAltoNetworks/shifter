"""Server-owned RAES artifact-requirement resolution seam (#1580, ADR-034-R2/R8).

ADR-034 makes RAES the sole semantic authority for artifact requirements. This
module is the ONE Shifter-owned seam that decides, for a compiled
``ArtifactRequirement`` and a selected backend, whether the backend can satisfy
it and how -- honoring the author's ``exact`` / ``constrained`` / ``open``
posture and *never* substituting a fallback, candidate, composition, or fresh
bake for an ``exact`` requirement. ``absent`` (no requirement on the ``Source``)
is not an artifact request and is reported as :attr:`ArtifactResolutionStatus.SKIPPED`.

It CONSUMES the portable upstream contracts -- the compiled
:class:`~raes.artifact_requirements.ArtifactRequirement`, the backend's declared
:class:`ArtifactMechanismCapability` set, an immutable
:class:`ArtifactRequirementAvailability` snapshot of Shifter-owned facts (verified
inventory, satisfied constraints, verified locked inputs), and the selected
backend identity -- and EMITS the upstream
:class:`ArtifactSatisfactionDisclosureModel` on success. It defines no portable
schema and no diagnostic vocabulary of its own for the contract surface; the
non-satisfaction reasons are Shifter's own realizability projection, namespaced
``shifter-realizability.artifact-*`` exactly like the sibling gaps in
:mod:`shared.raes.realizability`.

Crucially the seam is a **pure decision function**: it performs no acquisition,
trust check, download, or image construction. That is what keeps long-running
VM-image construction off the range-provisioning critical path (ADR-034-R8): a
resolution only *selects* among routes the author permitted AND the backend
declared, each of which already carries its own acquisition transport and
timing. Selection, availability, trust/admission, acquisition transport, and
timing therefore stay five independent decisions, as ADR-034 requires.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from raes.artifact_requirements import (
    ArtifactMechanismProfile,
    ArtifactRequirement,
    ArtifactSatisfactionRoute,
)
from raes.explicitness import ExplicitnessClass

# ``raes_contracts.artifact_requirements`` raises a partially-initialized circular
# ImportError when it is the first ``raes_contracts`` submodule imported. Importing
# ``raes_contracts.apparatus`` first (as ``shared.raes.manifest`` also does) resolves
# it, and it sorts before ``raes_contracts.contracts`` so import ordering is stable.
from raes_contracts.apparatus import ApparatusIdentity
from raes_contracts.contracts import (
    ArtifactAcquisitionTimingModel,
    ArtifactMechanismCapability,
    ArtifactRequirementAvailability,
    ArtifactSatisfactionDisclosureModel,
)

from shared.operation_envelope import canonical_payload_digest
from shared.raes.prepared_artifacts import VerifiedMaterialization

__all__ = [
    "ArtifactResolution",
    "ArtifactResolutionFailure",
    "ArtifactResolutionStatus",
    "resolve_artifact_requirement",
]


class ArtifactResolutionStatus(StrEnum):
    """Closed outcome of resolving one artifact requirement against a backend."""

    #: A concrete artifact and mechanism were selected (``exact`` / ``constrained``).
    SATISFIED = "satisfied"
    #: An ``open`` concern the backend is permitted to realize at apply time; no
    #: concrete artifact is bound here because open realization is delegated.
    DELEGATED = "delegated"
    #: The ``Source`` declared no artifact requirement -- not an artifact request.
    SKIPPED = "skipped"
    #: The requirement cannot be satisfied by this backend; see :attr:`ArtifactResolution.failure`.
    UNRESOLVABLE = "unresolvable"


class ArtifactResolutionFailure(StrEnum):
    """The six ADR-034-R8 non-realizability reasons, as stable switchable codes.

    The value IS the ``shifter-realizability.artifact-*`` gap code that
    :mod:`shared.raes.realizability` surfaces, so clients switch on the code and
    never on prose.
    """

    UNAVAILABLE_EXACT_ARTIFACT = "shifter-realizability.artifact-unavailable-exact"
    UNSATISFIED_CONSTRAINT = "shifter-realizability.artifact-unsatisfied-constraint"
    UNSUPPORTED_OPEN_REALIZATION = "shifter-realizability.artifact-unsupported-open"
    MISSING_LOCKED_INPUT = "shifter-realizability.artifact-missing-locked-input"
    UNAVAILABLE_CANDIDATE = "shifter-realizability.artifact-unavailable-candidate"
    UNSUPPORTED_BACKEND_MECHANISM = "shifter-realizability.artifact-unsupported-mechanism"


@dataclass(frozen=True)
class ArtifactResolution:
    """The typed outcome of resolving one requirement.

    ``disclosure`` is populated only for :attr:`ArtifactResolutionStatus.SATISFIED`;
    ``route`` names the selected route for ``SATISFIED`` and ``DELEGATED``;
    ``failure`` and ``message`` are populated only for ``UNRESOLVABLE``. ``message``
    is a bounded, safe string: it never carries authored values, artifact
    payloads, provider detail, constraints, locked-input values, or credentials.
    """

    requirement_id: str
    address: str
    status: ArtifactResolutionStatus
    disclosure: ArtifactSatisfactionDisclosureModel | None = None
    route: ArtifactSatisfactionRoute | None = None
    failure: ArtifactResolutionFailure | None = None
    message: str = ""

    @property
    def code(self) -> str:
        """The stable failure code, or ``""`` when the requirement was satisfied."""
        return self.failure.value if self.failure is not None else ""


def resolve_artifact_requirement(
    requirement: ArtifactRequirement | None,
    *,
    address: str,
    capabilities: Sequence[ArtifactMechanismCapability],
    availability: ArtifactRequirementAvailability | None,
    backend: ApparatusIdentity,
    prepared_materializations: Sequence[VerifiedMaterialization] = (),
) -> ArtifactResolution:
    """Resolve one artifact requirement against a selected backend.

    Args:
        requirement: The compiled RAES artifact requirement, or ``None`` for an
            absent concern (a ``Source`` that declared no requirement).
        address: The compiled requirement address (for diagnostics and the
            availability join). Never an authored value.
        capabilities: The backend's declared ``ArtifactMechanismCapability`` set.
            An empty set truthfully admits no mechanism (fail-closed).
        availability: Shifter-owned trusted facts scoped to this requirement, or
            ``None`` when nothing is available for it.
        backend: The selected backend identity recorded in the disclosure.

    Returns:
        A typed :class:`ArtifactResolution`. Never raises for an expected
        non-realizability; that is a domain result, not an exception.
    """
    if requirement is None:
        return ArtifactResolution(
            requirement_id="",
            address=address,
            status=ArtifactResolutionStatus.SKIPPED,
        )

    facts = availability or _empty_availability(address)
    posture = requirement.explicitness
    if posture is ExplicitnessClass.EXACT:
        result = _resolve_exact(requirement, address, capabilities, facts, backend)
    elif posture is ExplicitnessClass.CONSTRAINED:
        result = _resolve_constrained(requirement, address, capabilities, facts, backend)
        if result.status is not ArtifactResolutionStatus.SATISFIED:
            prepared = _resolve_prepared(requirement, address, capabilities, backend, prepared_materializations)
            if prepared is not None:
                result = prepared
    else:
        result = _resolve_open(requirement, address, capabilities)
    return result


def _resolve_prepared(
    requirement: ArtifactRequirement,
    address: str,
    capabilities: Sequence[ArtifactMechanismCapability],
    backend: ApparatusIdentity,
    materializations: Sequence[VerifiedMaterialization],
) -> ArtifactResolution | None:
    """Select one completely verified output without combining partial evidence."""
    digest = canonical_payload_digest(requirement.model_dump(mode="json"))
    for facts in materializations:
        if (
            facts.requirement_digest != digest
            or facts.specification not in requirement.materialization_specifications
            or set(facts.satisfied_constraint_ids) != {item.constraint_id for item in requirement.constraints}
            or set(facts.locked_input_ids) != {item.input_id for item in requirement.locked_inputs}
        ):
            continue
        supported = [capability for capability in capabilities if capability.mechanism == facts.specification.profile]
        selected = _select_route(requirement, supported)
        if selected is None:
            continue
        mechanism, route = selected
        if route.acquisition != "none" or route.timing != "backend-preparation":
            continue
        return ArtifactResolution(
            requirement_id=requirement.requirement_id,
            address=address,
            status=ArtifactResolutionStatus.SATISFIED,
            route=route,
            disclosure=ArtifactSatisfactionDisclosureModel(
                requirement_id=requirement.requirement_id,
                artifact=facts.artifact,
                mechanism=mechanism,
                acquisition=route.acquisition,
                timing=route.timing,
                backend=backend,
                materialization_specification_id=facts.specification.specification_id,
                materialization_specification_digest=facts.specification.digest,
                satisfied_constraint_ids=facts.satisfied_constraint_ids,
                locked_input_ids=facts.locked_input_ids,
                integrity_refs=[facts.integrity_ref],
                provenance_refs=[facts.provenance_ref],
            ),
        )
    return None


def _resolve_exact(
    requirement: ArtifactRequirement,
    address: str,
    capabilities: Sequence[ArtifactMechanismCapability],
    facts: ArtifactRequirementAvailability,
    backend: ApparatusIdentity,
) -> ArtifactResolution:
    """Resolve an ``exact`` requirement: the authored identity, or nothing."""
    selection = _select_route(requirement, capabilities)
    if selection is None:
        return _fail(requirement, address, ArtifactResolutionFailure.UNSUPPORTED_BACKEND_MECHANISM)
    mechanism, route = selection

    exact = requirement.exact_artifact
    if exact is None or exact.digest not in facts.available_artifact_digests or not _trust_admissible(facts):
        # An exact requirement is honored only by its exact artifact -- never a
        # candidate, composition, base image, or fresh bake -- and only when the
        # artifact's owning integrity/provenance gates have admitted it (a
        # separate decision from selection, AC9).
        return _fail(requirement, address, ArtifactResolutionFailure.UNAVAILABLE_EXACT_ARTIFACT)

    return ArtifactResolution(
        requirement_id=requirement.requirement_id,
        address=address,
        status=ArtifactResolutionStatus.SATISFIED,
        route=route,
        disclosure=ArtifactSatisfactionDisclosureModel(
            requirement_id=requirement.requirement_id,
            artifact=exact,
            mechanism=mechanism,
            acquisition=route.acquisition,
            timing=route.timing,
            backend=backend,
            **_trust_refs(facts),
        ),
    )


def _resolve_constrained(
    requirement: ArtifactRequirement,
    address: str,
    capabilities: Sequence[ArtifactMechanismCapability],
    facts: ArtifactRequirementAvailability,
    backend: ApparatusIdentity,
) -> ArtifactResolution:
    """Resolve a ``constrained`` requirement: an available candidate meeting every bound."""
    selection = _select_route(requirement, capabilities)
    if selection is None:
        return _fail(requirement, address, ArtifactResolutionFailure.UNSUPPORTED_BACKEND_MECHANISM)
    mechanism, route = selection

    candidate = next((c for c in requirement.candidates if c.candidate_id in facts.available_candidate_ids), None)
    failure = _constrained_failure(requirement, facts, candidate_available=candidate is not None)
    if failure is not None or candidate is None:
        # An unmet constraint, an unverified locked input, or an unavailable /
        # non-trust-admissible candidate each fails closed (trust stays separate
        # from selection, AC9). ``candidate is None`` here always coincides with a
        # non-None failure; the explicit check narrows the type for the return below.
        return _fail(requirement, address, failure or ArtifactResolutionFailure.UNAVAILABLE_CANDIDATE)

    return ArtifactResolution(
        requirement_id=requirement.requirement_id,
        address=address,
        status=ArtifactResolutionStatus.SATISFIED,
        route=route,
        disclosure=ArtifactSatisfactionDisclosureModel(
            requirement_id=requirement.requirement_id,
            artifact=candidate.artifact,
            mechanism=mechanism,
            acquisition=route.acquisition,
            timing=route.timing,
            backend=backend,
            candidate_id=candidate.candidate_id,
            satisfied_constraint_ids=[c.constraint_id for c in requirement.constraints],
            locked_input_ids=[li.input_id for li in requirement.locked_inputs],
            **_trust_refs(facts),
        ),
    )


def _constrained_failure(
    requirement: ArtifactRequirement,
    facts: ArtifactRequirementAvailability,
    *,
    candidate_available: bool,
) -> ArtifactResolutionFailure | None:
    """Return why a constrained requirement is unsatisfiable, or None if admissible.

    Every declared constraint must be independently satisfied and every locked
    input independently verified, and a trust-admissible authored candidate must
    be available; each maps to a stable failure code. Absent an independent
    verifier the availability facts leave these empty, so the requirement fails
    closed (ADR-034-R8).
    """
    checks = (
        (
            any(c.constraint_id not in facts.satisfied_constraint_ids for c in requirement.constraints),
            ArtifactResolutionFailure.UNSATISFIED_CONSTRAINT,
        ),
        (
            any(li.input_id not in facts.verified_locked_input_ids for li in requirement.locked_inputs),
            ArtifactResolutionFailure.MISSING_LOCKED_INPUT,
        ),
        (
            not candidate_available or not _trust_admissible(facts),
            ArtifactResolutionFailure.UNAVAILABLE_CANDIDATE,
        ),
    )
    for failed, failure in checks:
        if failed:
            return failure
    return None


def _resolve_open(
    requirement: ArtifactRequirement,
    address: str,
    capabilities: Sequence[ArtifactMechanismCapability],
) -> ArtifactResolution:
    """Resolve an ``open`` requirement: delegable only to a declared compatible mechanism.

    Open realization picks no concrete artifact here -- the backend realizes it
    at apply time -- so success is :attr:`ArtifactResolutionStatus.DELEGATED`
    carrying the selected route, not a concrete disclosure.
    """
    selection = _select_route(requirement, capabilities)
    if selection is None:
        return _fail(requirement, address, ArtifactResolutionFailure.UNSUPPORTED_OPEN_REALIZATION)
    _, route = selection
    if route.timing != "realization":
        return _fail(requirement, address, ArtifactResolutionFailure.UNSUPPORTED_OPEN_REALIZATION)
    return ArtifactResolution(
        requirement_id=requirement.requirement_id,
        address=address,
        status=ArtifactResolutionStatus.DELEGATED,
        route=route,
    )


def _select_route(
    requirement: ArtifactRequirement,
    capabilities: Sequence[ArtifactMechanismCapability],
) -> tuple[ArtifactMechanismProfile, ArtifactSatisfactionRoute] | None:
    """Return the first (mechanism, route) the author permitted AND the backend declared.

    A route is usable only when the backend declares a capability that supports
    the source-artifact concern, whose mechanism matches an author-permitted
    route, and whose supported acquisition/timing combinations include that
    route's. The backend expresses support as mechanism-scoped
    ``ArtifactAcquisitionTimingModel`` entries (the mechanism is the capability's
    own field), while the author permits full ``ArtifactSatisfactionRoute``s;
    matching bridges the two shapes. Deterministic: capabilities are scanned in
    declared order, permitted routes in author order.
    """
    # Public capability kinds name compiled concerns, not explicitness postures.
    kind = "source-artifact"
    for capability in capabilities:
        if kind not in capability.supported_requirement_kinds:
            continue
        for route in requirement.permitted_routes:
            if route.mechanism == capability.mechanism and _route_timing_supported(route, capability.supported_routes):
                return capability.mechanism, route
    return None


def _route_timing_supported(
    route: ArtifactSatisfactionRoute,
    supported: Sequence[ArtifactAcquisitionTimingModel],
) -> bool:
    """Return whether the route's acquisition/timing is one the backend declared."""
    return any(entry.acquisition == route.acquisition and entry.timing == route.timing for entry in supported)


def _fail(
    requirement: ArtifactRequirement,
    address: str,
    failure: ArtifactResolutionFailure,
) -> ArtifactResolution:
    """Build an ``UNRESOLVABLE`` result with a bounded, value-free message."""
    return ArtifactResolution(
        requirement_id=requirement.requirement_id,
        address=address,
        status=ArtifactResolutionStatus.UNRESOLVABLE,
        failure=failure,
        message=failure.name.replace("_", " ").lower(),
    )


def _trust_admissible(facts: ArtifactRequirementAvailability) -> bool:
    """Return whether the artifact's integrity and provenance gates have cleared it.

    The satisfaction disclosure contract refuses to describe a realized artifact
    without at least one integrity and one provenance reference, so an artifact
    is admissibly available only once those owning gates have recorded evidence.
    """
    return bool(facts.verified_integrity_refs) and bool(facts.verified_provenance_refs)


def _trust_refs(facts: ArtifactRequirementAvailability) -> dict[str, list[str]]:
    """Carry the verified trust references straight from their owning gates.

    The disclosure never asserts integrity, authenticity, admission, provenance,
    or evidence itself; it only echoes the references that Shifter's independent
    trust/admission gates already recorded in the availability snapshot, keeping
    trust a separate decision from artifact selection.
    """
    return {
        "integrity_refs": list(facts.verified_integrity_refs),
        "authenticity_refs": list(facts.verified_authenticity_refs),
        "admission_refs": list(facts.verified_admission_refs),
        "provenance_refs": list(facts.verified_provenance_refs),
        "evidence_refs": list(facts.verified_evidence_refs),
    }


def _empty_availability(address: str) -> ArtifactRequirementAvailability:
    """Return an availability snapshot that admits nothing, for a requirement with no facts."""
    return ArtifactRequirementAvailability(address=address)
