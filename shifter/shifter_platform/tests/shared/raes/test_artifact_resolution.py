"""Tests for the RAES artifact-requirement resolution seam (#1580, ADR-034-R2/R8).

The seam is a pure decision function over the portable upstream contracts, so
these tests build real ``raes`` contract objects (no mocks) and assert the
posture matrix -- exact / constrained / open / absent -- plus each of the six
ADR-034-R8 non-realizability reasons.
"""

from __future__ import annotations

from raes.artifact_requirements import (
    ArtifactCandidate,
    ArtifactConstraint,
    ArtifactIdentity,
    ArtifactLockedInput,
    ArtifactMechanismProfile,
    ArtifactRequirement,
    ArtifactSatisfactionRoute,
)
from raes.explicitness import ExplicitnessClass
from raes_contracts.apparatus import ApparatusIdentity
from raes_contracts.contracts import (
    ArtifactAcquisitionTimingModel,
    ArtifactMechanismCapability,
    ArtifactRequirementAvailability,
)

from shared.raes.artifact_resolution import (
    ArtifactResolutionFailure,
    ArtifactResolutionStatus,
    resolve_artifact_requirement,
)

_ADDRESS = "node.web.source.artifact_requirement"
_BACKEND = ApparatusIdentity(name="shifter-provisioner", version="0.0.0")
_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_PROFILE_DIGEST = "sha256:" + "c" * 64

# Distinct verified-trust facts, one per gate, so a swapped or dropped mapping in
# ``_trust_refs`` is caught rather than silently corrupting the admission audit trail.
_TRUST_FACTS = {
    "verified_integrity_refs": ["integrity-1"],
    "verified_authenticity_refs": ["authenticity-1"],
    "verified_admission_refs": ["admission-1"],
    "verified_provenance_refs": ["provenance-1"],
    "verified_evidence_refs": ["evidence-1"],
}


def _assert_disclosure_echoes_trust(disclosure) -> None:
    """Assert the disclosure echoes each verified-trust fact into its matching field."""
    assert disclosure.integrity_refs == ["integrity-1"]
    assert disclosure.authenticity_refs == ["authenticity-1"]
    assert disclosure.admission_refs == ["admission-1"]
    assert disclosure.provenance_refs == ["provenance-1"]
    assert disclosure.evidence_refs == ["evidence-1"]


def _identity(artifact_id: str = "img-web", digest: str = _DIGEST_A) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=artifact_id, version="1.0.0", digest=digest, media_type="application/vnd.raes.image"
    )


def _profile(mechanism: str) -> ArtifactMechanismProfile:
    return ArtifactMechanismProfile(mechanism=mechanism, profile="shifter-gce", version="1", digest=_PROFILE_DIGEST)


def _route(
    mechanism: str, acquisition: str = "local-lookup", timing: str = "backend-preparation"
) -> ArtifactSatisfactionRoute:
    return ArtifactSatisfactionRoute(mechanism=_profile(mechanism), acquisition=acquisition, timing=timing)


def _capability(
    mechanism: str, kinds: list[str], routes: list[ArtifactSatisfactionRoute]
) -> ArtifactMechanismCapability:
    # A capability's supported_routes are mechanism-scoped acquisition/timing
    # pairs (the mechanism is the capability's own field), so project each
    # author-shaped route down to its acquisition/timing.
    supported = [ArtifactAcquisitionTimingModel(acquisition=route.acquisition, timing=route.timing) for route in routes]
    return ArtifactMechanismCapability(
        mechanism=_profile(mechanism), supported_requirement_kinds=kinds, supported_routes=supported
    )


def _exact_requirement(routes: list[ArtifactSatisfactionRoute]) -> ArtifactRequirement:
    return ArtifactRequirement(
        requirement_id="req-exact",
        explicitness=ExplicitnessClass.EXACT,
        exact_artifact=_identity(),
        permitted_routes=routes,
    )


def _constrained_requirement(routes: list[ArtifactSatisfactionRoute]) -> ArtifactRequirement:
    return ArtifactRequirement(
        requirement_id="req-constrained",
        explicitness=ExplicitnessClass.CONSTRAINED,
        candidates=[ArtifactCandidate(candidate_id="cand-linux", artifact=_identity())],
        constraints=[ArtifactConstraint(constraint_id="os-family", kind="os-family", allowed_values=["linux"])],
        locked_inputs=[
            ArtifactLockedInput(
                input_id="locked-1",
                artifact=_identity(artifact_id="img-input", digest=_DIGEST_B),
                associated_artifact_manifest_ref="manifest-1",
                trust_policy_ref="trust-1",
            )
        ],
        permitted_routes=routes,
    )


def _open_requirement(routes: list[ArtifactSatisfactionRoute]) -> ArtifactRequirement:
    return ArtifactRequirement(requirement_id="req-open", explicitness=ExplicitnessClass.OPEN, permitted_routes=routes)


def _availability(**facts: object) -> ArtifactRequirementAvailability:
    return ArtifactRequirementAvailability(address=_ADDRESS, **facts)


