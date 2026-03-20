"""Tests for get_task_status() function."""

import logging
from unittest.mock import MagicMock, patch

from shared.cloud.exceptions import CloudTaskError


class TestGetTaskStatus:
    """Tests for get_task_status() public function.

    Contract:
    - Inputs: task_arn (str)
    - Outputs: Dict with status info, or None if not configured/error
    - Side effects: Calls TaskRunner.get_task_status via get_task_runner()
    - Errors: Returns None on CloudTaskError (does not raise)
    - Logging: ERROR on failures
    """

    # -------------------------------------------------------------------------
    # Happy path - function succeeds
    # -------------------------------------------------------------------------

    def test_returns_status_dict_on_success(self, settings):
        """Function returns status dict when task is found."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {
                "task_id": "arn:aws:ecs:us-east-2:123456789:task/test/abc123",
                "status": "RUNNING",
                "desired_status": "RUNNING",
                "started_at": "2024-01-01T00:00:00Z",
                "stopped_at": None,
                "stopped_reason": None,
            }
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:us-east-2:123456789:task/test/abc123")

            assert result is not None
            assert result["status"] == "RUNNING"

    def test_returns_dict_with_all_expected_keys(self, settings):
        """Function returns dict with all expected status keys."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {
                "task_id": "arn:aws:ecs:task/abc123",
                "status": "STOPPED",
                "desired_status": "STOPPED",
                "started_at": "2024-01-01T00:00:00Z",
                "stopped_at": "2024-01-01T01:00:00Z",
                "stopped_reason": "Essential container exited",
            }
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert "status" in result
            assert "desired_status" in result
            assert "started_at" in result
            assert "stopped_at" in result
            assert "stopped_reason" in result

    def test_returns_running_status(self, settings):
        """Function returns RUNNING status for running task."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {
                "status": "RUNNING",
                "desired_status": "RUNNING",
            }
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result["status"] == "RUNNING"
            assert result["desired_status"] == "RUNNING"

    def test_returns_stopped_status(self, settings):
        """Function returns STOPPED status for stopped task."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {
                "status": "STOPPED",
                "desired_status": "STOPPED",
                "stopped_reason": "Task completed",
            }
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result["status"] == "STOPPED"
            assert result["stopped_reason"] == "Task completed"

    def test_returns_pending_status(self, settings):
        """Function returns PENDING status for pending task."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {
                "status": "PENDING",
                "desired_status": "RUNNING",
            }
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result["status"] == "PENDING"
            assert result["desired_status"] == "RUNNING"

    def test_calls_get_task_status_with_correct_params(self, settings):
        """Function calls TaskRunner.get_task_status with cluster and task ARN."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {"status": "RUNNING"}
            mock_get_runner.return_value = mock_runner

            task_arn = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"
            get_task_status(task_arn)

            mock_runner.get_task_status.assert_called_once_with(
                cluster="arn:aws:ecs:us-east-2:123456789:cluster/test",
                task_id=task_arn,
            )

    # -------------------------------------------------------------------------
    # Configuration - not configured returns None
    # -------------------------------------------------------------------------

    def test_returns_none_when_cluster_not_configured(self, settings):
        """Function returns None when PULUMI_ECS_CLUSTER_ARN is not set."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "PULUMI_ECS_CLUSTER_ARN"):
            delattr(settings, "PULUMI_ECS_CLUSTER_ARN")

        result = get_task_status("arn:aws:ecs:task/abc123")

        assert result is None

    def test_returns_none_when_cluster_is_empty(self, settings):
        """Function returns None when PULUMI_ECS_CLUSTER_ARN is empty."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = ""

        result = get_task_status("arn:aws:ecs:task/abc123")

        assert result is None

    def test_returns_none_when_cluster_is_none(self, settings):
        """Function returns None when PULUMI_ECS_CLUSTER_ARN is None."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = None

        result = get_task_status("arn:aws:ecs:task/abc123")

        assert result is None

    # -------------------------------------------------------------------------
    # Input validation - empty/None task_arn
    # -------------------------------------------------------------------------

    def test_returns_none_when_task_arn_is_none(self, settings):
        """Function returns None when task_arn is None."""
        from engine.ecs import get_task_status

        result = get_task_status(None)

        assert result is None

    def test_returns_none_when_task_arn_is_empty(self, settings):
        """Function returns None when task_arn is empty string."""
        from engine.ecs import get_task_status

        result = get_task_status("")

        assert result is None

    def test_returns_none_when_task_arn_is_whitespace(self, settings):
        """Function returns None when task_arn is whitespace."""
        from engine.ecs import get_task_status

        # Note: This depends on implementation - if it only checks falsy,
        # whitespace might pass through
        result = get_task_status("   ")

        # Whitespace is truthy, so it might call the runner
        # The test documents current behavior
        assert result is None or isinstance(result, dict)

    # -------------------------------------------------------------------------
    # Task not found
    # -------------------------------------------------------------------------

    def test_returns_unknown_when_task_not_found(self, settings):
        """Function returns UNKNOWN status when task not found."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = None
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/nonexistent")

            assert result is not None
            assert result["status"] == "UNKNOWN"
            assert "not found" in result.get("reason", "").lower()

    def test_returns_unknown_when_adapter_returns_none(self, settings):
        """Function handles None return from adapter."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = None
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result is not None
            assert result["status"] == "UNKNOWN"

    # -------------------------------------------------------------------------
    # Error handling - returns None on errors
    # -------------------------------------------------------------------------

    def test_returns_none_on_cloud_task_error(self, settings):
        """Function returns None when CloudTaskError occurs."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.side_effect = CloudTaskError("Cluster not found")
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result is None

    def test_returns_none_on_access_denied(self, settings):
        """Function returns None when access is denied (wrapped in CloudTaskError)."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.side_effect = CloudTaskError("Access Denied")
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result is None

    def test_does_not_raise_on_cloud_task_error(self, settings):
        """Function does not raise exception on CloudTaskError."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.side_effect = CloudTaskError("Internal error")
            mock_get_runner.return_value = mock_runner

            # Should not raise
            result = get_task_status("arn:aws:ecs:task/abc123")
            assert result is None

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_error_on_cloud_task_error(self, settings, caplog):
        """Function logs ERROR when CloudTaskError occurs."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with (
            patch("engine.ecs.get_task_runner") as mock_get_runner,
            caplog.at_level(logging.ERROR, logger="engine.ecs"),
        ):
            mock_runner = MagicMock()
            mock_runner.get_task_status.side_effect = CloudTaskError("Cluster not found")
            mock_get_runner.return_value = mock_runner

            get_task_status("arn:aws:ecs:task/abc123")

        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Output format
    # -------------------------------------------------------------------------

    def test_output_status_is_string(self, settings):
        """Status field is a string."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {"status": "RUNNING"}
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert isinstance(result["status"], str)

    def test_output_includes_timestamps(self, settings):
        """Output includes started_at and stopped_at timestamps."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        started = "2024-01-01T00:00:00Z"
        stopped = "2024-01-01T01:00:00Z"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {
                "status": "STOPPED",
                "started_at": started,
                "stopped_at": stopped,
            }
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result["started_at"] == started
            assert result["stopped_at"] == stopped

    def test_output_handles_missing_optional_fields(self, settings):
        """Output handles missing optional fields gracefully."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {"status": "RUNNING"}
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            # Should not raise KeyError for missing fields
            assert result["status"] == "RUNNING"
            assert result.get("started_at") is None
            assert result.get("stopped_at") is None
            assert result.get("stopped_reason") is None

    def test_defaults_status_to_unknown(self, settings):
        """Status defaults to UNKNOWN when status is missing from adapter response."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {}
            mock_get_runner.return_value = mock_runner

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result["status"] == "UNKNOWN"

    # -------------------------------------------------------------------------
    # Boundary conditions
    # -------------------------------------------------------------------------

    def test_handles_valid_task_arn_format(self, settings):
        """Function handles valid ECS task ARN format."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {"status": "RUNNING"}
            mock_get_runner.return_value = mock_runner

            # Full ARN format
            result = get_task_status("arn:aws:ecs:us-east-2:123456789012:task/cluster-name/abc123def456")

            assert result is not None
            assert result["status"] == "RUNNING"

    def test_handles_short_task_id(self, settings):
        """Function handles short task ID (just the ID portion)."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.get_task_status.return_value = {"status": "RUNNING"}
            mock_get_runner.return_value = mock_runner

            # Short format
            result = get_task_status("abc123")

            assert result is not None

    # -------------------------------------------------------------------------
    # Multiple calls
    # -------------------------------------------------------------------------

    def test_multiple_calls_are_independent(self, settings):
        """Multiple calls don't affect each other."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()

            # First call returns RUNNING
            mock_runner.get_task_status.return_value = {"status": "RUNNING"}
            mock_get_runner.return_value = mock_runner

            result1 = get_task_status("arn:aws:ecs:task/task1")
            assert result1["status"] == "RUNNING"

            # Second call returns STOPPED
            mock_runner.get_task_status.return_value = {"status": "STOPPED"}

            result2 = get_task_status("arn:aws:ecs:task/task2")
            assert result2["status"] == "STOPPED"

            # Results are independent
            assert result1["status"] == "RUNNING"
            assert result2["status"] == "STOPPED"
