"""Tests for provider-aware range lifecycle behavior in range_ops.py."""

from unittest.mock import patch

import pytest

from events import EVENT_TYPE_STATUS_UPDATED
from range_ops import get_range_instance_ids, run_range_pause, run_range_resume


def _assert_status_outbox_event(mock_update_range, *, expected_status: str) -> None:
    """Assert update_range_status was passed a real (non-None) status outbox event.

    ``outbox_event=ANY`` would also match ``None`` — which would silently break
    the atomic status+event commit #476 requires (``update_range_status`` skips
    ``enqueue_event_outbox`` when ``outbox_event is None``). Inspect the value
    directly so the regression is actually guarded.
    """
    event = mock_update_range.call_args.kwargs["outbox_event"]
    assert event is not None
    assert event["event_type"] == EVENT_TYPE_STATUS_UPDATED
    assert event["new_status"] == expected_status


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
    """GCP pause/resume should fail closed until parity-safe lifecycle exists."""

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
    ):
        request_id = "req-123"
        vm_state = {
            "cloud_provider": "gcp",
            "asset_type": "vm_runtime_vm",
            "instance_id": "range-42-vm-123",
            "provider_metadata": {"gcp": {"namespace": "range-42", "vm_name": "range-42-vm-123"}},
        }
        mock_range_data.return_value = {"range_id": 42, "user_id": 7, "status": "ready"}
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

        with pytest.raises(RuntimeError, match="Failed to pause 2/2 instances"):
            run_range_pause(request_id)

        mock_update_instances.assert_not_called()
        mock_pause_ngfw.assert_not_called()
        # Phase 1: status + outbox_event commit atomically; no separate publish call
        mock_update_range.assert_called_once()
        assert mock_update_range.call_args.args == (42, "failed")
        assert mock_update_range.call_args.kwargs["error_message"] == "Failed to pause 2/2 instances"
        _assert_status_outbox_event(mock_update_range, expected_status="failed")

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
    ):
        request_id = "req-123"
        vm_state = {
            "cloud_provider": "gcp",
            "asset_type": "vm_runtime_vm",
            "instance_id": "range-42-vm-123",
            "provider_metadata": {"gcp": {"namespace": "range-42", "vm_name": "range-42-vm-123"}},
        }
        mock_range_data.return_value = {"range_id": 42, "user_id": 7, "status": "paused"}
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

        with pytest.raises(RuntimeError, match="Failed to resume 2/2 instances"):
            run_range_resume(request_id)

        mock_ensure_ngfw.assert_called_once_with(request_id)
        mock_update_instances.assert_not_called()
        # Phase 1: status + outbox_event commit atomically; no separate publish call
        mock_update_range.assert_called_once()
        assert mock_update_range.call_args.args == (42, "failed")
        assert mock_update_range.call_args.kwargs["error_message"] == "Failed to resume 2/2 instances"
        _assert_status_outbox_event(mock_update_range, expected_status="failed")
