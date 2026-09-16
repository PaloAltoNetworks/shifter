"""Issue #1261: publish Shifter's ``provisioning-only`` backend manifest.

These tests *publish* Shifter's RAES backend manifest by binding it to the
published RAES contract authorities shipped by ``raes`` -- the
``backend-manifest-v2`` Pydantic model, the ``provisioning-only`` backend
profile, and the conformance profile-inference runner -- so the issue #1261
acceptance criteria are locked against regression:

1. the manifest renders to a payload that validates against the published
   ``backend-manifest-v2`` model;
2. ``supported_contract_versions`` covers the published ``provisioning-only``
   profile contract set;
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
from dataclasses import replace
from pathlib import Path

from raes_backend_protocols.capabilities import BackendCapabilitySet
from raes_conformance.conformance import (
    BackendCapabilityProfile,
    profile_for_manifest,
    required_contracts,
)
from raes_contracts.backend_profiles import load_backend_profile
from raes_contracts.contracts import BackendManifestV2Model
from raes_contracts.realization_envelope import realizer_configuration_digest

from shared.raes.manifest import (
    SHIFTER_BACKEND_PROFILE,
    SHIFTER_SUPPORTED_CONTRACT_VERSIONS,
    create_shifter_backend_manifest,
    render_shifter_backend_manifest_payload,
)
from shared.raes.realization import (
    SHIFTER_REALIZER_CONFIGURATION,
    create_shifter_realization_envelope,
)

PUBLISHED_MANIFEST_PATH = Path(__file__).resolve().parents[3] / "shared" / "raes" / "backend-manifest.json"
PUBLISHED_ENVELOPE_PATH = Path(__file__).resolve().parents[3] / "shared" / "raes" / "backend-realization-envelope.json"

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
    assert manifest.supported_contract_versions == frozenset(profile_required)
    assert manifest.supported_contract_versions == SHIFTER_SUPPORTED_CONTRACT_VERSIONS


def test_generic_manifest_withholds_scenario_bound_realization_envelope():
    """Publication cannot claim a constructive carrier before target selection."""
    manifest = create_shifter_backend_manifest()

    assert manifest.realization_envelope is None
    assert "realization-envelope-v1" not in manifest.supported_contract_versions


def test_checked_in_envelope_is_the_configured_conformance_fixture():
    """The standalone qualification carrier is generated for its named fixture."""
    expected = create_shifter_realization_envelope(scenario_name="shifter-conformance", compute_node_name="vm")

    assert json.loads(PUBLISHED_ENVELOPE_PATH.read_text()) == expected.model_dump(mode="json")


def test_realizer_configuration_is_public_complete_and_digest_bound():
    """The independent realization evidence uses RAES's published model."""
    manifest = create_shifter_backend_manifest()
    configuration = SHIFTER_REALIZER_CONFIGURATION

    assert configuration.configuration_digest == realizer_configuration_digest(configuration)
    assert frozenset(configuration.supported_account_features) == manifest.provisioner.supported_account_features


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
            if kind == "source-artifact":
                # Artifact authority is in the public mechanism declaration;
                # node/OS capability lists do not describe portable identities.
                mechanisms = declaration["artifact_mechanisms"]
                assert mechanisms and all(
                    "source-artifact" in item["supported_requirement_kinds"] for item in mechanisms
                )
                assert {item["mechanism"]["mechanism"] for item in mechanisms} == {"exact-artifact"}
                continue
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


def test_provisioner_capabilities_are_the_narrowed_ledger():
    """#1563: the manifest declares only genuinely-realized provisioning terms."""
    provisioner = create_shifter_backend_manifest().provisioner

    assert provisioner.supported_account_features == frozenset(
        {"groups", "shell", "home", "disabled", "auth_method", "spn"}
    )
    assert provisioner.supported_content_types == frozenset({"file", "directory"})
    assert provisioner.supported_domain_profiles == frozenset({"active_directory"})
    # Removed over-claims stay out until their sibling issue lands genuine realization
    # (auth_method -> #1560, spn -> #1561). #1564 re-declares file + directory now
    # that every admitted shape (inline text, empty dir, source-backed file/dir) has a
    # genuine, digest-verified guest effect; dataset stays out (no deterministic
    # materializer + readback for its item-only / generator shapes).
    for dropped in ("mail",):
        assert dropped not in provisioner.supported_account_features
    for dropped in ("dataset",):
        assert dropped not in provisioner.supported_content_types

    checked_in = json.loads(PUBLISHED_MANIFEST_PATH.read_text())
    assert checked_in["capabilities"]["provisioner"]["supported_domain_profiles"] == ["active_directory"]


def test_provisioner_declares_ipv4_only_network_address_family(tmp_path):
    """#1568: the provisioner honestly publishes IPv4-only networking as a constraint.

    ``switch`` stays supported (Shifter realizes IPv4 networks), the constraint is
    the opaque ``constraints`` disclosure surface (not a made-up capability enum or
    realization-support kind), the profile is unchanged, and the rendered payload
    carries the same constraint without leaking any provider/subnet/CIDR detail.
    """
    del tmp_path
    manifest = create_shifter_backend_manifest()
    provisioner = manifest.provisioner

    assert provisioner.constraints["network-address-family"] == "ipv4-only"
    # switch is required for any networked scenario and stays claimed; the limitation
    # is the address family, not networking itself.
    assert "switch" in provisioner.supported_node_types
    assert profile_for_manifest(manifest) == BackendCapabilityProfile.PROVISIONING_ONLY

    payload = render_shifter_backend_manifest_payload()
    assert payload["capabilities"]["provisioner"]["constraints"]["network-address-family"] == "ipv4-only"


def test_profile_inference_does_not_catch_a_term_level_overclaim():
    """#1563: profile inference is blind to a term-level over-claim, so realizability is
    guarded by exact-set assertions (above) and the apply-time evidence gate, not profile shape."""
    honest = create_shifter_backend_manifest()
    overclaimed_provisioner = replace(
        honest.provisioner,
        supported_account_features=honest.provisioner.supported_account_features | {"mail"},
    )
    overclaimed = replace(honest, capabilities=BackendCapabilitySet(provisioner=overclaimed_provisioner))

    # Re-declaring a still-unrealized account term does not change the profile ...
    assert profile_for_manifest(overclaimed) == BackendCapabilityProfile.PROVISIONING_ONLY
    assert profile_for_manifest(overclaimed) == profile_for_manifest(honest)
    # ... so a generic provisioning-only conformance pass is not realizability evidence.
    assert "mail" not in honest.provisioner.supported_account_features
