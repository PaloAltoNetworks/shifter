"""Behavior tests for start_range_operation().

Drives the real pause/resume dispatch with AWS configured via settings and the
ECS client mocked at the ``boto3`` boundary. Asserts the command line reaching
``boto3`` and the return/raise behavior, instead of patching ``get_task_runner``.
"""

import logging
from contextlib import contextmanager
from unittest.mock import patch
from uuid import UUID

import pytest
from botocore.exceptions import ClientError

from shared.cloud.exceptions import CloudTaskError

from .conftest import TASK_ARN, make_ecs_client, run_task_command

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


@contextmanager
def _boto3_client(client):
    with patch("boto3.client", return_value=client):
        yield


class TestStartRangeOperation:
    def test_returns_task_arn_for_pause(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_range_operation

        assert start_range_operation(request_id=TEST_REQUEST_ID, operation="pause") == TASK_ARN

    def test_returns_task_arn_for_resume(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_range_operation

        assert start_range_operation(request_id=TEST_REQUEST_ID, operation="resume") == TASK_ARN

    def test_dispatches_pause_command(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_range_operation

        start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")
        assert run_task_command(ecs_client) == ["range", "pause", "--request-id", str(TEST_REQUEST_ID)]

    def test_dispatches_resume_command(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_range_operation

        start_range_operation(request_id=TEST_REQUEST_ID, operation="resume")
        assert run_task_command(ecs_client) == ["range", "resume", "--request-id", str(TEST_REQUEST_ID)]

    @pytest.mark.parametrize("operation", ["invalid", "provision", "destroy"])
    def test_rejects_invalid_operation(self, aws_ecs_configured, operation):
        from engine.ecs import start_range_operation

        with pytest.raises(ValueError, match="Invalid operation"):
            start_range_operation(request_id=TEST_REQUEST_ID, operation=operation)

    @pytest.mark.parametrize("request_id", [None, str(TEST_REQUEST_ID), 42])
    def test_rejects_non_uuid_request_id(self, aws_ecs_configured, request_id):
        from engine.ecs import start_range_operation

        with pytest.raises(TypeError):
            start_range_operation(request_id=request_id, operation="pause")

    def test_returns_none_when_unconfigured(self, aws_ecs_unconfigured, ecs_client):
        from engine.ecs import start_range_operation

        assert start_range_operation(request_id=TEST_REQUEST_ID, operation="pause") is None
        ecs_client.run_task.assert_not_called()

    def test_raises_cloud_task_error_when_dispatch_fails(self, aws_ecs_configured):
        from engine.ecs import start_range_operation

        client = make_ecs_client()
        client.run_task.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFoundException", "Message": "Cluster not found"}}, "RunTask"
        )
        with pytest.raises(CloudTaskError), _boto3_client(client):
            start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

    def test_logs_warning_when_config_incomplete(self, aws_ecs_unconfigured, caplog):
        from engine.ecs import start_range_operation

        with caplog.at_level(logging.WARNING, logger="engine.ecs"):
            start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")
        assert "incomplete" in caplog.text.lower() or "skipping" in caplog.text.lower()

    def test_logs_request_id_on_success(self, aws_ecs_configured, ecs_client, caplog):
        from engine.ecs import start_range_operation

        with caplog.at_level(logging.INFO, logger="engine.ecs"):
            start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")
        assert str(TEST_REQUEST_ID) in caplog.text
