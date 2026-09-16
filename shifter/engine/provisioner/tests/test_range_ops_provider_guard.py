"""Tests for provider-aware range lifecycle behavior in range_ops.py."""

import json
from unittest.mock import patch

import pytest
from shared.operation_results import ResultStep

from range_ops import get_range_instance_ids, run_range_pause, run_range_resume
from range_ops._pause_resume import UnsupportedRangeLifecycleError

_OPERATION_ID = "44444444-4444-4444-4444-444444444444"


def _assert_terminal_failure_reported(
    mock_cursor, *, operation: str, reason_code: str = "cloud_operation_failed"
) -> None:
    """Assert the operation reported a terminal failure to the result inbox.

    ADR-043 phase 4 (#1836): the applier is the authoritative writer, so a failed
    pause/resume must surface as a closed terminal-failure result rather than a
    direct status write. Asserted at the psycopg boundary (ADR-019) rather than
    by patching the append helper. Only the authored reason code travels; the
    free-text diagnostic stays bounded inside the payload.
    """
    appends = [
        call
        for call in mock_cursor.execute.call_args_list
        if "engine_operation_result_inbox" in str(call.args[0]).lower()
    ]
    assert len(appends) == 1, "expected exactly one terminal-failure result append"
    params = appends[0].args[1]
    assert params[2] == "range"
    assert params[3] == operation
    assert params[6] == ResultStep.RANGE_TERMINAL_FAILED
    payload = json.loads(params[9])["payload"]
    assert payload["reason_code"] == reason_code


class TestRangeInstanceClassification:
    """Ensure range lifecycle targets are derived from engine-owned runtime state."""

    def test_get_range_instance_ids_maps_gcp_vm_and_pod_assets(self):
        rows = [
            (
                "vm-instance-uuid-123",
                {
                    "cloud_provider": "gcp",
                    "asset_type": "vm_runtime_vm",
                    "instance_id": "range-42-vm-123",
                    "provider_metadata": {"gcp": {"namespace": "range-42", "vm_name": "range-42-vm-123"}},
                },
                "victim",
                "win-target",
            ),
            (
                "pod-instance-uuid-456",
                {
                    "cloud_provider": "gcp",
                    "asset_type": "scenario_pod",
                    "instance_id": "range-42-pod-456",
                    "provider_metadata": {"gcp": {"namespace": "range-42", "pod_name": "range-42-pod-456"}},
                },
                "victim",
                "lower-fidelity-target",
            ),
        ]

        with patch("range_ops.get_db_connection") as mock_get_db_connection:
            conn = mock_get_db_connection.return_value.__enter__.return_value
            cursor = conn.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = rows

            instances = get_range_instance_ids("req-123")

        assert instances == [
            {
                "uuid": "vm-instance-uuid-123",
                "name": "win-target",
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "vm_runtime_vm",
                "state": rows[0][1],
                "operation_mode": "gdc_vm_runtime",
            },
            {
                "uuid": "pod-instance-uuid-456",
                "name": "lower-fidelity-target",
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "scenario_pod",
                "state": rows[1][1],
                "operation_mode": "gdc_scenario_pod",
            },
        ]

    def test_get_range_instance_ids_rejects_unknown_provider_asset_mix(self):
        rows = [
            (
                "instance-uuid-123",
                {
                    "cloud_provider": "azure",
                    "asset_type": "vm_runtime_vm",
                    "instance_id": "vm-1",
                },
                "victim",
                "victim-1",
            )
        ]

        with patch("range_ops.get_db_connection") as mock_get_db_connection:
            conn = mock_get_db_connection.return_value.__enter__.return_value
            cursor = conn.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = rows

            with pytest.raises(ValueError, match="Unsupported range lifecycle target"):
                get_range_instance_ids("req-123")


