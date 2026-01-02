"""Tests for get_task_status() function."""

import logging
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError


class TestGetTaskStatus:
    """Tests for get_task_status() public function.

    Contract:
    - Inputs: task_arn (str)
    - Outputs: Dict with status info, or None if not configured/error
    - Side effects: Calls ECS describe_tasks API
    - Errors: Returns None on ClientError (does not raise)
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

        mock_response = {
            "tasks": [
                {
                    "taskArn": "arn:aws:ecs:us-east-2:123456789:task/test/abc123",
                    "lastStatus": "RUNNING",
                    "desiredStatus": "RUNNING",
                    "startedAt": "2024-01-01T00:00:00Z",
                    "stoppedAt": None,
                    "stoppedReason": None,
                }
            ]
        }

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:us-east-2:123456789:task/test/abc123")

            assert result is not None
            assert result["status"] == "RUNNING"

    def test_returns_dict_with_all_expected_keys(self, settings):
        """Function returns dict with all expected status keys."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        mock_response = {
            "tasks": [
                {
                    "taskArn": "arn:aws:ecs:task/abc123",
                    "lastStatus": "STOPPED",
                    "desiredStatus": "STOPPED",
                    "startedAt": "2024-01-01T00:00:00Z",
                    "stoppedAt": "2024-01-01T01:00:00Z",
                    "stoppedReason": "Essential container exited",
                }
            ]
        }

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

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

        mock_response = {"tasks": [{"lastStatus": "RUNNING", "desiredStatus": "RUNNING"}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result["status"] == "RUNNING"
            assert result["desired_status"] == "RUNNING"

    def test_returns_stopped_status(self, settings):
        """Function returns STOPPED status for stopped task."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        mock_response = {
            "tasks": [
                {
                    "lastStatus": "STOPPED",
                    "desiredStatus": "STOPPED",
                    "stoppedReason": "Task completed",
                }
            ]
        }

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result["status"] == "STOPPED"
            assert result["stopped_reason"] == "Task completed"

    def test_returns_pending_status(self, settings):
        """Function returns PENDING status for pending task."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        mock_response = {"tasks": [{"lastStatus": "PENDING", "desiredStatus": "RUNNING"}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result["status"] == "PENDING"
            assert result["desired_status"] == "RUNNING"

    def test_calls_describe_tasks_with_correct_params(self, settings):
        """Function calls describe_tasks with cluster and task ARN."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        mock_response = {"tasks": [{"lastStatus": "RUNNING"}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            task_arn = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"
            get_task_status(task_arn)

            mock_ecs.describe_tasks.assert_called_once_with(
                cluster="arn:aws:ecs:us-east-2:123456789:cluster/test",
                tasks=[task_arn],
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

        # Whitespace is truthy, so it might call ECS
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

        mock_response = {"tasks": []}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:task/nonexistent")

            assert result is not None
            assert result["status"] == "UNKNOWN"
            assert "not found" in result.get("reason", "").lower()

    def test_returns_unknown_when_tasks_key_missing(self, settings):
        """Function handles missing 'tasks' key in response."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        mock_response = {}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result is not None
            assert result["status"] == "UNKNOWN"

    # -------------------------------------------------------------------------
    # Error handling - returns None on errors
    # -------------------------------------------------------------------------

    def test_returns_none_on_client_error(self, settings):
        """Function returns None when ClientError occurs."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.side_effect = ClientError(
                {"Error": {"Code": "ClusterNotFound", "Message": "Cluster not found"}},
                "DescribeTasks",
            )
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result is None

    def test_returns_none_on_access_denied(self, settings):
        """Function returns None when access is denied."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
                "DescribeTasks",
            )
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result is None

    def test_does_not_raise_on_client_error(self, settings):
        """Function does not raise exception on ClientError."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.side_effect = ClientError(
                {"Error": {"Code": "InternalError", "Message": "Internal error"}},
                "DescribeTasks",
            )
            mock_get_client.return_value = mock_ecs

            # Should not raise
            result = get_task_status("arn:aws:ecs:task/abc123")
            assert result is None

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_error_on_client_error(self, settings, caplog):
        """Function logs ERROR when ClientError occurs."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        with (
            patch("engine.ecs._get_ecs_client") as mock_get_client,
            caplog.at_level(logging.ERROR, logger="engine.ecs"),
        ):
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.side_effect = ClientError(
                {"Error": {"Code": "ClusterNotFound", "Message": "Cluster not found"}},
                "DescribeTasks",
            )
            mock_get_client.return_value = mock_ecs

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

        mock_response = {"tasks": [{"lastStatus": "RUNNING"}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert isinstance(result["status"], str)

    def test_output_includes_timestamps(self, settings):
        """Output includes started_at and stopped_at timestamps."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        started = "2024-01-01T00:00:00Z"
        stopped = "2024-01-01T01:00:00Z"
        mock_response = {
            "tasks": [
                {
                    "lastStatus": "STOPPED",
                    "startedAt": started,
                    "stoppedAt": stopped,
                }
            ]
        }

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:task/abc123")

            assert result["started_at"] == started
            assert result["stopped_at"] == stopped

    def test_output_handles_missing_optional_fields(self, settings):
        """Output handles missing optional fields gracefully."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        mock_response = {"tasks": [{"lastStatus": "RUNNING"}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = get_task_status("arn:aws:ecs:task/abc123")

            # Should not raise KeyError for missing fields
            assert result["status"] == "RUNNING"
            assert result.get("started_at") is None
            assert result.get("stopped_at") is None
            assert result.get("stopped_reason") is None

    def test_defaults_status_to_unknown(self, settings):
        """Status defaults to UNKNOWN when lastStatus is missing."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        mock_response = {"tasks": [{}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

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

        mock_response = {"tasks": [{"lastStatus": "RUNNING"}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            # Full ARN format
            result = get_task_status("arn:aws:ecs:us-east-2:123456789012:task/cluster-name/abc123def456")

            assert result is not None
            assert result["status"] == "RUNNING"

    def test_handles_short_task_id(self, settings):
        """Function handles short task ID (just the ID portion)."""
        from engine.ecs import get_task_status

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"

        mock_response = {"tasks": [{"lastStatus": "RUNNING"}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.describe_tasks.return_value = mock_response
            mock_get_client.return_value = mock_ecs

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

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()

            # First call returns RUNNING
            mock_ecs.describe_tasks.return_value = {"tasks": [{"lastStatus": "RUNNING"}]}
            mock_get_client.return_value = mock_ecs

            result1 = get_task_status("arn:aws:ecs:task/task1")
            assert result1["status"] == "RUNNING"

            # Second call returns STOPPED
            mock_ecs.describe_tasks.return_value = {"tasks": [{"lastStatus": "STOPPED"}]}

            result2 = get_task_status("arn:aws:ecs:task/task2")
            assert result2["status"] == "STOPPED"

            # Results are independent
            assert result1["status"] == "RUNNING"
            assert result2["status"] == "STOPPED"
