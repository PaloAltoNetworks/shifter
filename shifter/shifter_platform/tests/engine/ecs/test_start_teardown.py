"""Behavior tests for start_teardown().

start_teardown() delegates to _start_ecs_task with the "destroy" command. Driven
through the real dispatch with the ECS client mocked at the ``boto3`` boundary;
the delegation is asserted by the command line reaching ``boto3``.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from shared.cloud.exceptions import CloudTaskError

from .conftest import TASK_ARN, make_ecs_client, run_task_command


@contextmanager
def _boto3_client(client):
    with patch("boto3.client", return_value=client):
        yield


class TestStartTeardown:
    def test_dispatches_destroy_command(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_teardown

        start_teardown(range_id=42, user_id=7)
        assert run_task_command(ecs_client) == ["range", "destroy", "--range-id", "42", "--user-id", "7"]

    def test_returns_task_arn_on_success(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_teardown

        assert start_teardown(range_id=42, user_id=7) == TASK_ARN

    def test_returns_none_when_ecs_not_configured(self, aws_ecs_unconfigured, ecs_client):
        from engine.ecs import start_teardown

        assert start_teardown(range_id=42, user_id=7) is None
        ecs_client.run_task.assert_not_called()

    @pytest.mark.parametrize(
        ("range_id", "user_id", "exc_type"),
        [
            pytest.param(None, 7, TypeError, id="none-range_id"),
            pytest.param(-1, 7, ValueError, id="negative-range_id"),
            pytest.param(42, None, TypeError, id="none-user_id"),
            pytest.param(42, -1, ValueError, id="negative-user_id"),
        ],
    )
    def test_raises_on_invalid_input(self, aws_ecs_configured, range_id, user_id, exc_type):
        from engine.ecs import start_teardown

        with pytest.raises(exc_type):
            start_teardown(range_id=range_id, user_id=user_id)

    def test_raises_cloud_task_error_on_task_failure(self, aws_ecs_configured):
        from engine.ecs import start_teardown

        client = make_ecs_client()
        client.run_task.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Task launch failed"}}, "RunTask"
        )
        with pytest.raises(CloudTaskError), _boto3_client(client):
            start_teardown(range_id=42, user_id=7)
