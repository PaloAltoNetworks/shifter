"""Tests for backend artifact inventory → availability + the live mechanism (#1580).

Covers the (B) realization after the codex-review hardening: availability is built
by COMPLETE-identity match against admitted inventory (never digest alone) and
never synthesizes constraint/locked-input facts; the manifest declares only the
truthful ``exact-artifact`` mechanism; and a registered prebaked image genuinely
satisfies an exact requirement end-to-end through the seam.
"""

from __future__ import annotations

import pytest
from raes.artifact_requirements import (
    ArtifactCandidate,
    ArtifactConstraint,
    ArtifactIdentity,
    ArtifactRequirement,
    ArtifactSatisfactionRoute,
)
from raes.explicitness import ExplicitnessClass
from raes_contracts.apparatus import ApparatusIdentity

from shared.raes.artifact_inventory import (
    ArtifactSatisfactionError,
    BackendArtifact,
    _fenced_binding,
    build_artifact_availability,
    resolve_plan_artifact_bindings,
)
from shared.raes.artifact_resolution import (
    ArtifactResolution,
    ArtifactResolutionStatus,
    resolve_artifact_requirement,
)
from shared.raes.manifest import (
    exact_artifact_profile,
    shifter_artifact_mechanism_capabilities,
    shifter_backend_apparatus,
)

_NODE_ADDRESS = "provision.node.web"
_ADDRESS = "provision.node.web.source-artifact"
_DIGEST = "sha256:" + "a" * 64
_OTHER_DIGEST = "sha256:" + "b" * 64
_MEDIA = "application/vnd.raes.image"


def _identity(*, artifact_id: str = "img-web", version: str = "1.0.0", digest: str = _DIGEST) -> ArtifactIdentity:
    return ArtifactIdentity(artifact_id=artifact_id, version=version, digest=digest, media_type=_MEDIA)


def _owned(
    *,
    artifact_id: str = "img-web",
    version: str = "1.0.0",
    digest: str = _DIGEST,
    image_ref: str = "projects/x/global/images/web",
) -> BackendArtifact:
    return BackendArtifact(
        artifact_id=artifact_id,
        version=version,
        digest=digest,
        media_type=_MEDIA,
        integrity_ref="integrity-1",
        provenance_ref="provenance-1",
        image_ref=image_ref,
        machine_type="e2-medium",
    )


def _exact_route() -> ArtifactSatisfactionRoute:
    """A route referencing Shifter's exact-artifact profile (the only mechanism exact permits)."""
    return ArtifactSatisfactionRoute(
        mechanism=exact_artifact_profile(), acquisition="local-lookup", timing="backend-preparation"
    )


def _exact_requirement() -> ArtifactRequirement:
    return ArtifactRequirement(
        requirement_id="r",
        explicitness=ExplicitnessClass.EXACT,
        exact_artifact=_identity(),
        permitted_routes=[_exact_route()],
    )


# --- build_artifact_availability: complete-identity match, no synthesis -----


def test_exact_artifact_owned_by_complete_identity_is_available_with_evidence():
    availability = build_artifact_availability({_ADDRESS: _exact_requirement()}, [_owned()])
    facts = availability[_ADDRESS]
    assert facts.available_artifact_digests == [_DIGEST]
    assert facts.verified_integrity_refs == ["integrity-1"]
    assert facts.verified_provenance_refs == ["provenance-1"]


def test_same_digest_different_identity_is_not_a_match():
    # Bytes (digest) collide, but artifact_id differs -> not the same artifact.
    availability = build_artifact_availability({_ADDRESS: _exact_requirement()}, [_owned(artifact_id="other-image")])
    assert availability[_ADDRESS].available_artifact_digests == []


def test_unowned_exact_artifact_is_not_available():
    availability = build_artifact_availability({_ADDRESS: _exact_requirement()}, [_owned(digest=_OTHER_DIGEST)])
    assert availability[_ADDRESS].available_artifact_digests == []
    assert availability[_ADDRESS].verified_integrity_refs == []


def test_constraints_and_locked_inputs_are_never_synthesized_from_presence():
    # A constrained requirement whose candidate is owned still reports NO satisfied
    # constraints: constraint satisfaction is an author claim needing an independent
    # verifier, so availability leaves it empty (fail closed).
    requirement = ArtifactRequirement(
        requirement_id="r",
        explicitness=ExplicitnessClass.CONSTRAINED,
        candidates=[ArtifactCandidate(candidate_id="c1", artifact=_identity())],
        constraints=[ArtifactConstraint(constraint_id="os-family", kind="os-family", allowed_values=["linux"])],
        permitted_routes=[_exact_route()],
    )
    facts = build_artifact_availability({_ADDRESS: requirement}, [_owned()])[_ADDRESS]
    assert facts.available_candidate_ids == ["c1"]  # identity match is a fact
    assert facts.satisfied_constraint_ids == []  # constraint satisfaction is not


def test_ambiguous_address_is_skipped():
    assert build_artifact_availability({_ADDRESS: None}, [_owned()]) == {}


# --- manifest declares only the truthful exact-artifact mechanism -----------


