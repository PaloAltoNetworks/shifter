"""Shared boundary fixtures for the engine.services behavior tests.

These drive the real ``engine.secrets`` helpers (and their callers) against the
provider secrets store with the AWS Secrets Manager client mocked at the
``boto3`` boundary, instead of patching the first-party ``get_secrets_store`` /
``get_ssh_key`` helpers. Fixtures are opt-in (not autouse) so the existing
services suites that manage ``boto3.client`` themselves are unaffected.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# Opaque stand-in for SSH key material; tests only assert it round-trips from the
# secrets store, never that it is a valid key. A literal PEM block would trip the
# detect-private-key pre-commit hook, so an opaque token is used instead.
SSH_KEY_PEM = "TEST-SSH-PRIVATE-KEY-MATERIAL"  # nosec B105  # NOSONAR


def make_secrets_client(value=SSH_KEY_PEM):
    """Build a MagicMock standing in for the boto3 Secrets Manager client."""
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": value}
    return client


@contextmanager
def boto3_secrets(client):
    """Bind a Secrets Manager client at the boto3 boundary."""
    with patch("boto3.client", return_value=client):
        yield client


@pytest.fixture
def secrets_client(settings):
    """Patch the boto3 Secrets Manager client; expose the mock for assertions."""
    settings.CLOUD_PROVIDER = "aws"
    client = make_secrets_client()
    with patch("boto3.client", return_value=client):
        yield client


# --- ECS task-dispatch boundary (for NGFW teardown / lifecycle operations) ----

ECS_TASK_ARN = "arn:aws:ecs:us-east-2:123:task/test-cluster/op"


def make_ecs_client(*, task_arn=ECS_TASK_ARN):
    """Build a MagicMock standing in for the boto3 ECS client."""
    client = MagicMock()
    client.run_task.return_value = {"tasks": [{"taskArn": task_arn}]}
    return client


@pytest.fixture
def ecs_dispatch(settings):
    """Configure AWS ECS and patch the boto3 ECS client so engine.ecs dispatches.

    Yields the ECS client mock; ``run_task`` call args expose the dispatched
    command line for assertions.
    """
    settings.CLOUD_PROVIDER = "aws"
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = "test-cluster"
    settings.ENGINE_TASK_DEFINITION = "test-taskdef"
    settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
    settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-aaa,subnet-bbb"
    client = make_ecs_client()
    with patch("boto3.client", return_value=client):
        yield client


@pytest.fixture
def ecs_unconfigured(settings):
    """Clear ECS config so engine.ecs dispatch is a no-op (returns None)."""
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


def ecs_run_task_command(client):
    """Return the container command line passed to boto3 run_task."""
    return client.run_task.call_args.kwargs["overrides"]["containerOverrides"][0]["command"]
