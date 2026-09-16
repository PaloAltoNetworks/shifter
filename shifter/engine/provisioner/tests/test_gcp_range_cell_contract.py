"""Cross-boundary tests for scenario artifacts entering GCP VM range cells."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from shared.range_cells import (
    RangeCellContractError,
    build_gcp_vm_range_cell_request,
    build_scenario_artifact,
    validate_scenario_artifact,
)

from range_terraform_runner import apply_range
from terraform_vars import RangeVariableContext, build_range_variables


def _envelope(payload: dict[str, object]) -> dict[str, object]:
    return {"spec_schema": "range_spec", "spec_version": "1", "payload": payload}


def _contract_request() -> dict[str, object]:
    payload = {
        "scenario_id": "scenario-a",
        "user_id": 7,
        "subnets": [
            {
                "name": "attack",
                "uuid": "subnet-a",
                "instances": [
                    {
                        "name": "attacker",
                        "uuid": "attacker-a",
                        "role": "attacker",
                        "os_type": "kali",
                    }
                ],
            }
        ],
        "participant_access": [{"target_ref": "attacker-a", "channel": "ssh"}],
    }
    return build_gcp_vm_range_cell_request(
        request_id="request-a",
        range_id=42,
        scenario_artifact=build_scenario_artifact(_envelope(payload)),
        network_bindings=[{"subnet_ref": "subnet-a", "cidr": "10.50.2.0/28"}],
        access_declarations=payload["participant_access"],
    )


@pytest.mark.parametrize(
    "scenario_payload",
    [
        {
            "scenario_id": "native-guests",
            "user_id": 7,
            "subnets": [
                {
                    "name": "attack",
                    "uuid": "subnet-a",
                    "instances": [
                        {
                            "name": "attacker",
                            "uuid": "attacker-a",
                            "role": "attacker",
                            "os_type": "kali",
                        }
                    ],
                }
            ],
            "participant_access": [{"target_ref": "attacker-a", "channel": "ssh"}],
        },
        {
            "scenario_id": "nested-runtime",
            "user_id": 7,
            "subnets": [
                {
                    "name": "control",
                    "uuid": "subnet-b",
                    "instances": [
                        {
                            "name": "orchestration-host",
                            "uuid": "host-b",
                            "role": "attacker",
                            "os_type": "kali",
                            "ami_key": "polaris-vm",
                        }
                    ],
                },
                {
                    "name": "targets",
                    "uuid": "subnet-c",
                    "instances": [
                        {
                            "name": "domain-controller",
                            "uuid": "dc-c",
                            "role": "dc",
                            "os_type": "windows",
                        }
                    ],
                },
            ],
            "participant_access": [
                {"target_ref": "host-b", "channel": "ssh"},
                {"target_ref": "host-b", "channel": "rdp"},
            ],
        },
    ],
)
def test_different_scenario_compositions_cross_the_same_outer_contract(scenario_payload):
    artifact = build_scenario_artifact(_envelope(scenario_payload))
    runtime_spec = deepcopy(scenario_payload)
    for index, subnet in enumerate(runtime_spec["subnets"]):
        subnet["cidr"] = f"10.50.{index + 2}.0/28"

    with patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
        request = build_range_variables(
            "request-a",
            42,
            7,
            runtime_spec,
            RangeVariableContext(scenario_artifact=artifact),
        )

    assert set(request) == {
        "contract",
        "contract_version",
        "capability",
        "operation",
        "admission",
        "scenario_artifact",
        "network_bindings",
        "access_declarations",
        "remote_access",
    }
    assert request["scenario_artifact"]["payload"]["scenario_id"] == scenario_payload["scenario_id"]
    assert request["access_declarations"] == scenario_payload["participant_access"]
    assert all("cidr" not in subnet for subnet in request["scenario_artifact"]["payload"]["subnets"])
    assert [binding["subnet_ref"] for binding in request["network_bindings"]] == [
        subnet["uuid"] for subnet in scenario_payload["subnets"]
    ]


def test_gce_variable_builder_rejects_missing_scenario_artifact():
    runtime_spec = {"subnets": [{"name": "attack", "uuid": "subnet-a", "cidr": "10.50.2.0/28"}]}

    with (
        patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True),
        pytest.raises(RuntimeError, match="digest-bound scenario artifact"),
    ):
        build_range_variables("request-a", 42, 7, runtime_spec)


@pytest.mark.parametrize(
    "environment",
    [
        {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"},
        {"CLOUD_PROVIDER": "aws"},
    ],
)
def test_contract_request_cannot_fall_back_to_an_unsafe_backend(monkeypatch, environment):
    gdc_network_apply = MagicMock()
    terraform_apply = MagicMock()
    request = _contract_request()
    monkeypatch.setattr("range_terraform_runner.gdc_range_networks.apply_range_networks", gdc_network_apply)
    monkeypatch.setattr("range_terraform_runner.terraform_base.apply", terraform_apply)

    with (
        patch.dict("os.environ", environment, clear=True),
        pytest.raises(RuntimeError, match="GCP/GCE VM range-cell backend"),
    ):
        apply_range("request-a", request)

    gdc_network_apply.assert_not_called()
    terraform_apply.assert_not_called()


def test_contract_request_routes_to_gce_without_reclassification():
    request = _contract_request()
    gce_apply = MagicMock(return_value={"subnets": {}, "instances": []})

    with patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
        result = apply_range("request-a", request, gce_apply_range_cell=gce_apply)

    assert result == {"subnets": {}, "instances": []}
    gce_apply.assert_called_once_with("request-a", request)


def test_invalid_persisted_artifact_fails_before_ngfw_or_provider_work(monkeypatch):
    from terraform_ops import run_range_terraform

    malformed_envelope = {
        "spec_schema": "range_spec",
        "spec_version": "2",
        "payload": {"ngfw": True, "subnets": []},
        "digest": "sha256:" + "0" * 64,
    }
    monkeypatch.setattr(
        "terraform_ops.get_range_data_by_request_id",
        MagicMock(
            return_value={
                "range_id": 42,
                "user_id": 7,
                "spec": malformed_envelope["payload"],
                "spec_envelope": malformed_envelope,
                "range_backend": "gce",
                "instantiation_purpose": "live_fire",
            }
        ),
    )
    ngfw_ready = MagicMock()
    dispatch = MagicMock()
    cleanup = MagicMock()
    update_status = MagicMock()
    monkeypatch.setattr("terraform_ops._ensure_ngfw_ready_for_provisioning", ngfw_ready)
    monkeypatch.setattr("terraform_ops._dispatch_terraform_operation", dispatch)
    monkeypatch.setattr("terraform_ops._attempt_terraform_auto_cleanup", cleanup)
    monkeypatch.setattr("terraform_ops.update_range_status", update_status)

    with (
        patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True),
        pytest.raises(RangeCellContractError, match="Unsupported spec_version"),
    ):
        run_range_terraform("up", "request-a")

    ngfw_ready.assert_not_called()
    dispatch.assert_not_called()
    cleanup.assert_not_called()
    update_status.assert_called_once_with(
        range_id=42,
        status="failed",
        error_message="Range-cell contract validation failed",
    )


def test_valid_persisted_artifact_is_bound_before_operation_dispatch(monkeypatch):
    from terraform_ops import run_range_terraform

    artifact = build_scenario_artifact(_envelope({"scenario_id": "scenario-a", "user_id": 7, "subnets": []}))
    monkeypatch.setattr(
        "terraform_ops.get_range_data_by_request_id",
        MagicMock(
            return_value={
                "range_id": 42,
                "user_id": 7,
                "spec": artifact["payload"],
                "spec_envelope": artifact,
                "range_backend": "gce",
                "instantiation_purpose": "live_fire",
            }
        ),
    )
    dispatch = MagicMock()
    monkeypatch.setattr("terraform_ops._dispatch_terraform_operation", dispatch)

    with patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
        run_range_terraform("up", "request-a")

    dispatched_operation = dispatch.call_args.args[1]
    assert validate_scenario_artifact(dispatched_operation.scenario_artifact) == artifact


def test_reloaded_gce_range_can_destroy_without_scenario_cidrs(monkeypatch):
    """A later worker may destroy from membership even if no CIDRs are rehydrated."""
    from terraform_ops import run_range_terraform

    artifact = build_scenario_artifact(_envelope(_contract_request()["scenario_artifact"]["payload"]))
    range_data = {
        "range_id": 42,
        "user_id": 7,
        "status": "ready",
        "spec": deepcopy(artifact["payload"]),
        "spec_envelope": artifact,
        "range_backend": "gce",
        "instantiation_purpose": "live_fire",
    }
    destroy = MagicMock()
    monkeypatch.setattr("terraform_ops.get_range_data_by_request_id", MagicMock(return_value=range_data))
    monkeypatch.setattr("components.network.read_range_subnets", MagicMock(return_value=()))
    monkeypatch.setattr("terraform_ops.range_terraform_runner.destroy_range", destroy)
    monkeypatch.setattr("terraform_ops.range_terraform_runner.cleanup_range_state", MagicMock())
    monkeypatch.setattr("terraform_ops._remove_ngfw_attachments_for_destroy", MagicMock())
    monkeypatch.setattr("terraform_ops._post_destroy_cleanup", MagicMock())
    monkeypatch.setattr("terraform_ops._maybe_pause_user_ngfw", MagicMock())
    monkeypatch.setattr("terraform_ops.update_range_status", MagicMock())

    with patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
        run_range_terraform("destroy", "request-a")

    destroy_request = destroy.call_args.kwargs["variables"]
    assert destroy_request["network_bindings"] == []
    assert destroy_request["scenario_artifact"] == artifact


def test_cidr_reservation_does_not_rewrite_authored_scenario_content(monkeypatch):
    """Reservation realizes CIDRs for the operation without touching authored intent.

    Previously this held only for the GCE backend, via a ``persist_to_scenario``
    flag; after #1838 authored intent is never rewritten for any backend, so the
    realized spec must be a separate object from the one passed in.
    """
    from config import RangeNetworkConfig
    from terraform_ops import _reserve_range_subnet_cidrs

    range_spec = {"scenario_id": "scenario-a", "subnets": [{"name": "attack", "uuid": "subnet-a"}]}
    monkeypatch.setattr(
        "range_subnet_allocation.load_range_network_config",
        MagicMock(return_value=RangeNetworkConfig("range-vpc", "10.50.0.0/16", "us-central1")),
    )
    monkeypatch.setattr("components.network.reserve_range_subnets", MagicMock(return_value=("10.50.2.0/28",)))

    realized = _reserve_range_subnet_cidrs(
        "request-a",
        range_spec,
        operation_id="11111111-1111-4111-8111-111111111111",
    )

    assert realized["subnets"][0]["cidr"] == "10.50.2.0/28"
    # The authored spec the operation was launched with is left as it was found.
    assert "cidr" not in range_spec["subnets"][0]
