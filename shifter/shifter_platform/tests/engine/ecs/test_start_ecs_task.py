"""Behavior tests for _start_ecs_task().

Drives the real ECS dispatch path with AWS configured via settings and the ECS
client mocked only at the ``boto3`` boundary. Asserts the dispatch contract that
reaches ``boto3`` (cluster, task definition, container, command line, network
config) and the return/raise behavior, instead of patching ``get_task_runner``.
"""

import logging
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from shared.cloud.exceptions import CloudTaskError

from .conftest import (
    CLUSTER,
    PROVISIONER_CONTAINER,
    TASK_ARN,
    TASK_DEFINITION,
    make_ecs_client,
    run_task_command,
    run_task_container_name,
)


@contextmanager
def _boto3_client(client):
    """Bind a custom ECS client at the boto3 boundary for a single call."""
    with patch("boto3.client", return_value=client):
        yield


class TestStartEcsTaskSuccess:
    def test_returns_task_arn_on_success(self, aws_ecs_configured, ecs_client):
        from engine.ecs import _start_ecs_task

        assert _start_ecs_task(range_id=42, user_id=7, command="provision") == TASK_ARN

    def test_dispatches_to_configured_cluster_and_task_definition(self, aws_ecs_configured, ecs_client):
        from engine.ecs import _start_ecs_task

        _start_ecs_task(range_id=42, user_id=7, command="provision")

        ecs_client.run_task.assert_called_once()
        kwargs = ecs_client.run_task.call_args.kwargs
        assert kwargs["cluster"] == CLUSTER
        assert kwargs["taskDefinition"] == TASK_DEFINITION
        assert kwargs["launchType"] == "FARGATE"
        assert run_task_container_name(ecs_client) == PROVISIONER_CONTAINER

    def test_passes_range_id_user_id_and_command_to_container(self, aws_ecs_configured, ecs_client):
        from engine.ecs import _start_ecs_task

        _start_ecs_task(range_id=99, user_id=7, command="destroy")

        assert run_task_command(ecs_client) == ["range", "destroy", "--range-id", "99", "--user-id", "7"]

    def test_includes_network_configuration(self, aws_ecs_configured, ecs_client):
        from engine.ecs import _start_ecs_task

        _start_ecs_task(range_id=42, user_id=7, command="provision")

        net = ecs_client.run_task.call_args.kwargs["networkConfiguration"]["awsvpcConfiguration"]
        assert net["subnets"] == ["subnet-aaa", "subnet-bbb"]
        assert net["securityGroups"] == ["sg-test"]


class TestStartEcsTaskConfigurationValidation:
    """Incomplete ECS config makes the function a no-op (returns None); it never
    reaches ``boto3``."""

    def test_returns_none_when_cluster_missing(self, aws_ecs_unconfigured, settings, ecs_client):
        from engine.ecs import _start_ecs_task

        settings.ENGINE_TASK_DEFINITION = "test-taskdef"
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-1,subnet-2"

        assert _start_ecs_task(range_id=42, user_id=7, command="provision") is None
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_task_definition_missing(self, aws_ecs_unconfigured, settings, ecs_client):
        from engine.ecs import _start_ecs_task

        settings.ENGINE_TASK_CLUSTER = "test-cluster"
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-1,subnet-2"

        assert _start_ecs_task(range_id=42, user_id=7, command="provision") is None
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_security_group_missing(self, aws_ecs_unconfigured, settings, ecs_client):
        from engine.ecs import _start_ecs_task

        settings.ENGINE_TASK_CLUSTER = "test-cluster"
        settings.ENGINE_TASK_DEFINITION = "test-taskdef"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-1,subnet-2"

        assert _start_ecs_task(range_id=42, user_id=7, command="provision") is None
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_subnet_ids_missing(self, aws_ecs_unconfigured, settings, ecs_client):
        from engine.ecs import _start_ecs_task

        settings.ENGINE_TASK_CLUSTER = "test-cluster"
        settings.ENGINE_TASK_DEFINITION = "test-taskdef"
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"

        assert _start_ecs_task(range_id=42, user_id=7, command="provision") is None
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_subnet_ids_empty(self, aws_ecs_configured, settings, ecs_client):
        from engine.ecs import _start_ecs_task

        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = ""
        assert _start_ecs_task(range_id=42, user_id=7, command="provision") is None
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_subnet_ids_whitespace(self, aws_ecs_configured, settings, ecs_client):
        from engine.ecs import _start_ecs_task

        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "   ,   ,   "
        assert _start_ecs_task(range_id=42, user_id=7, command="provision") is None
        ecs_client.run_task.assert_not_called()


