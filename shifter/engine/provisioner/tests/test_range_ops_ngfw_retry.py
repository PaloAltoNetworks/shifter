"""Tests for NGFW start retry logic in ensure_ngfw_running().

Verifies that transient orchestration failures are retried up to
NGFW_START_MAX_RETRIES times before permanently failing the range.
"""

from unittest.mock import MagicMock, patch

import pytest

from range_ops import NGFW_START_MAX_RETRIES, ensure_ngfw_running

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_NGFW_INFO = {
    "ngfw_instance_id": 1,
    "ngfw_request_id": "ngfw-req-uuid",
    "ec2_instance_id": "i-ngfw123",
    "instance_uuid": "ngfw-inst-uuid",
    "status": "stopped",
    "app_id": "ngfw-app-uuid",
    "range_id": 42,
}


@pytest.fixture
def _mock_ngfw_deps():
    """Patch all external dependencies used by ensure_ngfw_running.

    Yields a dict of all mocks keyed by short name so individual tests
    can configure them further.
    """
    with (
        patch("range_ops.get_range_ngfw_info") as mock_get_info,
        patch("range_ops._update_ngfw_status") as mock_update,
        patch("range_ops.publish_ngfw_event") as mock_publish,
        patch("range_ops.AWSExecutor") as mock_executor_cls,
        patch("range_ops.OpsOrchestrator") as mock_orch_cls,
        patch("range_ops.NGFWStartPlan") as mock_plan_cls,
        patch("range_ops.time") as mock_time,
    ):
        # Default: return stopped NGFW info
        mock_get_info.return_value = dict(SAMPLE_NGFW_INFO)

        # Plan.get_context returns a simple dict
        mock_plan = MagicMock()
        mock_plan.get_context.return_value = {"instance_id": "i-ngfw123"}
        mock_plan_cls.return_value = mock_plan

        # Orchestrator instance
        mock_orch = MagicMock()
        mock_orch_cls.return_value = mock_orch

        yield {
            "get_info": mock_get_info,
            "update_status": mock_update,
            "publish": mock_publish,
            "executor_cls": mock_executor_cls,
            "orch": mock_orch,
            "plan": mock_plan,
            "time": mock_time,
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnsureNgfwRunningRetries:
    """Tests for the retry loop inside ensure_ngfw_running."""

    def test_retries_on_failure_then_succeeds(self, _mock_ngfw_deps):
        """Orchestrate is called 3 times when it fails twice then succeeds."""
        mocks = _mock_ngfw_deps
        fail = MagicMock(success=False, error="transient AWS error")
        success = MagicMock(success=True)

        mocks["orch"].orchestrate.side_effect = [fail, fail, success]

        # On retry re-queries, return still-stopped so retry continues
        mocks["get_info"].side_effect = [
            dict(SAMPLE_NGFW_INFO),  # initial call
            dict(SAMPLE_NGFW_INFO),  # re-query after attempt 1
            dict(SAMPLE_NGFW_INFO),  # re-query after attempt 2
        ]

        ensure_ngfw_running("req-uuid-123")

        assert mocks["orch"].orchestrate.call_count == NGFW_START_MAX_RETRIES
        assert mocks["time"].sleep.call_count == 2
        # Status should end up as active, not failed
        mocks["update_status"].assert_any_call(1, "active")

    def test_fails_after_max_retries(self, _mock_ngfw_deps):
        """RuntimeError is raised after all retry attempts are exhausted."""
        mocks = _mock_ngfw_deps
        fail = MagicMock(success=False, error="persistent AWS error")

        mocks["orch"].orchestrate.side_effect = [fail, fail, fail]

        # Re-query returns still-stopped on retry waits
        mocks["get_info"].side_effect = [
            dict(SAMPLE_NGFW_INFO),  # initial call
            dict(SAMPLE_NGFW_INFO),  # re-query after attempt 1
            dict(SAMPLE_NGFW_INFO),  # re-query after attempt 2
        ]

        with pytest.raises(RuntimeError, match="persistent AWS error"):
            ensure_ngfw_running("req-uuid-123")

        assert mocks["orch"].orchestrate.call_count == NGFW_START_MAX_RETRIES
        # time.sleep called for 2 inter-attempt delays (not after the last)
        assert mocks["time"].sleep.call_count == 2
        # Status should be set to failed
        mocks["update_status"].assert_any_call(1, "failed")
        # Failed event published
        mocks["publish"].assert_any_call(
            request_id="ngfw-req-uuid",
            instance_id="ngfw-inst-uuid",
            app_id="ngfw-app-uuid",
            status="failed",
        )
