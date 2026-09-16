"""Prepared inventory satisfies only the exact qualified materialization contract."""

from dataclasses import replace

import pytest

from shared.raes.artifact_inventory import BackendArtifact, build_artifact_supply, resolve_plan_artifact_bindings
from shared.raes.artifact_resolution import ArtifactResolutionStatus, resolve_artifact_requirement
from shared.raes.manifest import shifter_backend_apparatus
from shared.raes.prepared_artifacts import admit_materialization_facts
from tests.shared.raes.test_prepared_artifacts import admission_arguments


def inventory_fixture():
    args = admission_arguments()
    facts = admit_materialization_facts(**args)
    inventory = BackendArtifact(
        artifact_id=facts.artifact.artifact_id,
        version=facts.artifact.version,
        digest=facts.artifact.digest,
        media_type=facts.artifact.media_type,
        integrity_ref=facts.integrity_ref,
        provenance_ref=facts.provenance_ref,
        image_ref=facts.image_ref,
        image_id=facts.image_id,
        materialization=facts,
    )
    return args["package"].requirement, inventory


def test_private_prepared_inventory_produces_public_disclosure_and_fixed_launch_binding():
    requirement, owned = inventory_fixture()
    address = "plan/private/web"
    supply = build_artifact_supply({address: requirement}, [owned])
    resolution = resolve_artifact_requirement(
        requirement,
        address=address,
        capabilities=supply.capabilities,
        availability=supply.availability[address],
        backend=shifter_backend_apparatus(),
        prepared_materializations=supply.materializations,
    )
    assert resolution.status == ArtifactResolutionStatus.SATISFIED
    assert resolution.disclosure.materialization_specification_digest == owned.materialization.specification.digest
    assert resolution.disclosure.artifact.digest == owned.digest
    assert resolution.disclosure.locked_input_ids == ["base"]
    plan = {
        "resources": {
            "web": {
                "resource_type": "node",
                "address": address,
                "payload": {
                    "spec": {
                        "node": {
                            "source": {"artifact_requirement": requirement.model_dump(mode="json")},
                        }
                    }
                },
            }
        }
    }
    bindings = resolve_plan_artifact_bindings(
        plan, inventory=[owned], capabilities=(), backend=shifter_backend_apparatus()
    )
    assert bindings[0].image_ref == owned.image_ref and bindings[0].image_id == "555"


@pytest.mark.parametrize("drift", ["requirement", "lock", "specification", "provider", "artifact", "trust"])
def test_similar_or_mutated_inventory_cannot_substitute_for_verified_materialization(drift):
    requirement, owned = inventory_fixture()
    raw = requirement.model_dump(mode="json")
    if drift == "requirement":
        raw["requirement_id"] = "different"
    elif drift == "lock":
        raw["locked_inputs"][0]["artifact"]["version"] = "2"
    elif drift == "specification":
        raw["materialization_specifications"][0]["digest"] = "sha256:" + "8" * 64
    elif drift == "provider":
        owned = replace(owned, image_id="999")
    elif drift == "artifact":
        owned = replace(owned, artifact_id="other")
    else:
        owned = replace(owned, integrity_ref="")
    requirement = type(requirement).model_validate(raw)
    supply = build_artifact_supply({"node": requirement}, [owned])
    result = resolve_artifact_requirement(
        requirement,
        address="node",
        capabilities=supply.capabilities,
        availability=supply.availability["node"],
        prepared_materializations=supply.materializations,
        backend=shifter_backend_apparatus(),
    )
    assert result.status == ArtifactResolutionStatus.UNRESOLVABLE


def test_editor_assessment_consumes_the_same_private_supply_snapshot(monkeypatch):
    from shared.raes import realizability

    requirement, owned = inventory_fixture()
    monkeypatch.setattr(realizability, "authored_artifact_requirements", lambda scenarios: {"node": requirement})

    def provider(requirements):
        return build_artifact_supply(requirements, [owned])

    assert realizability._artifact_gaps_for_scenario(object(), provider) == ()


def test_artifact_bound_node_does_not_require_an_extra_source_alias():
    from types import SimpleNamespace

    from shared.raes.realizability import _project_image_demands

    requirement, _ = inventory_fixture()
    node = SimpleNamespace(
        address="node",
        resource_type="node",
        payload={
            "spec": {
                "node": {
                    "source": {
                        "name": "private-source-without-alias",
                        "artifact_requirement": requirement.model_dump(mode="json"),
                    }
                }
            }
        },
    )
    assert _project_image_demands(SimpleNamespace(resources={"node": node})) == ()


def test_materialization_binding_cannot_join_a_different_mapping_with_the_same_portable_identity():
    from shared.raes.artifact_inventory import _fenced_binding

    requirement, owned = inventory_fixture()
    shadow = replace(
        owned, materialization=None, image_ref="projects/test-project/global/images/shadow", image_id="999"
    )
    supply = build_artifact_supply({"node": requirement}, [shadow, owned])
    result = resolve_artifact_requirement(
        requirement,
        address="node",
        capabilities=supply.capabilities,
        availability=supply.availability["node"],
        prepared_materializations=supply.materializations,
        backend=shifter_backend_apparatus(),
    )
    binding = _fenced_binding("node", result, [shadow, owned])
    assert binding.image_ref == owned.image_ref and binding.image_id == "555"
