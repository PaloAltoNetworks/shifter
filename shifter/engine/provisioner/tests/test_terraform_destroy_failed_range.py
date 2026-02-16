"""Tests for _run_terraform_destroy and run_range_terraform failure handling.

Covers:
- _run_terraform_destroy allows destroying failed ranges (not just destroyed)
- run_range_terraform auto-cleanup passes variables on provision failure
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestRunTerraformDestroySkipsOnlyDestroyed:
    """_run_terraform_destroy should only skip 'destroyed' ranges, not 'failed'."""

    @patch("main.publish_destroyed")
    @patch("main.range_terraform_runner")
    @patch("main.get_range_data_by_request_id")
    def test_skips_destroyed_status(self, mock_get_data, mock_tf_runner, mock_publish):
        """Destroyed ranges should be skipped."""
        from main import _run_terraform_destroy

        mock_get_data.return_value = {"status": "destroyed"}

        _run_terraform_destroy("req-1", 80, 20, {})

        mock_tf_runner.destroy_range.assert_not_called()
        mock_publish.assert_not_called()

    @patch("main.mark_range_instances_destroyed")
    @patch("main.publish_destroyed")
    @patch("main.range_terraform_runner")
    @patch("main.remove_ngfw_subnets")
    @patch("main.get_range_data_by_request_id")
    def test_does_not_skip_failed_status(
        self, mock_get_data, mock_remove_ngfw, mock_tf_runner, mock_publish, mock_mark
    ):
        """Failed ranges should NOT be skipped - they may have orphaned resources."""
        from main import _run_terraform_destroy

        mock_get_data.return_value = {"status": "failed"}
        mock_tf_runner.RANGE_MODULE_PATH = Path("/fake")

        _run_terraform_destroy("req-1", 80, 20, {})

        mock_tf_runner.destroy_range.assert_called_once()
        mock_publish.assert_called_once()

    @patch("main.mark_range_instances_destroyed")
    @patch("main.publish_destroyed")
    @patch("main.range_terraform_runner")
    @patch("main.remove_ngfw_subnets")
    @patch("main.get_range_data_by_request_id")
    def test_proceeds_for_ready_status(self, mock_get_data, mock_remove_ngfw, mock_tf_runner, mock_publish, mock_mark):
        """Ready (active) ranges should proceed with destroy."""
        from main import _run_terraform_destroy

        mock_get_data.return_value = {"status": "ready"}
        mock_tf_runner.RANGE_MODULE_PATH = Path("/fake")

        _run_terraform_destroy("req-1", 80, 20, {})

        mock_tf_runner.destroy_range.assert_called_once()


class TestAutoCleanupPassesVariables:
    """run_range_terraform auto-cleanup should pass tf variables on provision failure."""

    @patch("main.publish_failed")
    @patch("main._build_range_terraform_variables")
    @patch("main.range_terraform_runner")
    @patch("main._run_terraform_provision", side_effect=RuntimeError("NGFW config failed"))
    @patch("main.get_range_data_by_request_id")
    def test_cleanup_passes_variables_to_destroy(
        self, mock_get_data, mock_provision, mock_tf_runner, mock_build_vars, mock_publish
    ):
        """Auto-cleanup should rebuild variables and pass them to destroy_range."""
        from main import run_range_terraform

        mock_get_data.return_value = {
            "range_id": 80,
            "user_id": 20,
            "spec": {"ngfw": False, "subnets": []},
        }
        mock_tf_runner.RANGE_MODULE_PATH = Path("/fake")
        fake_vars = {"range_id": 80, "user_id": 20, "request_uuid": "req-1"}
        mock_build_vars.return_value = fake_vars

        with pytest.raises(RuntimeError, match="NGFW config failed"):
            run_range_terraform("up", "req-1")

        mock_build_vars.assert_called_once_with("req-1", 80, 20, {"ngfw": False, "subnets": []})
        mock_tf_runner.destroy_range.assert_called_once_with(
            "req-1", mock_tf_runner.RANGE_MODULE_PATH, variables=fake_vars
        )

    @patch("main.publish_failed")
    @patch("main._build_range_terraform_variables", side_effect=ValueError("NGFW missing"))
    @patch("main.range_terraform_runner")
    @patch("main._run_terraform_provision", side_effect=RuntimeError("provision failed"))
    @patch("main.get_range_data_by_request_id")
    def test_cleanup_failure_logged_not_swallowed(
        self, mock_get_data, mock_provision, mock_tf_runner, mock_build_vars, mock_publish, caplog
    ):
        """When auto-cleanup fails, error should be logged (not just warned)."""
        import logging

        from main import run_range_terraform

        mock_get_data.return_value = {
            "range_id": 80,
            "user_id": 20,
            "spec": {"ngfw": False, "subnets": []},
        }

        with pytest.raises(RuntimeError, match="provision failed"), caplog.at_level(logging.ERROR):
            run_range_terraform("up", "req-1")

        assert any("Auto-cleanup FAILED" in record.message for record in caplog.records)
        assert any("Orphaned AWS resources" in record.message for record in caplog.records)

    @patch("main.publish_failed")
    @patch("main.range_terraform_runner")
    @patch("main._run_terraform_destroy")
    @patch("main.get_range_data_by_request_id")
    def test_no_cleanup_on_destroy_failure(self, mock_get_data, mock_destroy, mock_tf_runner, mock_publish):
        """Auto-cleanup should only run for 'up' operations, not 'destroy'."""
        from main import run_range_terraform

        mock_get_data.return_value = {
            "range_id": 80,
            "user_id": 20,
            "spec": {},
        }
        mock_destroy.side_effect = RuntimeError("destroy failed")

        with pytest.raises(RuntimeError, match="destroy failed"):
            run_range_terraform("destroy", "req-1")

        # destroy_range on the terraform_runner should NOT be called for cleanup
        mock_tf_runner.destroy_range.assert_not_called()