def test_manifest_declares_only_exact_artifact_mechanism():
    capabilities = shifter_artifact_mechanism_capabilities()
    assert len(capabilities) == 1
    capability = capabilities[0]
    assert capability.mechanism.mechanism == "exact-artifact"
    assert capability.supported_requirement_kinds == ["source-artifact"]
    route = capability.supported_routes[0]
    assert (route.acquisition, route.timing) == ("local-lookup", "backend-preparation")


def test_exact_mechanism_profile_digest_is_stable_and_well_formed():
    first = exact_artifact_profile()
    second = exact_artifact_profile()
    assert first == second  # two independent builds produce an equal, deterministic profile
    digest = first.digest
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


# --- end-to-end: a registered prebaked image satisfies an exact requirement --


def test_registered_backend_artifact_satisfies_exact_requirement():
    requirement = _exact_requirement()
    availability = build_artifact_availability({_ADDRESS: requirement}, [_owned()])
    resolution = resolve_artifact_requirement(
        requirement,
        address=_ADDRESS,
        capabilities=shifter_artifact_mechanism_capabilities(),
        availability=availability[_ADDRESS],
        backend=ApparatusIdentity(name="shifter-provisioner", version="0.0.0"),
    )
    assert resolution.status is ArtifactResolutionStatus.SATISFIED
    assert resolution.disclosure.artifact.digest == _DIGEST
    assert resolution.disclosure.mechanism.mechanism == "exact-artifact"
    assert resolution.disclosure.integrity_refs == ["integrity-1"]


def test_unregistered_exact_requirement_is_unresolvable():
    requirement = _exact_requirement()
    availability = build_artifact_availability({_ADDRESS: requirement}, [])  # empty inventory
    resolution = resolve_artifact_requirement(
        requirement,
        address=_ADDRESS,
        capabilities=shifter_artifact_mechanism_capabilities(),
        availability=availability[_ADDRESS],
        backend=ApparatusIdentity(name="shifter-provisioner", version="0.0.0"),
    )
    assert resolution.status is ArtifactResolutionStatus.UNRESOLVABLE


# --- resolve_plan_artifact_bindings (launch-time producer) ------------------


def _plan_with_source(requirement):
    """A minimal serialized-plan shape carrying one node source (+ optional requirement)."""
    source = {
        "name": "img-web",
        "version": "1.0.0",
        "build": None,
        "artifact_requirement": requirement.model_dump(mode="json") if requirement is not None else None,
    }
    return {
        "resources": {
            "n0": {
                "resource_type": "node",
                "address": _NODE_ADDRESS,
                "payload": {"spec": {"node": {"source": source}}},
            }
        }
    }


def _resolve_plan(plan, inventory):
    return resolve_plan_artifact_bindings(
        plan,
        inventory=inventory,
        capabilities=shifter_artifact_mechanism_capabilities(),
        backend=shifter_backend_apparatus(),
    )


def test_resolve_plan_bindings_satisfies_registered_node():
    bindings = _resolve_plan(_plan_with_source(_exact_requirement()), [_owned()])
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.target == _NODE_ADDRESS  # the plan-node address the provisioner keys on
    assert binding.digest == _DIGEST
    assert binding.image_ref == "projects/x/global/images/web"
    assert binding.mechanism == "exact-artifact"
    assert binding.machine_type == "e2-medium"


def test_resolve_plan_bindings_unsatisfiable_fails_closed():
    plan = _plan_with_source(_exact_requirement())
    with pytest.raises(ArtifactSatisfactionError):
        _resolve_plan(plan, [])  # empty inventory


def test_resolve_plan_bindings_absent_requirement_is_empty():
    assert _resolve_plan(_plan_with_source(None), [_owned()]) == ()


def test_fenced_binding_without_disclosure_fails_closed():
    # A SATISFIED resolution is expected to carry a disclosure; a missing one fails
    # the launch closed rather than emitting a binding built from nothing.
    resolution = ArtifactResolution(
        requirement_id="req-1",
        address=_ADDRESS,
        status=ArtifactResolutionStatus.SATISFIED,
        disclosure=None,
    )
    inventory = [_owned()]
    with pytest.raises(ArtifactSatisfactionError, match="no disclosure"):
        _fenced_binding(_ADDRESS, resolution, inventory)


def test_fenced_binding_with_unowned_artifact_fails_closed():
    # The disclosed artifact must join to an owned inventory row by complete identity;
    # an empty inventory means the row is gone, so it fails closed instead of guessing.
    requirement = _exact_requirement()
    availability = build_artifact_availability({_ADDRESS: requirement}, [_owned()])
    resolution = resolve_artifact_requirement(
        requirement,
        address=_ADDRESS,
        capabilities=shifter_artifact_mechanism_capabilities(),
        availability=availability[_ADDRESS],
        backend=shifter_backend_apparatus(),
    )
    assert resolution.status is ArtifactResolutionStatus.SATISFIED
    with pytest.raises(ArtifactSatisfactionError, match="not in inventory"):
        _fenced_binding(_ADDRESS, resolution, [])
