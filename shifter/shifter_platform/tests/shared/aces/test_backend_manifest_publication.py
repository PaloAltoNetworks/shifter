"""Issue #1261: publish Shifter's ``provisioning-only`` backend manifest.

These tests *publish* Shifter's ACES backend manifest by binding it to the
published ACES contract authorities shipped by ``aces-sdl`` -- the
``backend-manifest-v2`` Pydantic model, the ``provisioning-only`` backend
profile, and the conformance profile-inference runner -- so the issue #1261
acceptance criteria are locked against regression:

1. the manifest renders to a payload that validates against the published
   ``backend-manifest-v2`` model;
2. ``supported_contract_versions`` covers the published ``provisioning-only``
   profile contract set (exactly ``backend-manifest-v2``, ``operation-receipt-v1``,
   ``operation-status-v1``, ``runtime-snapshot-v1``);
3. the manifest infers as ``PROVISIONING_ONLY`` -- it declares no orchestrator,
   evaluator, participant-runtime, or observation capability;
4. every declared realization-support constraint kind is backed by a non-empty
   provisioner capability surface (no hollow over-claim); and
5. the Python builder renders byte-for-byte to the checked-in
   ``backend-manifest.json`` published artifact.

Live end-to-end target conformance (``run_target_conformance``) is intentionally
out of scope here: it requires a working ``RuntimeTarget``/``Provisioner``, which
is the RuntimeTarget-adapter slice (#1262). This publication slice validates the
manifest source, contract coverage, and profile inference only.
"""

from __future__ import annotations

import json
from pathlib import Path

from aces_conformance.conformance import (
    BackendCapabilityProfile,
    profile_for_manifest,
    required_contracts,
)
from aces_contracts.backend_profiles import load_backend_profile
from aces_contracts.contracts import BackendManifestV2Model

from shared.aces.manifest import (
    SHIFTER_BACKEND_PROFILE,
    SHIFTER_SUPPORTED_CONTRACT_VERSIONS,
    create_shifter_backend_manifest,
    render_shifter_backend_manifest_payload,
)

PUBLISHED_MANIFEST_PATH = Path(__file__).resolve().parents[3] / "shared" / "aces" / "backend-manifest.json"

# A realization-support constraint kind is truthful only when the provisioner
# capability surface that backs it is non-empty.
_CONSTRAINT_KIND_TO_PROVISIONER_SURFACE = {
    "node-type": "supported_node_types",
    "os-family": "supported_os_families",
    "content-type": "supported_content_types",
    "account-feature": "supported_account_features",
}


def test_profile_claim_is_provisioning_only():
    """The published profile discriminator is exactly ``provisioning-only``."""
    assert SHIFTER_BACKEND_PROFILE == "provisioning-only"


def test_manifest_validates_against_published_model():
    """AC1: the rendered payload validates against the published backend-manifest-v2 model."""
    payload = render_shifter_backend_manifest_payload()

    model = BackendManifestV2Model.model_validate(payload)

    assert model.identity.name == "shifter"


def test_supported_contract_versions_cover_provisioning_only_profile():
    """AC2: supported_contract_versions covers the published provisioning-only contract set exactly."""
    manifest = create_shifter_backend_manifest()

    profile_required = set(load_backend_profile(SHIFTER_BACKEND_PROFILE).required_contracts)
    runner_required = set(required_contracts(BackendCapabilityProfile.PROVISIONING_ONLY))

    assert profile_required, "published provisioning-only profile must declare required contracts"
    assert profile_required <= manifest.supported_contract_versions
    assert runner_required <= manifest.supported_contract_versions
    # This publication slice claims exactly the profile's required contracts and
    # nothing more -- no provisioning-plan or participant contracts are declared.
    assert manifest.supported_contract_versions == frozenset(profile_required)
    assert manifest.supported_contract_versions == SHIFTER_SUPPORTED_CONTRACT_VERSIONS


def test_manifest_infers_provisioning_only_profile():
    """AC2/AC3: the manifest declares no capability that would widen the profile."""
    manifest = create_shifter_backend_manifest()

    assert profile_for_manifest(manifest) == BackendCapabilityProfile.PROVISIONING_ONLY
    assert manifest.orchestrator is None
    assert manifest.evaluator is None
    assert manifest.participant_runtime is None
    assert manifest.observation is None


def test_realization_support_is_not_hollow():
    """AC3: every realization-support declaration discloses and is backed by real capability."""
    manifest = create_shifter_backend_manifest()
    provisioner = manifest.provisioner
    declarations = render_shifter_backend_manifest_payload()["realization_support"]

    assert declarations, "manifest must declare at least one realization-support domain"
    for declaration in declarations:
        assert declaration["disclosure_kinds"], "realization-support must disclose backend evidence kinds"
        for kind in declaration.get("supported_constraint_kinds", ()):
            surface = _CONSTRAINT_KIND_TO_PROVISIONER_SURFACE.get(kind)
            assert surface is not None, f"unmapped realization constraint kind {kind!r}"
            assert getattr(provisioner, surface), (
                f"realization declares constraint kind {kind!r} but provisioner surface "
                f"{surface!r} is empty (hollow over-claim)"
            )


def test_manifest_does_not_expose_backend_owned_realization_details():
    """Backend-owned realization stays backend-owned: no Terraform/cloud/secret leakage."""
    rendered = json.dumps(render_shifter_backend_manifest_payload()).lower()

    for forbidden in (
        "terraform",
        "ssm",
        "subnet",
        "cidr",
        "ngfw",
        "secret",
        "ami-",
        "arn:aws",
        "gcp",
        "instance_type",
    ):
        assert forbidden not in rendered, f"manifest must not expose backend-owned detail {forbidden!r}"


def test_builder_matches_checked_in_published_artifact():
    """AC/publication: the builder renders byte-for-byte to the checked-in artifact."""
    assert PUBLISHED_MANIFEST_PATH.exists(), f"published manifest artifact missing at {PUBLISHED_MANIFEST_PATH}"

    checked_in = json.loads(PUBLISHED_MANIFEST_PATH.read_text())

    assert render_shifter_backend_manifest_payload() == checked_in, (
        "checked-in backend-manifest.json is stale; regenerate it from create_shifter_backend_manifest()"
    )
