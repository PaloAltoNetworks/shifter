"""Contract tests for the platform-owned GCP VM range-cell boundary."""

from __future__ import annotations

from copy import deepcopy

import pytest

from shared.range_cells import (
    RangeCellContractError,
    build_gcp_vm_range_cell_request,
    build_gcp_vm_range_cell_result,
    build_scenario_artifact,
    validate_gcp_vm_range_cell_request,
    validate_gcp_vm_range_cell_result,
)


def _envelope() -> dict[str, object]:
    return {
        "spec_schema": "range_spec",
        "spec_version": "1",
        "payload": {
            "scenario_id": "scenario-a",
            "user_id": 7,
            "subnets": [
                {
                    "name": "attack",
                    "uuid": "subnet-a",
                    "instances": [
                        {
                            "name": "attacker",
                            "uuid": "instance-a",
                            "role": "attacker",
                            "os_type": "kali",
                        }
                    ],
                }
            ],
            "participant_access": [{"target_ref": "instance-a", "channel": "ssh"}],
        },
    }


def _request() -> dict[str, object]:
    return build_gcp_vm_range_cell_request(
        request_id="request-a",
        range_id=42,
        scenario_artifact=build_scenario_artifact(_envelope()),
        network_bindings=[{"subnet_ref": "subnet-a", "cidr": "10.50.2.0/28"}],
        access_declarations=[{"target_ref": "instance-a", "channel": "ssh"}],
    )


def _result() -> dict[str, object]:
    return build_gcp_vm_range_cell_result(
        _request(),
        cell_id="gcp:test-project:us-central1:42",
        members=[
            {
                "authored_ref": "instance-a",
                "resource_id": "projects/test/zones/test/instances/range-42-a",
                "subnet_ref": "subnet-a",
                "lifecycle_state": "ready",
            }
        ],
        access=[
            {
                "target_ref": "instance-a",
                "channel": "ssh",
                "address": "10.50.2.3",
                "port": 22,
                "credential_ref": "projects/test/secrets/range-42-a-ssh",
            }
        ],
    )


def test_scenario_artifact_digest_detects_payload_tampering():
    artifact = build_scenario_artifact(_envelope())
    tampered = deepcopy(artifact)
    tampered["payload"]["scenario_id"] = "scenario-b"  # type: ignore[index]
    request = build_gcp_vm_range_cell_request(
        request_id="request-a",
        range_id=42,
        scenario_artifact=artifact,
        network_bindings=[{"subnet_ref": "subnet-a", "cidr": "10.50.2.0/28"}],
    )
    request["scenario_artifact"] = tampered

    with pytest.raises(RangeCellContractError, match="digest mismatch"):
        validate_gcp_vm_range_cell_request(request)


def test_scenario_artifact_builder_requires_the_canonical_range_spec():
    malformed = _envelope()
    del malformed["payload"]["user_id"]  # type: ignore[index]

    with pytest.raises(RangeCellContractError, match="canonical validation"):
        build_scenario_artifact(malformed)


def test_scenario_artifact_builder_does_not_digest_ignored_extension_fields():
    envelope = _envelope()
    envelope["payload"]["provider_request"] = {"machine_type": "unapproved"}  # type: ignore[index]

    artifact = build_scenario_artifact(envelope)

    assert "provider_request" not in artifact["payload"]


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("contract_version",), "2", "contract_version"),
        (("admission", "backend"), "gdc", "backend"),
        (("unexpected",), True, "unexpected field"),
    ],
)
def test_request_rejects_unknown_version_backend_and_fields(path, value, message):
    request = deepcopy(_request())
    target = request
    for key in path[:-1]:
        target = target[key]  # type: ignore[index,assignment]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(RangeCellContractError, match=message):
        validate_gcp_vm_range_cell_request(request)


def test_request_rejects_duplicate_network_membership():
    artifact = build_scenario_artifact(_envelope())
    with pytest.raises(RangeCellContractError, match="duplicate subnet_ref"):
        build_gcp_vm_range_cell_request(
            request_id="request-a",
            range_id=42,
            scenario_artifact=artifact,
            network_bindings=[
                {"subnet_ref": "subnet-a", "cidr": "10.50.2.0/28"},
                {"subnet_ref": "subnet-a", "cidr": "10.50.3.0/28"},
            ],
        )


@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "10.0.0.0/15"])
def test_request_rejects_oversized_range_cell_networks(cidr):
    artifact = build_scenario_artifact(_envelope())

    with pytest.raises(RangeCellContractError, match="larger than /16"):
        build_gcp_vm_range_cell_request(
            request_id="request-a",
            range_id=42,
            scenario_artifact=artifact,
            network_bindings=[{"subnet_ref": "subnet-a", "cidr": cidr}],
        )


def test_request_rejects_overlapping_range_cell_networks():
    artifact = build_scenario_artifact(_envelope())

    with pytest.raises(RangeCellContractError, match="overlaps"):
        build_gcp_vm_range_cell_request(
            request_id="request-a",
            range_id=42,
            scenario_artifact=artifact,
            network_bindings=[
                {"subnet_ref": "subnet-a", "cidr": "10.50.2.0/27"},
                {"subnet_ref": "subnet-b", "cidr": "10.50.2.16/28"},
            ],
        )


def test_request_rejects_duplicate_participant_access_declarations():
    declaration = {"target_ref": "instance-a", "channel": "ssh"}
    artifact = build_scenario_artifact(_envelope())

    with pytest.raises(RangeCellContractError, match="duplicate access declaration"):
        build_gcp_vm_range_cell_request(
            request_id="request-a",
            range_id=42,
            scenario_artifact=artifact,
            network_bindings=[{"subnet_ref": "subnet-a", "cidr": "10.50.2.0/28"}],
            access_declarations=[declaration, declaration],
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda result: result["members"].append(deepcopy(result["members"][0])), "duplicate authored_ref"),
        (lambda result: result["members"][0].update(subnet_ref="foreign-subnet"), "foreign subnet_ref"),
        (lambda result: result["access"][0].update(target_ref="missing-instance"), "dangling target_ref"),
        (lambda result: result["access"][0].update(password="secret-value"), "unexpected field"),
    ],
)
def test_result_rejects_invalid_membership_access_and_secret_values(mutation, message):
    result = deepcopy(_result())
    mutation(result)

    with pytest.raises(RangeCellContractError, match=message):
        validate_gcp_vm_range_cell_result(result)


def test_result_contains_only_outer_lifecycle_membership_and_logical_access():
    result = validate_gcp_vm_range_cell_result(_result())

    assert set(result) == {"contract", "contract_version", "capability", "operation", "cell", "members", "access"}
    assert set(result["members"][0]) == {"authored_ref", "resource_id", "subnet_ref", "lifecycle_state"}
    assert set(result["access"][0]) == {"target_ref", "channel", "address", "port", "credential_ref"}
    assert "role" not in repr(result)
    assert "os_type" not in repr(result)
