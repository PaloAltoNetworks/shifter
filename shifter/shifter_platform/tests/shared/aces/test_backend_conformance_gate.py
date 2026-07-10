"""Issue #1263: ACES backend conformance gate.

This is the automated conformance gate for Shifter's initial ACES backend
profile claim. Shifter publishes a single ``provisioning-only`` backend manifest
(``shared.aces.manifest`` + the checked-in
``shifter/shifter_platform/shared/aces/backend-manifest.json`` artifact, issue
#1261). This gate proves that claim stays honest by validating it through
ACES-owned contract/profile/conformance tooling -- Shifter does not reimplement
profile inference, required-contract calculation, or the conformance verdict
(see ``docs/architecture/aces-backend-conformance-gate-preflight-1263.md`` and
the design source ``...-preflight-1233.md``).

It complements the #1261 publication tests
(``test_backend_manifest_publication.py``) rather than duplicating them. Those
lock the manifest source, contract coverage, profile inference, and
builder/artifact byte-for-byte sync. This gate adds the conformance behaviour on
top:

1. it runs the ACES fixture conformance runner for the ``provisioning-only``
   profile and asserts Shifter's published manifest (both the builder and the
   checked-in artifact) validates against it;
2. it proves the gate is not vacuous -- a manifest that widens capabilities
   (declares an orchestrator) or drops a required contract fails the gate, while
   the honest manifest passes, so the gate can report both a clean bill of
   health and a real failure;
3. it asserts the gate's diagnostics are bounded and sanitized -- single-line,
   length-capped, and free of secret- or provider-realization-shaped substrings
   -- since conformance output can surface in CI logs and review threads.

The gate is exercised through the parameterized ``run_backend_conformance_gate``
seam (manifest, expected profile, manifest ref). A later orchestrator,
evaluator, participant-runtime, observation, or live ``RuntimeTarget`` (#1262 /
#1264) variant extends that seam with a new profile/parameter rather than
copying the gate into CMS, engine, provisioner, or workflow code.

No production code ships with this gate: the manifest already claims exactly
``provisioning-only`` and the conformance tooling lives in the dev/test-scoped
``aces-sdl`` package, so nothing here pulls ACES into Shifter's runtime import
graph.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from aces_backend_protocols.capabilities import (
    BackendCapabilitySet,
    BackendManifest,
    OrchestratorCapabilities,
)
from aces_conformance.conformance import (
    BackendCapabilityProfile,
    profile_for_manifest,
    required_contracts,
    run_fixture_suite,
    run_target_conformance,
)
from aces_contracts.contracts import BackendManifestV2Model

from shared import log_sanitize
from shared.aces.dispatch_port import ShifterDispatchResult
from shared.aces.manifest import create_shifter_backend_manifest
from shared.aces.runtime_target import create_shifter_backend_target

PUBLISHED_MANIFEST_PATH = Path(__file__).resolve().parents[3] / "shared" / "aces" / "backend-manifest.json"

#: Shifter's first and only backend profile claim.
EXPECTED_PROFILE = BackendCapabilityProfile.PROVISIONING_ONLY

#: Upper bound on any single sanitized diagnostic line. Wide enough for a
#: legitimate multi-contract gap message, tight enough that an unbounded dump
#: (a raw payload, a stack trace, a serialized manifest) cannot pass.
_MAX_DIAGNOSTIC_LENGTH = 512

#: Substrings a conformance diagnostic must never contain. Combines the
#: secret-shaped set guarded by the #1291 participant-runtime gate with the
#: backend-owned realization detail the #1261 publication test forbids in the
#: manifest payload, since this gate's output has the same leakage surface.
_FORBIDDEN_SUBSTRINGS = (
    "BEGIN",
    "PRIVATE KEY",
    "Bearer ",
    "token=",
    "https://",
    "password",
    "AKIA",
    "arn:aws",
    "terraform",
    "ssm",
    "ami-",
    "secret",
    "subnet",
    "cidr",
    "ngfw",
    "instance_type",
)


def _sanitize_diagnostic(message: str) -> str:
    """Render a gate diagnostic as a bounded, single-line, log-safe string."""
    return log_sanitize.safe_log_value(message, max_len=_MAX_DIAGNOSTIC_LENGTH)


def run_backend_conformance_gate(
    manifest: BackendManifest,
    *,
    expected_profile: BackendCapabilityProfile,
    manifest_ref: str,
    profiles_root: Path | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Validate ``manifest`` against ``expected_profile`` via ACES-owned tooling.

    Returns ``(passed, diagnostics)`` where ``diagnostics`` is a tuple of
    bounded, sanitized single-line strings. ACES tooling is the authority:
    :func:`profile_for_manifest`, :func:`required_contracts`, and
    :func:`run_fixture_suite` provide profile inference, the required-contract
    set, and the fixture verdict. This helper only adapts the invocation shape
    and bounds/sanitizes the output; it does not reimplement any verdict logic.

    ``profiles_root`` overrides the published backend-profile corpus (defaulting
    to the canonical ACES corpus); tests use it to exercise the profile-load
    failure path.
    """
    expected_profile_id = expected_profile.value
    diagnostics: list[str] = []

    inferred = profile_for_manifest(manifest)
    if inferred != expected_profile:
        diagnostics.append(
            _sanitize_diagnostic(
                f"{manifest_ref}: manifest infers profile {inferred.value!r}, expected {expected_profile_id!r}"
            )
        )

    report = run_fixture_suite(profile=expected_profile, profiles_root=profiles_root)

    # ``required_contracts`` raises when the profile artifact cannot be loaded;
    # ``run_fixture_suite`` surfaces that same failure as a structured
    # ``conformance.profile-load-failed`` diagnostic instead. Only compute the
    # manifest-vs-profile contract check when the profile actually loaded, so the
    # gate reports one sanitized load-failure diagnostic rather than raising.
    profile_loaded = not any(diag.code == "conformance.profile-load-failed" for diag in report.diagnostics)
    if profile_loaded:
        # The claim is *exactly* ``expected_profile``: the manifest must declare
        # the profile's required contract set and no more. A subset check would
        # let the manifest widen its supported-contract surface with unevidenced
        # extras; the exact comparison against the ACES-owned required set
        # (``required_contracts``) catches both a missing required contract and
        # an over-declared one without reimplementing the contract calculation.
        required = required_contracts(expected_profile, profiles_root=profiles_root)
        supported = manifest.supported_contract_versions
        missing_contracts = sorted(required - supported)
        if missing_contracts:
            diagnostics.append(
                _sanitize_diagnostic(
                    f"{manifest_ref}: manifest is missing required {expected_profile_id!r} "
                    f"contracts: {', '.join(missing_contracts)}"
                )
            )
        unexpected_contracts = sorted(supported - required)
        if unexpected_contracts:
            diagnostics.append(
                _sanitize_diagnostic(
                    f"{manifest_ref}: manifest declares contracts beyond the {expected_profile_id!r} "
                    f"required set without conformance evidence: {', '.join(unexpected_contracts)}"
                )
            )

    if not report.passed:
        diagnostics.append(
            _sanitize_diagnostic(f"{manifest_ref}: ACES fixture conformance failed for profile {expected_profile_id!r}")
        )
    diagnostics.extend(_sanitize_diagnostic(f"{diag.code}: {diag.message}") for diag in report.diagnostics)

    return not diagnostics, tuple(diagnostics)


