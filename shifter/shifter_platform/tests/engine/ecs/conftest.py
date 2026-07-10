"""Shared fixtures for the engine ECS task-dispatch behavior tests.

The engine ``ecs`` module builds CLI command lines and dispatches them through
the real ``shared.cloud`` task runner. These tests drive the real dispatch with
AWS configured via settings and the ECS client mocked at the ``boto3`` boundary,
so we assert the actual dispatch contract (cluster / task definition / container
/ command line / network config reaching ``boto3``) instead of patching the
first-party ``get_task_runner`` / ``_start_*`` helpers.
"""

from unittest.mock import MagicMock, patch

import pytest

CLUSTER = "test-cluster"
TASK_DEFINITION = "test-taskdef"
SECURITY_GROUP = "sg-test"
SUBNETS = "subnet-aaa,subnet-bbb"
TASK_ARN = "arn:aws:ecs:us-east-2:123456789:task/test-cluster/abc123"
PROVISIONER_CONTAINER = "pulumi-provisioner"


@pytest.fixture
def aws_ecs_configured(settings):
    """Configure a complete AWS ECS task-runner environment.

    Sets the canonical ENGINE_TASK_* settings and clears the legacy *_ARN
    aliases so the config gate is unambiguous regardless of ambient settings.
    """
    settings.CLOUD_PROVIDER = "aws"
    settings.LOCAL_PROVISIONER = None
    settings.AWS_REGION = "us-east-2"
    settings.ENGINE_TASK_CLUSTER = CLUSTER
    settings.ENGINE_TASK_DEFINITION = TASK_DEFINITION
    settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = SECURITY_GROUP
    settings.ENGINE_TASK_NETWORK_SUBNET_IDS = SUBNETS
    settings.ENGINE_ECS_CLUSTER_ARN = ""
    settings.ENGINE_TASK_DEFINITION_ARN = ""
    settings.ENGINE_ECS_SECURITY_GROUP_ID = ""
    settings.ENGINE_PRIVATE_SUBNET_IDS = ""
    return settings


@pytest.fixture
def aws_ecs_unconfigured(settings):
    """Clear every ECS config setting so the dispatch is a no-op (returns None)."""
    settings.CLOUD_PROVIDER = "aws"
    settings.LOCAL_PROVISIONER = None
    for name in (
        "ENGINE_TASK_CLUSTER",
        "ENGINE_TASK_DEFINITION",
        "ENGINE_TASK_NETWORK_SECURITY_GROUP_ID",
        "ENGINE_TASK_NETWORK_SUBNET_IDS",
        "ENGINE_ECS_CLUSTER_ARN",
        "ENGINE_TASK_DEFINITION_ARN",
        "ENGINE_ECS_SECURITY_GROUP_ID",
        "ENGINE_PRIVATE_SUBNET_IDS",
    ):
        setattr(settings, name, "")
    return settings


def make_ecs_client(*, task_arn=TASK_ARN, run_task_response=None, describe_response=None):
    """Build a MagicMock standing in for the boto3 ECS client."""
    client = MagicMock()
    if run_task_response is not None:
        client.run_task.return_value = run_task_response
    else:
        client.run_task.return_value = {"tasks": [{"taskArn": task_arn}]}
    if describe_response is not None:
        client.describe_tasks.return_value = describe_response
    return client


@pytest.fixture
def ecs_client():
    """Patch the boto3 ECS client and expose the mock for call assertions."""
    client = make_ecs_client()
    with patch("boto3.client", return_value=client):
        yield client


def run_task_command(client):
    """Return the container command line passed to ``boto3`` run_task."""
    kwargs = client.run_task.call_args.kwargs
    return kwargs["overrides"]["containerOverrides"][0]["command"]


def run_task_container_name(client):
    kwargs = client.run_task.call_args.kwargs
    return kwargs["overrides"]["containerOverrides"][0]["name"]
