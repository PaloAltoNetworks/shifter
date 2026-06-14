"""Tests for _run_terraform_destroy and run_range_terraform failure handling.

Covers:
- _run_terraform_destroy allows destroying failed ranges (not just destroyed)
- run_range_terraform auto-cleanup passes variables on provision failure
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _install_destroy_fakes(monkeypatch, *, status="ready", variables=None):
    mock_get_data = MagicMock(return_value={"status": status})
    mock_tf_runner = MagicMock()
    mock_build_vars = MagicMock(return_value=variables or {})
    mock_publish = MagicMock()
    mock_mark = MagicMock()
    monkeypatch.setattr("terraform_ops.get_range_data_by_request_id", mock_get_data)
    monkeypatch.setattr("terraform_ops.range_terraform_runner", mock_tf_runner)
    monkeypatch.setattr("terraform_ops._build_range_terraform_variables", mock_build_vars)
    monkeypatch.setattr("terraform_ops.publish_destroyed", mock_publish)
    monkeypatch.setattr("terraform_ops.mark_range_instances_destroyed", mock_mark)
    monkeypatch.setattr("terraform_ops.remove_ngfw_subnets", MagicMock())
    return mock_get_data, mock_tf_runner, mock_build_vars, mock_publish, mock_mark


class TestRunTerraformDestroySkipsOnlyDestroyed:
    """_run_terraform_destroy should only skip 'destroyed' ranges, not 'failed'."""

    def test_skips_destroyed_status(self, monkeypatch):
        """Destroyed ranges should be skipped."""
        from terraform_ops import _run_terraform_destroy

        _mock_get_data, mock_tf_runner, _mock_build_vars, mock_publish, _mock_mark = _install_destroy_fakes(
            monkeypatch, status="destroyed"
        )

        _run_terraform_destroy("req-1", 80, 20, {})

        mock_tf_runner.destroy_range.assert_not_called()
        mock_publish.assert_not_called()

    def test_does_not_skip_failed_status(self, monkeypatch):
        """Failed ranges should NOT be skipped - they may have orphaned resources."""
        from terraform_ops import _run_terraform_destroy

        _mock_get_data, mock_tf_runner, _mock_build_vars, mock_publish, _mock_mark = _install_destroy_fakes(
            monkeypatch, status="failed"
        )

        _run_terraform_destroy("req-1", 80, 20, {})

        mock_tf_runner.destroy_range.assert_called_once()
        mock_publish.assert_called_once()

    def test_proceeds_for_ready_status(self, monkeypatch):
        """Ready (active) ranges should proceed with destroy."""
        from terraform_ops import _run_terraform_destroy

        _mock_get_data, mock_tf_runner, _mock_build_vars, _mock_publish, _mock_mark = _install_destroy_fakes(
            monkeypatch, status="ready"
        )

        _run_terraform_destroy("req-1", 80, 20, {})

        mock_tf_runner.destroy_range.assert_called_once()

    def test_destroy_passes_variables_to_destroy_range(self, monkeypatch):
        """_run_terraform_destroy must pass variables to destroy_range."""
        from terraform_ops import _run_terraform_destroy

        fake_vars = {"range_id": 80, "user_id": 20, "request_uuid": "req-1", "vpc_id": "vpc-123"}
        _mock_get_data, mock_tf_runner, _mock_build_vars, _mock_publish, _mock_mark = _install_destroy_fakes(
            monkeypatch, status="ready", variables=fake_vars
        )
        range_spec = {"subnets": []}

        _run_terraform_destroy("req-1", 80, 20, range_spec)

        mock_tf_runner.destroy_range.assert_called_once_with("req-1", variables=fake_vars)


class TestAutoCleanupPassesVariables:
    """run_range_terraform auto-cleanup should pass tf variables on provision failure."""

    def test_cleanup_passes_variables_to_destroy(self, monkeypatch):
        """Auto-cleanup should rebuild variables and pass them to destroy_range."""
        from terraform_ops import run_range_terraform

        mock_get_data = MagicMock(
            return_value={
                "range_id": 80,
                "user_id": 20,
                "spec": {"ngfw": False, "subnets": []},
            }
        )
        mock_tf_runner = MagicMock()
        fake_vars = {"range_id": 80, "user_id": 20, "request_uuid": "req-1"}
        mock_build_vars = MagicMock(return_value=fake_vars)
        monkeypatch.setattr("terraform_ops.get_range_data_by_request_id", mock_get_data)
        monkeypatch.setattr(
            "terraform_ops._run_terraform_provision", MagicMock(side_effect=RuntimeError("NGFW config failed"))
        )
        monkeypatch.setattr("terraform_ops.range_terraform_runner", mock_tf_runner)
        monkeypatch.setattr("terraform_ops._build_range_terraform_variables", mock_build_vars)
        monkeypatch.setattr("terraform_ops.publish_failed", MagicMock())

        with pytest.raises(RuntimeError, match="NGFW config failed"):
            run_range_terraform("up", "req-1")

        mock_build_vars.assert_called_once_with("req-1", 80, 20, {"ngfw": False, "subnets": []})
        mock_tf_runner.destroy_range.assert_called_once_with("req-1", variables=fake_vars)

    def test_cleanup_failure_logged_not_swallowed(self, monkeypatch, caplog):
        """When auto-cleanup fails, error should be logged (not just warned)."""
        import logging

        from terraform_ops import run_range_terraform

        monkeypatch.setattr(
            "terraform_ops.get_range_data_by_request_id",
            MagicMock(
                return_value={
                    "range_id": 80,
                    "user_id": 20,
                    "spec": {"ngfw": False, "subnets": []},
                }
            ),
        )
        monkeypatch.setattr(
            "terraform_ops._run_terraform_provision",
            MagicMock(side_effect=RuntimeError("provision failed")),
        )
        monkeypatch.setattr("terraform_ops.range_terraform_runner", MagicMock())
        monkeypatch.setattr(
            "terraform_ops._build_range_terraform_variables",
            MagicMock(side_effect=ValueError("NGFW missing")),
        )
        monkeypatch.setattr("terraform_ops.publish_failed", MagicMock())

        with pytest.raises(RuntimeError, match="provision failed"), caplog.at_level(logging.ERROR):
            run_range_terraform("up", "req-1")

        assert any("Auto-cleanup FAILED" in record.message for record in caplog.records)
        assert any("Orphaned cloud resources" in record.message for record in caplog.records)

    def test_no_cleanup_on_destroy_failure(self, monkeypatch):
        """Auto-cleanup should only run for 'up' operations, not 'destroy'."""
        from terraform_ops import run_range_terraform

        mock_get_data = MagicMock(
            return_value={
                "range_id": 80,
                "user_id": 20,
                "spec": {},
            }
        )
        mock_tf_runner = MagicMock()
        monkeypatch.setattr("terraform_ops.get_range_data_by_request_id", mock_get_data)
        monkeypatch.setattr("terraform_ops.range_terraform_runner", mock_tf_runner)
        mock_destroy = MagicMock()
        monkeypatch.setattr("terraform_ops._run_terraform_destroy", mock_destroy)
        monkeypatch.setattr("terraform_ops.publish_failed", MagicMock())
        mock_destroy.side_effect = RuntimeError("destroy failed")

        with pytest.raises(RuntimeError, match="destroy failed"):
            run_range_terraform("destroy", "req-1")

        # destroy_range on the terraform_runner should NOT be called for cleanup
        mock_tf_runner.destroy_range.assert_not_called()