def _manifest_with_orchestration_claim() -> BackendManifest:
    """Return a copy of Shifter's real manifest that additionally declares an
    orchestrator capability.

    Only the capability set varies; identity, compatibility, realization
    support, concept bindings, and constraints are reused byte-for-byte from the
    real published manifest. Declaring an orchestrator widens the inferred
    profile past ``provisioning-only`` (to ``orchestration-capable``), which the
    gate must catch.
    """
    real = create_shifter_backend_manifest()
    capabilities = BackendCapabilitySet(
        provisioner=real.provisioner,
        orchestrator=OrchestratorCapabilities(
            name="shifter-orchestrator-test-fixture",
            supported_sections=frozenset({"injects", "events", "scripts", "stories"}),
        ),
    )
    return BackendManifest(
        identity=real.identity,
        supported_contract_versions=real.supported_contract_versions,
        compatibility=real.compatibility,
        realization_support=real.realization_support,
        concept_bindings=real.concept_bindings,
        constraints=real.constraints,
        capabilities=capabilities,
    )


def _manifest_with_contract_versions(supported_contract_versions: frozenset[str]) -> BackendManifest:
    """Return a copy of Shifter's real manifest with an altered contract set.

    Capabilities are unchanged, so the manifest still infers as
    ``provisioning-only``; only the declared ``supported_contract_versions``
    varies, letting a test drop a required contract without widening the
    profile.
    """
    real = create_shifter_backend_manifest()
    return BackendManifest(
        identity=real.identity,
        supported_contract_versions=supported_contract_versions,
        compatibility=real.compatibility,
        realization_support=real.realization_support,
        concept_bindings=real.concept_bindings,
        constraints=real.constraints,
        capabilities=BackendCapabilitySet(provisioner=real.provisioner),
    )


