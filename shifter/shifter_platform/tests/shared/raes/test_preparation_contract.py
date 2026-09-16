"""Preparation joins authored permission to an installed exact adapter contract."""

from copy import deepcopy

import pytest
from raes.artifact_requirements import ArtifactRequirement

from shared.raes.preparation_contract import AdapterManifest, PreparationContractError, select_preparation


def manifest_payload():
    """One closed GCE profile with a pinned base and separately pinned verifier."""
    profile = {
        "mechanism": "materialization-specification",
        "profile": "shifter-gce-contained-build",
        "version": "1",
        "digest": "sha256:" + "a" * 64,
    }
    return {
        "protocol": "shifter.artifact-preparation/v1",
        "adapter_id": "private-example",
        "version": "1",
        "backend": "gce",
        "worker_image": "registry.example/private/build@sha256:" + "b" * 64,
        "verifier_image": "registry.example/private/verify@sha256:" + "c" * 64,
        "verification_contract": "shifter.gce-raw-disk/v1",
        "required_permissions": ["gce-image-build", "private-artifact-storage"],
        "specifications": [
            {
                "reference": {
                    "specification_id": "example-image",
                    "profile": profile,
                    "digest": "sha256:" + "d" * 64,
                    "locked_input_ids": ["base"],
                },
                "locked_inputs": [
                    {
                        "input_id": "base",
                        "artifact": {
                            "artifact_id": "base-image",
                            "version": "1",
                            "digest": "sha256:" + "e" * 64,
                            "media_type": "application/vnd.shifter.raw-disk",
                        },
                        "associated_artifact_manifest_ref": "base-manifest",
                        "trust_policy_ref": "tenant-input-policy",
                    }
                ],
                "constraint_kinds": ["operating-system"],
            }
        ],
    }


def requirement_payload():
    """Author permission names the exact installed profile, spec and fixed base."""
    spec = manifest_payload()["specifications"][0]
    return {
        "requirement_id": "private-image",
        "explicitness": "constrained",
        "materialization_specifications": [deepcopy(spec["reference"])],
        "locked_inputs": deepcopy(spec["locked_inputs"]),
        "permitted_routes": [
            {
                "mechanism": deepcopy(spec["reference"]["profile"]),
                "acquisition": "none",
                "timing": "backend-preparation",
            }
        ],
    }


def test_selects_only_the_exact_authored_materialization():
    adapter = AdapterManifest.model_validate(manifest_payload())
    selection = select_preparation(ArtifactRequirement.model_validate(requirement_payload()), adapter, "example-image")
    assert selection.specification.digest == "sha256:" + "d" * 64
    assert selection.route.timing == "backend-preparation"
    assert selection.locked_inputs[0].artifact.digest == "sha256:" + "e" * 64


@pytest.mark.parametrize("field", ["digest", "specification_id"])
def test_rejects_specification_identity_drift(field):
    raw = requirement_payload()
    raw["materialization_specifications"][0][field] = "sha256:" + "f" * 64
    with pytest.raises(PreparationContractError):
        select_preparation(
            ArtifactRequirement.model_validate(raw), AdapterManifest.model_validate(manifest_payload()), "example-image"
        )


def test_rejects_same_profile_name_with_changed_digest():
    raw = requirement_payload()
    raw["materialization_specifications"][0]["profile"]["digest"] = "sha256:" + "f" * 64
    raw["permitted_routes"][0]["mechanism"]["digest"] = "sha256:" + "f" * 64
    with pytest.raises(PreparationContractError):
        select_preparation(
            ArtifactRequirement.model_validate(raw), AdapterManifest.model_validate(manifest_payload()), "example-image"
        )


@pytest.mark.parametrize("field,value", [("digest", "sha256:" + "f" * 64), ("version", "2"), ("artifact_id", "other")])
def test_locked_input_names_do_not_authorize_changed_identity(field, value):
    raw = requirement_payload()
    raw["locked_inputs"][0]["artifact"][field] = value
    with pytest.raises(PreparationContractError):
        select_preparation(
            ArtifactRequirement.model_validate(raw), AdapterManifest.model_validate(manifest_payload()), "example-image"
        )


def test_declaration_does_not_authorize_other_timing():
    raw = requirement_payload()
    raw["permitted_routes"][0]["timing"] = "realization"
    with pytest.raises(PreparationContractError):
        select_preparation(
            ArtifactRequirement.model_validate(raw), AdapterManifest.model_validate(manifest_payload()), "example-image"
        )


@pytest.mark.parametrize("field", ["worker_image", "verifier_image"])
def test_mutable_worker_or_verifier_image_is_not_installable(field):
    raw = manifest_payload()
    raw[field] = "registry.example/private/worker:latest"
    with pytest.raises(ValueError):
        AdapterManifest.model_validate(raw)


def test_manifest_cannot_smuggle_pod_or_shell_overrides():
    raw = manifest_payload()
    raw["command"] = ["sh", "-c", "untrusted"]
    with pytest.raises(ValueError):
        AdapterManifest.model_validate(raw)


def test_manifest_cannot_omit_or_duplicate_declared_input_locks():
    for inputs in ([], manifest_payload()["specifications"][0]["locked_inputs"] * 2):
        raw = manifest_payload()
        raw["specifications"][0]["locked_inputs"] = inputs
        with pytest.raises(ValueError):
            AdapterManifest.model_validate(raw)


def test_absent_concern_never_requests_preparation():
    with pytest.raises(PreparationContractError):
        select_preparation(None, AdapterManifest.model_validate(manifest_payload()), "example-image")