def _resolve(requirement, *, capabilities=(), availability=None):
    return resolve_artifact_requirement(
        requirement,
        address=_ADDRESS,
        capabilities=list(capabilities),
        availability=availability,
        backend=_BACKEND,
    )


# --- absent posture ---------------------------------------------------------


def test_absent_requirement_is_skipped_not_an_artifact_request():
    result = _resolve(None)
    assert result.status is ArtifactResolutionStatus.SKIPPED
    assert result.disclosure is None
    assert result.failure is None


# --- exact posture ----------------------------------------------------------


def test_exact_satisfied_by_its_authored_identity():
    route = _route("exact-artifact")
    result = _resolve(
        _exact_requirement([route]),
        capabilities=[_capability("exact-artifact", ["source-artifact"], [route])],
        availability=_availability(available_artifact_digests=[_DIGEST_A], **_TRUST_FACTS),
    )
    assert result.status is ArtifactResolutionStatus.SATISFIED
    assert result.disclosure is not None
    assert result.disclosure.artifact.digest == _DIGEST_A
    assert result.disclosure.acquisition == "local-lookup"
    assert result.disclosure.timing == "backend-preparation"
    _assert_disclosure_echoes_trust(result.disclosure)


def test_exact_unavailable_when_its_digest_is_not_in_inventory():
    route = _route("exact-artifact")
    result = _resolve(
        _exact_requirement([route]),
        capabilities=[_capability("exact-artifact", ["source-artifact"], [route])],
        availability=_availability(available_artifact_digests=[_DIGEST_B]),
    )
    assert result.status is ArtifactResolutionStatus.UNRESOLVABLE
    assert result.failure is ArtifactResolutionFailure.UNAVAILABLE_EXACT_ARTIFACT
    assert result.code == "shifter-realizability.artifact-unavailable-exact"


def test_exact_is_never_substituted_by_an_available_candidate():
    # A backend-owned candidate is available, but an exact requirement whose exact
    # artifact is absent must fail rather than fall back to the candidate.
    route = _route("exact-artifact")
    result = _resolve(
        _exact_requirement([route]),
        capabilities=[_capability("exact-artifact", ["source-artifact"], [route])],
        availability=_availability(available_artifact_digests=[_DIGEST_B], available_candidate_ids=["cand-linux"]),
    )
    assert result.status is ArtifactResolutionStatus.UNRESOLVABLE
    assert result.failure is ArtifactResolutionFailure.UNAVAILABLE_EXACT_ARTIFACT


def test_exact_unsupported_when_backend_declares_no_mechanism():
    result = _resolve(
        _exact_requirement([_route("exact-artifact")]),
        capabilities=[],
        availability=_availability(available_artifact_digests=[_DIGEST_A]),
    )
    assert result.failure is ArtifactResolutionFailure.UNSUPPORTED_BACKEND_MECHANISM


def test_exact_present_but_untrusted_is_not_admissibly_available():
    # The digest is in inventory, but no integrity/provenance gate has cleared it,
    # so it is not admissibly available -- trust is a separate decision (AC9).
    route = _route("exact-artifact")
    result = _resolve(
        _exact_requirement([route]),
        capabilities=[_capability("exact-artifact", ["source-artifact"], [route])],
        availability=_availability(available_artifact_digests=[_DIGEST_A]),
    )
    assert result.status is ArtifactResolutionStatus.UNRESOLVABLE
    assert result.failure is ArtifactResolutionFailure.UNAVAILABLE_EXACT_ARTIFACT


def test_route_must_be_author_permitted_even_if_backend_offers_it():
    # Backend offers a pull route the author did not permit -> no usable route.
    author_route = _route("exact-artifact", acquisition="local-lookup")
    backend_route = _route("exact-artifact", acquisition="pull")
    result = _resolve(
        _exact_requirement([author_route]),
        capabilities=[_capability("exact-artifact", ["source-artifact"], [backend_route])],
        availability=_availability(available_artifact_digests=[_DIGEST_A]),
    )
    assert result.failure is ArtifactResolutionFailure.UNSUPPORTED_BACKEND_MECHANISM


# --- constrained posture ----------------------------------------------------


def test_constrained_satisfied_by_conforming_available_candidate():
    route = _route("published-candidate")
    result = _resolve(
        _constrained_requirement([route]),
        capabilities=[_capability("published-candidate", ["source-artifact"], [route])],
        availability=_availability(
            available_candidate_ids=["cand-linux"],
            satisfied_constraint_ids=["os-family"],
            verified_locked_input_ids=["locked-1"],
            **_TRUST_FACTS,
        ),
    )
    assert result.status is ArtifactResolutionStatus.SATISFIED
    assert result.disclosure.candidate_id == "cand-linux"
    assert result.disclosure.satisfied_constraint_ids == ["os-family"]
    assert result.disclosure.locked_input_ids == ["locked-1"]
    _assert_disclosure_echoes_trust(result.disclosure)


