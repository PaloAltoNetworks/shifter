"""Tests for provider-aware range lifecycle behavior in range_ops.py."""

from unittest.mock import patch

import pytest

from range_ops import get_range_instance_ids, run_range_pause, run_range_resume


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
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "vm_runtime_vm",
                "state": rows[0][1],
                "operation_mode": "gdc_vm_runtime",
            },
            {
                "uuid": "pod-instance-uuid-456",
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "scenario_pod",
                "state": rows[1][1],
                "operation_mode": "noop",
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
            )
        ]

        with patch("range_ops.get_db_connection") as mock_get_db_connection:
            conn = mock_get_db_connection.return_value.__enter__.return_value
            cursor = conn.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = rows

            with pytest.raises(ValueError, match="Unsupported range lifecycle target"):
                get_range_instance_ids("req-123")


class TestGcpRangeLifecycle:
    """GCP pause/resume should operate on VM Runtime guests and ignore pod assets."""

    @patch("range_ops.publish_status_update")
    @patch("range_ops.update_range_status")
    @patch("range_ops.pause_ngfw_for_range")
    @patch("range_ops._update_instance_statuses")
    @patch("range_ops.get_range_instance_ids")
    @patch("range_ops.get_range_data_by_request_id")
    @patch("range_ops.gdc_vmruntime_assets.run_power_operation")
    def test_run_range_pause_pauses_gcp_vms_and_ignores_pods(
        self,
        mock_power_operation,
        mock_range_data,
        mock_instances,
        mock_update_instances,
        mock_pause_ngfw,
        mock_update_range,
        mock_publish,
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
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "vm_runtime_vm",
                "state": vm_state,
                "operation_mode": "gdc_vm_runtime",
            },
            {
                "uuid": "pod-instance-uuid-456",
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "scenario_pod",
                "state": {"cloud_provider": "gcp", "asset_type": "scenario_pod"},
                "operation_mode": "noop",
            },
        ]

        run_range_pause(request_id)

        mock_power_operation.assert_called_once_with("stop", vm_state)
        mock_update_instances.assert_called_once_with(request_id, "paused")
        mock_pause_ngfw.assert_called_once_with(request_id, {"range_id": 42, "user_id": 7, "status": "ready"})
        mock_update_range.assert_called_once_with(42, "paused", paused_at="NOW()")
        mock_publish.assert_called_once_with(
            request_id=request_id,
            range_id=42,
            user_id=7,
            new_status="paused",
        )

    @patch("range_ops.publish_status_update")
    @patch("range_ops.update_range_status")
    @patch("range_ops.ensure_ngfw_running")
    @patch("range_ops._update_instance_statuses")
    @patch("range_ops.get_range_instance_ids")
    @patch("range_ops.get_range_data_by_request_id")
    @patch("range_ops.gdc_vmruntime_assets.run_power_operation")
    def test_run_range_resume_resumes_gcp_vms_and_ignores_pods(
        self,
        mock_power_operation,
        mock_range_data,
        mock_instances,
        mock_update_instances,
        mock_ensure_ngfw,
        mock_update_range,
        mock_publish,
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
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "vm_runtime_vm",
                "state": vm_state,
                "operation_mode": "gdc_vm_runtime",
            },
            {
                "uuid": "pod-instance-uuid-456",
                "role": "victim",
                "cloud_provider": "gcp",
                "asset_type": "scenario_pod",
                "state": {"cloud_provider": "gcp", "asset_type": "scenario_pod"},
                "operation_mode": "noop",
            },
        ]

        run_range_resume(request_id)

        mock_ensure_ngfw.assert_called_once_with(request_id)
        mock_power_operation.assert_called_once_with("start", vm_state)
        mock_update_instances.assert_called_once_with(request_id, "ready")
        mock_update_range.assert_called_once_with(42, "ready", ready_at="NOW()")
        mock_publish.assert_called_once_with(
            request_id=request_id,
            range_id=42,
            user_id=7,
            new_status="ready",
        )
