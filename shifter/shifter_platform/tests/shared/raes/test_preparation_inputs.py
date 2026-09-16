"""Public byte binding and independent raw measurements remain distinct gates."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from raes.artifact_requirements import ArtifactLockedInput
from raes.scenarios import load_scenario
from raes_contracts.associated_artifacts import associated_artifact_set_digest
from raes_contracts.contracts import AssociatedArtifactManifestModel

from shared.raes.preparation_inputs import bind_input_material, load_input_material, verify_input_observations
from tests.shared.raes.test_preparation_contract import manifest_payload


def input_material_fixture():
    scenario = load_scenario(Path(__file__).parent / "fixtures/launchable/shifter-launch-min.sdl.yaml")
    lock = ArtifactLockedInput.model_validate(manifest_payload()["specifications"][0]["locked_inputs"][0])
    descriptor = {
        "protocol": "shifter.gce-input/v1",
        "artifact": lock.artifact.model_dump(mode="json"),
        "image_ref": "projects/ubuntu-os-cloud/global/images/ubuntu-base",
        "image_id": "12345",
        "size_bytes": 10737418240,
    }
    payload = json.dumps(descriptor, sort_keys=True).encode()
    raw = {
        "schema_version": "associated-artifact-manifest/v1",
        "manifest_id": "base-input",
        "manifest_version": "1",
        "canonicalization_profile": "associated-artifact-set/v1",
        "scope": "scenario",
        "parent_ref": {"ref_kind": "scenario", "ref_id": scenario.name},
        "artifacts": {
            "base": {
                "artifact_id": "base",
                "role": "other",
                "media_type": "application/vnd.shifter.gce-input+json",
                "uri": "raes-environment-pack:/preparation/base.json",
                "checksum": {"algorithm": "sha256", "value": hashlib.sha256(payload).hexdigest()},
                "size_bytes": len(payload),
                "created_at": "2026-09-13T00:00:00Z",
                "source": "operator",
                "sensitivity": "internal",
                "satisfies_refs": [],
            },
        },
        "set_digest": "sha256:" + "0" * 64,
    }
    raw["set_digest"] = associated_artifact_set_digest(AssociatedArtifactManifestModel.model_validate(raw))
    return scenario, lock, raw, payload


@pytest.fixture
def material():
    return input_material_fixture()


def bound_input_fixture():
    return bind(input_material_fixture())


def bind(material):
    scenario, lock, manifest, payload = material
    return bind_input_material(
        lock, manifest_bytes=json.dumps(manifest).encode(), descriptor_bytes=payload, parent=scenario
    )


def test_real_descriptor_bytes_are_validated_by_public_manifest_contract(material):
    bound = bind(material)
    assert bound.lock == material[1]
    assert bound.manifest_digest == material[2]["set_digest"]
    assert bound.image_id == "12345"
    assert bound.digest.startswith("sha256:")


@pytest.mark.parametrize("failure", ["bytes", "parent", "set-digest", "identity", "extra-payload"])
def test_declared_reference_is_insufficient_to_bind_input(material, failure):
    scenario, lock, raw, payload = material
    raw = deepcopy(raw)
    if failure == "bytes":
        payload += b" "
    elif failure == "parent":
        raw["parent_ref"]["ref_id"] = "foreign-scenario"
    elif failure == "set-digest":
        raw["set_digest"] = "sha256:" + "1" * 64
    elif failure == "identity":
        lock = lock.model_copy(update={"artifact": lock.artifact.model_copy(update={"version": "other"})})
    else:
        raw["artifacts"]["other"] = {**raw["artifacts"]["base"], "artifact_id": "other", "uri": "file:/other"}
    with pytest.raises(ValueError):
        bind_input_material(lock, manifest_bytes=json.dumps(raw).encode(), descriptor_bytes=payload, parent=scenario)


def test_only_exact_independently_measured_bytes_and_explicit_trust_admit_input(material):
    bound = bind(material)
    observation = {
        "input_id": bound.lock.input_id,
        "image_ref": bound.image_ref,
        "image_id": bound.image_id,
        "disk_id": "9876",
        "raw_disk_digest": bound.lock.artifact.digest,
        "size_bytes": bound.size_bytes,
    }
    policy = {bound.lock.trust_policy_ref: [bound.digest]}
    assert verify_input_observations([bound], [observation], policy) == [bound.lock.input_id]
    for field, value in (("image_id", "5555"), ("raw_disk_digest", "sha256:" + "2" * 64), ("size_bytes", 512)):
        with pytest.raises(ValueError):
            verify_input_observations([bound], [{**observation, field: value}], policy)
    for observations, trust in (([], policy), ([observation, observation], policy), ([observation], {})):
        with pytest.raises(ValueError):
            verify_input_observations([bound], observations, trust)


def test_input_loader_reads_only_contained_real_pack_payloads(material, tmp_path):
    scenario, lock, manifest, payload = material
    (tmp_path / "base-manifest").write_text(json.dumps(manifest))
    (tmp_path / "preparation").mkdir()
    descriptor = tmp_path / "preparation/base.json"
    descriptor.write_bytes(payload)
    assert load_input_material(tmp_path, scenario, [lock]) == [bind(material)]
    descriptor.unlink()
    outside = tmp_path.parent / "outside-descriptor"
    outside.write_bytes(payload)
    descriptor.symlink_to(outside)
    with pytest.raises(ValueError):
        load_input_material(tmp_path, scenario, [lock])


def test_input_loader_refuses_traversal_before_opening_a_manifest(material, tmp_path):
    scenario, lock, _, _ = material
    escaped = lock.model_copy(update={"associated_artifact_manifest_ref": "../outside.json"})
    with pytest.raises(ValueError):
        load_input_material(tmp_path, scenario, [escaped])
