"""Issue #1291: participant-runtime manifest conformance gate.

Shifter's published ACES backend manifest (``shared.aces.manifest``) declares
no ``participant_runtime`` capability -- Shifter has no ACES participant
lifecycle/history/evidence protocol implementation, so the claim legitimately
stays ``None`` until a later slice adds the required contracts and live
conformance evidence (see
``docs/architecture/aces-participant-runtime-manifest-conformance-gate-preflight-1291.md``
and
``docs/architecture/aces-participant-runtime-manifest-cutover-rollback-1291.md``).

This file is the falsifiable conformance *gate* that protects that posture
going forward:

1. it locks the current, honest state -- Shifter's real manifest declares no
   ``participant_runtime`` capability and infers as ``PROVISIONING_ONLY``;
2. it proves the gate is not vacuous by constructing a mutated manifest that
   *does* claim participant-runtime support and asserting the ACES
   ``participant_runtime_capability_contract_gaps`` detector catches the
   premature claim (missing required contracts) both when the claim is
   unsupported and when the required contracts are actually present (so the
   detector can also report a clean bill of health, not just "always fail");
3. it asserts the detector's diagnostic strings are sanitized -- single-line,
   bounded, and free of secret-shaped substrings -- since this gate's output
   can surface in conformance run logs and review threads.

No production code changes ship with this file: the manifest already claims
nothing, and the gap-detector lives in the published ``aces-backend-protocols``
package.
"""

from __future__ import annotations

from aces_backend_protocols.capabilities import (
    BackendCapabilitySet,
    BackendManifest,
    ParticipantRuntimeCapabilities,
    participant_runtime_capability_contract_gaps,
)
from aces_conformance.conformance import BackendCapabilityProfile, profile_for_manifest

from shared import log_sanitize
from shared.aces.manifest import create_shifter_backend_manifest

# The premature claim used by the "caught" and "not vacuous" tests below: one
# term per participant-runtime dimension (role, behavior feature, interaction
# feature), each drawn from the ACES controlled vocabulary so construction
# succeeds regardless of whether the required contracts are present.
_CLAIMED_ROLE = "blue"
_CLAIMED_BEHAVIOR_FEATURE = "behavior_history"
_CLAIMED_INTERACTION_FEATURE = "coordination"

# The full contract surface required to make the claim above conformant,
# mirrors aces_backend_protocols.capabilities.PARTICIPANT_RUNTIME_CAPABILITY_REQUIRED_CONTRACTS
# for the three claimed terms.
_REQUIRED_CONTRACTS_FOR_CLAIM = frozenset(
    {
        "participant-episode-state-envelope-v1",
        "participant-episode-history-event-stream-v1",
        "participant-behavior-history-event-stream-v1",
        "participant-shared-state-record-v1",
        "participant-joint-action-record-v1",
        "participant-time-management-context-v1",
    }
)

_FORBIDDEN_SUBSTRINGS = (
    "BEGIN",
    "PRIVATE KEY",
    "Bearer ",
    "token=",
    "https://",
    "password",
    "AKIA",
)

_MAX_GAP_LENGTH = 512


def _manifest_with_participant_runtime_claim(supported_contract_versions: frozenset[str]) -> BackendManifest:
    """Return a mutated copy of Shifter's real manifest that additionally
    claims the ``_CLAIMED_*`` participant-runtime terms, with the given
    ``supported_contract_versions``.

    Every other manifest field (identity, compatibility, realization support,
    concept bindings, constraints, provisioner) is reused byte-for-byte from
    the real, published manifest, so this fixture only varies the one axis
    each test cares about: the participant-runtime claim and the contract
    surface backing it.
    """
    real_manifest = create_shifter_backend_manifest()
    participant_runtime = ParticipantRuntimeCapabilities(
        name="shifter-participant-runtime-test-fixture",
        supported_participant_roles=frozenset({_CLAIMED_ROLE}),
        supported_behavior_features=frozenset({_CLAIMED_BEHAVIOR_FEATURE}),
        supported_interaction_features=frozenset({_CLAIMED_INTERACTION_FEATURE}),
    )
    capabilities = BackendCapabilitySet(
        provisioner=real_manifest.provisioner,
        participant_runtime=participant_runtime,
    )
    return BackendManifest(
        identity=real_manifest.identity,
        supported_contract_versions=supported_contract_versions,
        compatibility=real_manifest.compatibility,
        realization_support=real_manifest.realization_support,
        concept_bindings=real_manifest.concept_bindings,
        constraints=real_manifest.constraints,
        capabilities=capabilities,
    )


def test_shifter_manifest_declares_no_participant_runtime():
    """Shifter's real, published manifest claims no participant runtime."""
    manifest = create_shifter_backend_manifest()

    assert manifest.participant_runtime is None
    assert manifest.has_participant_runtime is False
    assert profile_for_manifest(manifest) == BackendCapabilityProfile.PROVISIONING_ONLY


def test_current_manifest_has_no_participant_runtime_contract_gaps():
    """The real manifest is vacuously gap-free: it makes no claim to check."""
    manifest = create_shifter_backend_manifest()

    assert participant_runtime_capability_contract_gaps(manifest) == ()


def test_premature_participant_runtime_claim_is_caught():
    """A participant-runtime claim backed only by Shifter's real (provisioning-only)
    contract set is caught as a premature/over-claim: every required contract
    for the claimed role, behavior feature, and interaction feature is missing."""
    real_manifest = create_shifter_backend_manifest()
    premature_manifest = _manifest_with_participant_runtime_claim(
        supported_contract_versions=real_manifest.supported_contract_versions,
    )

    gaps = participant_runtime_capability_contract_gaps(premature_manifest)

    assert gaps
    joined = " ".join(gaps)
    for required_contract in _REQUIRED_CONTRACTS_FOR_CLAIM:
        assert required_contract in joined, f"expected gap diagnostics to name missing contract {required_contract!r}"


def test_conformance_gate_is_not_vacuous_when_contracts_present():
    """The same claim, backed by the full required contract surface, reports
    no gaps -- proving the detector can also pass, not just always fail."""
    real_manifest = create_shifter_backend_manifest()
    fully_backed_manifest = _manifest_with_participant_runtime_claim(
        supported_contract_versions=real_manifest.supported_contract_versions | _REQUIRED_CONTRACTS_FOR_CLAIM,
    )

    gaps = participant_runtime_capability_contract_gaps(fully_backed_manifest)

    assert gaps == ()


def test_conformance_gap_diagnostics_are_sanitized():
    """Gap diagnostics are single-line, bounded, and free of secret-shaped
    substrings, since this gate's output can land in conformance logs and
    review threads."""
    real_manifest = create_shifter_backend_manifest()
    premature_manifest = _manifest_with_participant_runtime_claim(
        supported_contract_versions=real_manifest.supported_contract_versions,
    )

    gaps = participant_runtime_capability_contract_gaps(premature_manifest)
    assert gaps, "fixture must produce at least one gap for this test to be meaningful"

    for gap in gaps:
        assert "\n" not in gap
        assert "\r" not in gap
        assert len(gap) < _MAX_GAP_LENGTH
        # A no-op round trip through the canonical sanitizer (bounded to this
        # test's own length cap, since the default safe_log_value max_len of
        # 200 is shorter than some legitimate multi-contract gap messages)
        # confirms the gap string already contains nothing safe_log_value
        # would need to escape -- i.e. it is already log-safe.
        assert log_sanitize.safe_log_value(gap, max_len=_MAX_GAP_LENGTH) == gap
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in gap, f"gap diagnostic must not contain secret-shaped substring {forbidden!r}"