def test_constrained_fails_on_unsatisfied_constraint():
    route = _route("published-candidate")
    result = _resolve(
        _constrained_requirement([route]),
        capabilities=[_capability("published-candidate", ["source-artifact"], [route])],
        availability=_availability(
            available_candidate_ids=["cand-linux"],
            satisfied_constraint_ids=[],
            verified_locked_input_ids=["locked-1"],
        ),
    )
    assert result.failure is ArtifactResolutionFailure.UNSATISFIED_CONSTRAINT


def test_constrained_fails_on_missing_locked_input():
    route = _route("published-candidate")
    result = _resolve(
        _constrained_requirement([route]),
        capabilities=[_capability("published-candidate", ["source-artifact"], [route])],
        availability=_availability(
            available_candidate_ids=["cand-linux"],
            satisfied_constraint_ids=["os-family"],
            verified_locked_input_ids=[],
        ),
    )
    assert result.failure is ArtifactResolutionFailure.MISSING_LOCKED_INPUT


def test_constrained_fails_when_no_candidate_is_available():
    route = _route("published-candidate")
    result = _resolve(
        _constrained_requirement([route]),
        capabilities=[_capability("published-candidate", ["source-artifact"], [route])],
        availability=_availability(
            available_candidate_ids=[],
            satisfied_constraint_ids=["os-family"],
            verified_locked_input_ids=["locked-1"],
        ),
    )
    assert result.failure is ArtifactResolutionFailure.UNAVAILABLE_CANDIDATE


def test_constrained_unsupported_when_backend_lacks_the_kind():
    route = _route("published-candidate")
    result = _resolve(
        _constrained_requirement([route]),
        # A different compiled concern does not authorize a source artifact.
        capabilities=[_capability("published-candidate", ["other-artifact"], [route])],
        availability=_availability(
            available_candidate_ids=["cand-linux"],
            satisfied_constraint_ids=["os-family"],
            verified_locked_input_ids=["locked-1"],
        ),
    )
    assert result.failure is ArtifactResolutionFailure.UNSUPPORTED_BACKEND_MECHANISM


# --- open posture -----------------------------------------------------------


def test_open_is_delegated_to_a_declared_compatible_mechanism():
    route = _route("dynamic-composition", timing="realization")
    result = _resolve(
        _open_requirement([route]),
        capabilities=[_capability("dynamic-composition", ["source-artifact"], [route])],
    )
    assert result.status is ArtifactResolutionStatus.DELEGATED
    assert result.route == route
    assert result.disclosure is None


def test_open_unsupported_when_no_backend_mechanism_declares_it():
    result = _resolve(_open_requirement([_route("dynamic-composition", timing="realization")]), capabilities=[])
    assert result.status is ArtifactResolutionStatus.UNRESOLVABLE
    assert result.failure is ArtifactResolutionFailure.UNSUPPORTED_OPEN_REALIZATION


def test_all_six_failure_codes_are_distinct_and_namespaced():
    codes = {member.value for member in ArtifactResolutionFailure}
    assert len(codes) == 6
    assert all(code.startswith("shifter-realizability.artifact-") for code in codes)


# --- realizability projection (resolve_artifact_gaps) ------------------------


def test_no_requirements_produce_no_artifact_gaps():
    from shared.raes.realizability import resolve_artifact_gaps

    gaps = resolve_artifact_gaps({}, capabilities=[], availability_by_address={}, backend=_BACKEND)
    assert gaps == ()


def test_unresolvable_requirement_becomes_an_artifact_gap():
    from shared.raes.realizability import GapCategory, resolve_artifact_gaps

    gaps = resolve_artifact_gaps(
        {_ADDRESS: _exact_requirement([_route("exact-artifact")])},
        capabilities=[],  # fail-closed: no mechanism declared
        availability_by_address={},
        backend=_BACKEND,
    )
    assert len(gaps) == 1
    assert gaps[0].category is GapCategory.ARTIFACT
    assert gaps[0].code == ArtifactResolutionFailure.UNSUPPORTED_BACKEND_MECHANISM.value
    assert gaps[0].address == _ADDRESS


def test_satisfied_requirement_produces_no_artifact_gap():
    from shared.raes.realizability import resolve_artifact_gaps

    route = _route("exact-artifact")
    gaps = resolve_artifact_gaps(
        {_ADDRESS: _exact_requirement([route])},
        capabilities=[_capability("exact-artifact", ["source-artifact"], [route])],
        availability_by_address={
            _ADDRESS: _availability(
                available_artifact_digests=[_DIGEST_A],
                verified_integrity_refs=["integrity-1"],
                verified_provenance_refs=["provenance-1"],
            )
        },
        backend=_BACKEND,
    )
    assert gaps == ()


def test_ambiguous_compiled_address_becomes_a_gap():
    from shared.raes.realizability import AMBIGUOUS_ARTIFACT_ADDRESS_CODE, resolve_artifact_gaps

    gaps = resolve_artifact_gaps({_ADDRESS: None}, capabilities=[], availability_by_address={}, backend=_BACKEND)
    assert len(gaps) == 1
    assert gaps[0].code == AMBIGUOUS_ARTIFACT_ADDRESS_CODE