class TestStartEcsTaskInputValidation:
    """Input validation happens before any config lookup or dispatch."""

    @pytest.mark.parametrize(
        ("range_id", "user_id", "command", "exc"),
        [
            (None, 7, "provision", TypeError),
            (-1, 7, "provision", ValueError),
            ("42", 7, "provision", TypeError),
            (42, None, "provision", TypeError),
            (42, -1, "provision", ValueError),
            (42, "7", "provision", TypeError),
            (42, 7, None, TypeError),
            (42, 7, "", ValueError),
        ],
    )
    def test_rejects_invalid_inputs(self, aws_ecs_configured, range_id, user_id, command, exc):
        from engine.ecs import _start_ecs_task

        with pytest.raises(exc):
            _start_ecs_task(range_id=range_id, user_id=user_id, command=command)


class TestStartEcsTaskCloudErrors:
    def test_raises_cloud_task_error_when_run_task_fails(self, aws_ecs_configured):
        from engine.ecs import _start_ecs_task

        client = make_ecs_client()
        client.run_task.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFoundException", "Message": "Cluster not found"}}, "RunTask"
        )
        with pytest.raises(CloudTaskError), _boto3_client(client):
            _start_ecs_task(range_id=42, user_id=7, command="provision")

    def test_raises_cloud_task_error_when_no_tasks_returned(self, aws_ecs_configured):
        from engine.ecs import _start_ecs_task

        client = make_ecs_client(run_task_response={"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]})
        with pytest.raises(CloudTaskError), _boto3_client(client):
            _start_ecs_task(range_id=42, user_id=7, command="provision")


class TestStartEcsTaskLogging:
    def test_logs_warning_when_config_incomplete(self, aws_ecs_unconfigured, caplog):
        from engine.ecs import _start_ecs_task

        with caplog.at_level(logging.WARNING, logger="engine.ecs"):
            _start_ecs_task(range_id=42, user_id=7, command="provision")
        assert "incomplete" in caplog.text.lower() or "skipping" in caplog.text.lower()

    def test_logs_error_when_subnet_ids_invalid(self, aws_ecs_configured, settings, caplog):
        from engine.ecs import _start_ecs_task

        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "   ,   "
        with caplog.at_level(logging.ERROR, logger="engine.ecs"):
            _start_ecs_task(range_id=42, user_id=7, command="provision")
        assert "empty" in caplog.text.lower() or "invalid" in caplog.text.lower()

    def test_logs_info_on_success(self, aws_ecs_configured, ecs_client, caplog):
        from engine.ecs import _start_ecs_task

        with caplog.at_level(logging.INFO, logger="engine.ecs"):
            _start_ecs_task(range_id=42, user_id=7, command="provision")
        assert "42" in caplog.text

    def test_logs_error_when_run_task_fails(self, aws_ecs_configured, caplog):
        from engine.ecs import _start_ecs_task

        client = make_ecs_client()
        client.run_task.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFoundException", "Message": "Cluster not found"}}, "RunTask"
        )
        with caplog.at_level(logging.ERROR, logger="engine.ecs"), pytest.raises(CloudTaskError), _boto3_client(client):
            _start_ecs_task(range_id=42, user_id=7, command="provision")
        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()
