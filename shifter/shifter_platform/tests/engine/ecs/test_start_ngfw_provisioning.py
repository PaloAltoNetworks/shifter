"""Behavior tests for start_ngfw_provisioning().

Thin wrapper that delegates to _start_ngfw_ecs_task with an "ngfw provision"
command. Driven through the real dispatch with the ECS client mocked at the
``boto3`` boundary; the delegation is asserted by the command line reaching
``boto3``.
"""

from contextlib import contextmanager
from unittest.mock import patch
from uuid import UUID

import pytest
from botocore.exceptions import ClientError

from shared.cloud.exceptions import CloudTaskError

from .conftest import TASK_ARN, make_ecs_client, run_task_command

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TEST_REQUEST_ID_2 = UUID("660e8400-e29b-41d4-a716-446655440001")


@contextmanager
def _boto3_client(client):
    with patch("boto3.client", return_value=client):
        yield


class TestStartNgfwProvisioning:
    def test_dispatches_provision_command(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_ngfw_provisioning

        start_ngfw_provisioning(request_id=TEST_REQUEST_ID_2)
        assert run_task_command(ecs_client) == ["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID_2)]

    def test_returns_task_arn_on_success(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_ngfw_provisioning

        assert start_ngfw_provisioning(request_id=TEST_REQUEST_ID) == TASK_ARN

    def test_returns_none_when_ecs_not_configured(self, aws_ecs_unconfigured, ecs_client):
        from engine.ecs import start_ngfw_provisioning

        assert start_ngfw_provisioning(request_id=TEST_REQUEST_ID) is None
        ecs_client.run_task.assert_not_called()

    def test_raises_type_error_for_none_request_id(self, aws_ecs_configured):
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(TypeError):
            start_ngfw_provisioning(request_id=None)

    def test_raises_cloud_task_error_on_task_failure(self, aws_ecs_configured):
        from engine.ecs import start_ngfw_provisioning

        client = make_ecs_client()
        client.run_task.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Task launch failed"}}, "RunTask"
        )
        with pytest.raises(CloudTaskError), _boto3_client(client):
            start_ngfw_provisioning(request_id=TEST_REQUEST_ID)
