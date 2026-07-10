"""Behavior tests for _start_ngfw_ecs_task().

Drives the real NGFW ECS dispatch with AWS configured via settings and the ECS
client mocked at the ``boto3`` boundary. Asserts the command line / container
reaching ``boto3`` and the return/raise behavior, instead of patching
``get_task_runner``.
"""

import logging
from contextlib import contextmanager
from unittest.mock import patch
from uuid import UUID

import pytest
from botocore.exceptions import ClientError

from shared.cloud.exceptions import CloudTaskError

from .conftest import PROVISIONER_CONTAINER, TASK_ARN, make_ecs_client, run_task_command, run_task_container_name

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TEST_REQUEST_ID_2 = UUID("660e8400-e29b-41d4-a716-446655440001")


@contextmanager
def _boto3_client(client):
    with patch("boto3.client", return_value=client):
        yield


class TestStartNgfwEcsTask:
    def test_returns_task_arn_on_success(self, aws_ecs_configured, ecs_client):
        from engine.ecs import _start_ngfw_ecs_task

        result = _start_ngfw_ecs_task(
            request_id=TEST_REQUEST_ID, command=["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID)]
        )
        assert result == TASK_ARN

    def test_passes_command_and_container_to_dispatch(self, aws_ecs_configured, ecs_client):
        from engine.ecs import _start_ngfw_ecs_task

        command = ["ngfw", "deprovision", "--request-id", str(TEST_REQUEST_ID_2)]
        _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID_2, command=command)

        assert run_task_command(ecs_client) == command
        assert run_task_container_name(ecs_client) == PROVISIONER_CONTAINER

    def test_returns_none_when_cluster_missing(self, aws_ecs_unconfigured, settings, ecs_client):
        from engine.ecs import _start_ngfw_ecs_task

        settings.ENGINE_TASK_DEFINITION = "test-taskdef"
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-1,subnet-2"

        assert _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=["ngfw", "provision"]) is None
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_subnet_ids_whitespace(self, aws_ecs_configured, settings, ecs_client):
        from engine.ecs import _start_ngfw_ecs_task

        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "   ,   ,   "
        assert _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=["ngfw", "provision"]) is None
        ecs_client.run_task.assert_not_called()

    @pytest.mark.parametrize("request_id", [None, str(TEST_REQUEST_ID), 42])
    def test_validates_request_id_type(self, aws_ecs_configured, request_id):
        from engine.ecs import _start_ngfw_ecs_task

        with pytest.raises(TypeError):
            _start_ngfw_ecs_task(request_id=request_id, command=["ngfw", "provision"])

    def test_validates_command_type(self, aws_ecs_configured):
        from engine.ecs import _start_ngfw_ecs_task

        for invalid_cmd in (None, "ngfw provision"):
            with pytest.raises(TypeError):
                _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=invalid_cmd)
        with pytest.raises(ValueError, match="non-empty"):
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=[])

    def test_raises_cloud_task_error_when_run_task_fails(self, aws_ecs_configured):
        from engine.ecs import _start_ngfw_ecs_task

        client = make_ecs_client()
        client.run_task.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFoundException", "Message": "Cluster not found"}}, "RunTask"
        )
        with pytest.raises(CloudTaskError), _boto3_client(client):
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=["ngfw", "provision"])

    def test_raises_cloud_task_error_when_no_tasks_returned(self, aws_ecs_configured):
        from engine.ecs import _start_ngfw_ecs_task

        client = make_ecs_client(run_task_response={"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]})
        with pytest.raises(CloudTaskError), _boto3_client(client):
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=["ngfw", "provision"])

    def test_logs_warning_when_config_incomplete(self, aws_ecs_unconfigured, caplog):
        from engine.ecs import _start_ngfw_ecs_task

        with caplog.at_level(logging.WARNING, logger="engine.ecs"):
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=["ngfw", "provision"])
        assert "incomplete" in caplog.text.lower() or "skipping" in caplog.text.lower()

    def test_logs_request_id_on_success(self, aws_ecs_configured, ecs_client, caplog):
        from engine.ecs import _start_ngfw_ecs_task

        with caplog.at_level(logging.INFO, logger="engine.ecs"):
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=["ngfw", "provision"])
        assert str(TEST_REQUEST_ID) in caplog.text

    def test_logs_error_when_run_task_fails(self, aws_ecs_configured, caplog):
        from engine.ecs import _start_ngfw_ecs_task

        client = make_ecs_client()
        client.run_task.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFoundException", "Message": "Cluster not found"}}, "RunTask"
        )
        with caplog.at_level(logging.ERROR, logger="engine.ecs"), pytest.raises(CloudTaskError), _boto3_client(client):
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=["ngfw", "provision"])
        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()