def test_shifter_backend_manifest_conformance_gate_passes():
    """Shifter's real, published manifest passes the provisioning-only gate."""
    manifest = create_shifter_backend_manifest()

    passed, diagnostics = run_backend_conformance_gate(
        manifest,
        expected_profile=EXPECTED_PROFILE,
        manifest_ref="shared.aces.manifest",
    )

    assert passed, f"expected the honest manifest to pass; diagnostics: {diagnostics}"
    assert diagnostics == ()


def test_provisioning_only_fixture_suite_is_non_vacuous_and_passes():
    """The ACES fixture runner the gate relies on actually validates cases."""
    report = run_fixture_suite(profile=EXPECTED_PROFILE)

    assert report.passed
    assert report.cases, "fixture suite must exercise at least one case for the gate to be meaningful"
    assert report.diagnostics == ()


def test_checked_in_artifact_validates_as_provisioning_only_through_aces_tooling():
    """The published ``backend-manifest.json`` artifact validates through the ACES
    ``backend-manifest-v2`` model and declares only the provisioning-only surface."""
    assert PUBLISHED_MANIFEST_PATH.exists(), f"published manifest artifact missing at {PUBLISHED_MANIFEST_PATH}"
    payload = json.loads(PUBLISHED_MANIFEST_PATH.read_text())

    model = BackendManifestV2Model.model_validate(payload)

    assert model.identity.name == "shifter"
    # provisioning-only: no widening capability is declared.
    assert model.capabilities.orchestrator is None
    assert model.capabilities.evaluator is None
    assert model.capabilities.participant_runtime is None
    assert model.capabilities.observation is None
    # and the artifact declares exactly the profile's required contract surface --
    # no missing contract and no unevidenced widening.
    assert set(model.supported_contract_versions) == required_contracts(EXPECTED_PROFILE)


def test_conformance_gate_is_not_vacuous_when_capabilities_widen():
    """A manifest that widens capabilities past provisioning-only fails the gate,
    while the honest manifest passes -- so the gate is not always-fail."""
    honest_passed, _ = run_backend_conformance_gate(
        create_shifter_backend_manifest(),
        expected_profile=EXPECTED_PROFILE,
        manifest_ref="honest",
    )
    assert honest_passed

    over_claiming = _manifest_with_orchestration_claim()
    assert profile_for_manifest(over_claiming) == BackendCapabilityProfile.ORCHESTRATION_CAPABLE

    passed, diagnostics = run_backend_conformance_gate(
        over_claiming,
        expected_profile=EXPECTED_PROFILE,
        manifest_ref="over-claim",
    )

    assert not passed
    assert any("orchestration-capable" in diag for diag in diagnostics), (
        f"expected a profile-inference mismatch diagnostic; got {diagnostics}"
    )


def test_conformance_gate_catches_dropped_required_contract():
    """A manifest that drops a required provisioning-only contract fails the gate."""
    real = create_shifter_backend_manifest()
    dropped_contract = "operation-receipt-v1"
    assert dropped_contract in real.supported_contract_versions

    weakened = _manifest_with_contract_versions(real.supported_contract_versions - {dropped_contract})
    # Dropping a contract does not widen the profile: it still infers as provisioning-only.
    assert profile_for_manifest(weakened) == EXPECTED_PROFILE

    passed, diagnostics = run_backend_conformance_gate(
        weakened,
        expected_profile=EXPECTED_PROFILE,
        manifest_ref="dropped-contract",
    )

    assert not passed
    joined = " ".join(diagnostics)
    assert dropped_contract in joined
    assert "missing required" in joined


