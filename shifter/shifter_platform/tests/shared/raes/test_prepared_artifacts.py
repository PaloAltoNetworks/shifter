"""Only verified outputs become requirement-scoped materialization facts."""

from uuid import uuid4

import pytest
from raes.artifact_requirements import ArtifactRequirement

from shared.raes.preparation_contract import AdapterManifest, PreparationPackage
from shared.raes.prepared_artifacts import admit_materialization_facts
from tests.shared.raes.test_preparation_contract import manifest_payload, requirement_payload
from tests.shared.raes.test_preparation_inputs import bound_input_fixture
from tests.shared.test_preparation_grant import grant_configuration


def admission_arguments():
    binding = bound_input_fixture()
    requirement = requirement_payload()
    requirement["constraints"] = [
        {"constraint_id": "os", "kind": "operating-system", "allowed_values": ["ubuntu:22.04"]}
    ]
    package = PreparationPackage(
        scenario_id="private-example",
        package_digest="sha256:" + "3" * 64,
        requirement_address="plan/private-example/web",
        requirement=ArtifactRequirement.model_validate(requirement),
        specification_id="example-image",
        input_bindings=[binding],
    )
    return {
        "operation_id": uuid4(),
        "attempt_id": uuid4(),
        "operation_input_digest": "sha256:" + "4" * 64,
        "package": package,
        "adapter": AdapterManifest.model_validate(manifest_payload()),
        "grant": grant_configuration(),
        "inputs": {
            "observations": [
                {
                    "input_id": binding.lock.input_id,
                    "image_ref": binding.image_ref,
                    "image_id": binding.image_id,
                    "disk_id": "444",
                    "raw_disk_digest": binding.artifact.digest,
                    "size_bytes": binding.size_bytes,
                }
            ]
        },
        "build": {
            "image_ref": "projects/test-project/global/images/prep-output",
            "image_id": "555",
            "source_disk_id": "333",
            "source_image_id": binding.image_id,
            "builder_instance_id": "222",
        },
        "output": {
            "image_ref": "projects/test-project/global/images/prep-output",
            "image_id": "555",
            "disk_id": "666",
            "raw_disk_digest": "sha256:" + "7" * 64,
            "size_bytes": binding.size_bytes,
            "sanitized": True,
            "boot_observed": True,
            "constraint_values": {"operating-system": "ubuntu:22.04"},
        },
    }


def test_measured_output_retains_exact_specification_locks_and_provider_identity():
    facts = admit_materialization_facts(**admission_arguments())
    assert facts.artifact.digest == "sha256:" + "7" * 64
    assert facts.satisfied_constraint_ids == ["os"]
    assert facts.locked_input_ids == ["base"]
    assert facts.image_id == "555"
    assert facts.specification.specification_id == "example-image"
    assert facts.integrity_ref and facts.provenance_ref


@pytest.mark.parametrize("failure", ["constraint", "input", "boot", "identity", "lineage", "trust"])
def test_partial_or_conflicting_evidence_cannot_be_admitted(failure):
    args = admission_arguments()
    if failure == "constraint":
        args["output"]["constraint_values"]["operating-system"] = "ubuntu:24.04"
    elif failure == "input":
        args["inputs"]["observations"] = []
    elif failure == "boot":
        args["output"]["boot_observed"] = False
    elif failure == "identity":
        args["output"]["image_id"] = "777"
    elif failure == "lineage":
        args["build"]["source_image_id"] = "777"
    else:
        args["grant"]["trusted_input_bindings"] = {}
    with pytest.raises(ValueError):
        admit_materialization_facts(**args)