class TestGcpRangeLifecycle:
    """A range whose mix is not losslessly pausable (pod-backed) fails closed (#614)."""

    @patch("range_ops.update_range_status")
    @patch("range_ops.pause_ngfw_for_range")
    @patch("range_ops._update_instance_statuses")
    @patch("range_ops.get_range_instance_ids")
    @patch("range_ops.get_range_data_by_request_id")
    def test_run_range_pause_fails_for_gcp_assets(
        self,
        mock_range_data,
        mock_instances,
        mock_update_instances,
        mock_pause_ngfw,
        mock_update_range,
        mock_psycopg_connect,
        monkeypatch,
    ):
        for key, value in {
            "DB_HOST": "test-db",
            "DB_USER": "shifter_app",
            "DB_NAME": "shifter",
            "DB_PASSWORD": "local-dev-password",
            "CLOUD_REGION": "us-east-2",
        }.items():
            monkeypatch.setenv(key, value)
        _connect, _conn, _cursor = mock_psycopg_connect

        request_id = "77777777-7777-4777-8777-777777777777"
        vm_state = {
            "cloud_provider": "gcp",
            "asset_type": "vm_runtime_vm",
            "instance_id": "range-42-vm-123",
            "provider_metadata": {"gcp": {"namespace": "range-42", "vm_name": "range-42-vm-123"}},
        }
        mock_range_data.return_value = {"range_id": 42, "user_id": 7, "status": "ready", "range_backend": "gdc"}
        mock_instances.return_value = [
            {
                "uuid": "vm-instance-uuid-123",
                "name": "",
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "vm_runtime_vm",
                "state": vm_state,
                "operation_mode": "gdc_vm_runtime",
            },
            {
                "uuid": "pod-instance-uuid-456",
                "name": "lower-fidelity-target",
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "scenario_pod",
                "state": {
                    "cloud_provider": "gcp",
                    "asset_type": "scenario_pod",
                    "subnet_name": "mixed",
                    "private_ip": "10.200.0.107",
                    "provider_metadata": {
                        "gcp": {
                            "namespace": "range-42",
                            "pod_name": "range-42-pod-456",
                            "nad_name": "range-42-mixed",
                            "container_image": "docker.io/library/ubuntu:24.04",
                            "ip": "10.200.0.107",
                        }
                    },
                },
                "operation_mode": "gdc_scenario_pod",
            },
        ]

        with pytest.raises(UnsupportedRangeLifecycleError, match="cannot be paused without losing state"):
            run_range_pause(request_id, operation_id=_OPERATION_ID)

        mock_update_instances.assert_not_called()
        mock_pause_ngfw.assert_not_called()
        # ADR-043 phase 4 (#1836): the provisioner no longer writes the range's
        # failed status or enqueues its own event -- it reports a terminal
        # failure result and the applier performs both.
        mock_update_range.assert_not_called()
        _assert_terminal_failure_reported(_cursor, operation="pause", reason_code="unsupported_capability")

    @patch("range_ops.update_range_status")
    @patch("range_ops.ensure_ngfw_running")
    @patch("range_ops._update_instance_statuses")
    @patch("range_ops.get_range_instance_ids")
    @patch("range_ops.get_range_data_by_request_id")
    def test_run_range_resume_fails_for_gcp_assets(
        self,
        mock_range_data,
        mock_instances,
        mock_update_instances,
        mock_ensure_ngfw,
        mock_update_range,
        mock_psycopg_connect,
        monkeypatch,
    ):
        for key, value in {
            "DB_HOST": "test-db",
            "DB_USER": "shifter_app",
            "DB_NAME": "shifter",
            "DB_PASSWORD": "local-dev-password",
            "CLOUD_REGION": "us-east-2",
        }.items():
            monkeypatch.setenv(key, value)
        _connect, _conn, _cursor = mock_psycopg_connect

        request_id = "77777777-7777-4777-8777-777777777777"
        vm_state = {
            "cloud_provider": "gcp",
            "asset_type": "vm_runtime_vm",
            "instance_id": "range-42-vm-123",
            "provider_metadata": {"gcp": {"namespace": "range-42", "vm_name": "range-42-vm-123"}},
        }
        mock_range_data.return_value = {"range_id": 42, "user_id": 7, "status": "paused", "range_backend": "gdc"}
        mock_instances.return_value = [
            {
                "uuid": "vm-instance-uuid-123",
                "name": "",
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "vm_runtime_vm",
                "state": vm_state,
                "operation_mode": "gdc_vm_runtime",
            },
            {
                "uuid": "pod-instance-uuid-456",
                "name": "lower-fidelity-target",
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "scenario_pod",
                "state": {
                    "cloud_provider": "gcp",
                    "asset_type": "scenario_pod",
                    "subnet_name": "mixed",
                    "private_ip": "10.200.0.107",
                    "provider_metadata": {
                        "gcp": {
                            "namespace": "range-42",
                            "pod_name": "range-42-pod-456",
                            "nad_name": "range-42-mixed",
                            "container_image": "docker.io/library/ubuntu:24.04",
                            "ip": "10.200.0.107",
                        }
                    },
                },
                "operation_mode": "gdc_scenario_pod",
            },
        ]

        with pytest.raises(UnsupportedRangeLifecycleError, match="cannot be paused without losing state"):
            run_range_resume(request_id, operation_id=_OPERATION_ID)

        # Capability preflight now runs BEFORE the NGFW cascade, so an unsupported
        # range never starts the shared NGFW (#614).
        mock_ensure_ngfw.assert_not_called()
        mock_update_instances.assert_not_called()
        # ADR-043 phase 4 (#1836): reported, not written directly.
        mock_update_range.assert_not_called()
        _assert_terminal_failure_reported(_cursor, operation="resume", reason_code="unsupported_capability")