def test_conformance_gate_catches_added_unevidenced_contract():
    """A manifest that declares a contract beyond the provisioning-only required
    set -- widening the published surface without conformance evidence -- fails
    the gate, even though its capabilities still infer as provisioning-only."""
    real = create_shifter_backend_manifest()
    extra_contract = "orchestration-plan-v1"
    assert extra_contract not in real.supported_contract_versions
    assert extra_contract not in required_contracts(EXPECTED_PROFILE)

    widened = _manifest_with_contract_versions(real.supported_contract_versions | {extra_contract})
    # Declaring an extra contract does not change capabilities, so the profile still infers as provisioning-only.
    assert profile_for_manifest(widened) == EXPECTED_PROFILE

    passed, diagnostics = run_backend_conformance_gate(
        widened,
        expected_profile=EXPECTED_PROFILE,
        manifest_ref="added-contract",
    )

    assert not passed
    joined = " ".join(diagnostics)
    assert extra_contract in joined
    assert "beyond the" in joined


class _ConformanceProbeDispatchPort:
    """In-process dispatch port for the live conformance probe.

    Accepts every serialized plan without DB/cloud so the ACES live probe
    exercises the real ShifterProvisioner.apply path (validate -> dispatch ->
    snapshot) against the reference scenario, proving the backend genuinely
    realizes a plan (non-empty changed_addresses + a PROVISIONING snapshot entry)
    rather than passing on schema validation alone.
    """

    request_id = "00000000-0000-0000-0000-0000000000ab"

    def realize(self, compiled_plan) -> ShifterDispatchResult:
        return ShifterDispatchResult(request_id=self.request_id, accepted=True, status="accepted")


def test_live_target_conformance_provisioning_only_is_non_vacuous():
    """The Shifter RuntimeTarget backend passes the ACES *live* target probe.

    ``run_target_conformance`` drives the backend through the ACES
    RuntimeManager/RuntimeControlPlane against the reference scenario and fails a
    vacuous pass: it requires the apply to report a non-empty changed_addresses
    set and a PROVISIONING snapshot entry. This is the primary oracle for the
    ACES-native backend (PLAT-2009), complementing the fixture gate above.
    """
    target = create_shifter_backend_target(port=_ConformanceProbeDispatchPort())

    report = run_target_conformance(target, profile=EXPECTED_PROFILE)

    assert report.passed, f"live target conformance failed: {[(d.code, d.message) for d in report.diagnostics]}"
    assert report.cases, "live conformance must exercise at least one case"
    assert report.diagnostics == ()


def test_conformance_gate_diagnostics_are_bounded_and_sanitized():
    """Gate diagnostics are single-line, bounded, and free of secret- or
    provider-realization-shaped substrings across both failure modes (a widened
    capability set and a profile that cannot be loaded)."""
    _, widen_diagnostics = run_backend_conformance_gate(
        _manifest_with_orchestration_claim(),
        expected_profile=EXPECTED_PROFILE,
        manifest_ref="over-claim",
    )

    with tempfile.TemporaryDirectory() as empty_profiles_root:
        load_failed, load_failure_diagnostics = run_backend_conformance_gate(
            create_shifter_backend_manifest(),
            expected_profile=EXPECTED_PROFILE,
            manifest_ref="isolated-profile-root",
            profiles_root=Path(empty_profiles_root),
        )
    assert not load_failed, "an empty profile corpus must fail the gate"

    all_diagnostics = (*widen_diagnostics, *load_failure_diagnostics)
    assert all_diagnostics, "both failure modes must produce diagnostics for this test to be meaningful"

    for diagnostic in all_diagnostics:
        assert "\n" not in diagnostic
        assert "\r" not in diagnostic
        assert len(diagnostic) <= _MAX_DIAGNOSTIC_LENGTH
        # Re-running the canonical sanitizer is a no-op: the diagnostic is already log-safe.
        assert log_sanitize.safe_log_value(diagnostic, max_len=_MAX_DIAGNOSTIC_LENGTH) == diagnostic
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in diagnostic, f"diagnostic must not contain leak-shaped substring {forbidden!r}"
