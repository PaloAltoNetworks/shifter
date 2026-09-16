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

# Opaque #1325 workspace scope binding (ADR-046-R3). These suites do not
# exercise tenancy; a fixed scalar stands in for the value the CMS launch
# facade resolves in production.
_WORKSPACE_ID = 1

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


# ---------------------------------------------------------------------------
# Domain-row helpers for provider-neutral launch-intent dispatch (#1833).
#
# After ADR-043-R2 the public dispatch entrypoints no longer call the provider
# TaskRunner synchronously; they persist a ``ProvisionerLaunchIntent`` (fenced
# on domain state) that the ``drain_provisioner_launch_outbox`` worker later
# dispatches. So a dispatch test must set up the authorizing domain row and then
# assert the enqueued intent (observable DB state) rather than a ``boto3``
# ``run_task`` call. The enqueue fencing itself is covered by
# ``tests/engine/test_launch_intents.py`` and the drainer's provider dispatch by
# ``tests/engine/test_provisioner_launch_outbox.py``; these helpers keep the
# per-family dispatch tests focused on "the right command is enqueued for this
# family on both providers."
# ---------------------------------------------------------------------------


def make_authorized_range(request_id, *, status=None, request_type="range"):
    """Create the User/Request/Range that authorizes a request-based range op."""
    from django.contrib.auth import get_user_model

    from engine.models import Range, Request

    user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
    request = Request.objects.create(request_id=str(request_id), request_type=request_type, user=user)
    range_row = Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=request,
        user=user,
        status=status if status is not None else Range.Status.PROVISIONING,
    )
    return request, range_row


def make_authorized_legacy_range(*, status=None):
    """Create a range addressed by the legacy range-id/user-id command shape."""

    _request, range_row = make_authorized_range("00000000-0000-0000-0000-0000000000aa", status=status)
    return range_row


def make_authorized_ngfw(request_id, *, status="provisioning"):
    """Create the User/Request/NGFW Instance/App that authorizes an NGFW op."""
    from django.contrib.auth import get_user_model

    from engine.models import App, Instance, Request

    user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
    request = Request.objects.create(request_id=str(request_id), request_type="ngfw", user=user)
    instance = Instance.objects.create(
        request=request,
        role=Instance.Role.NGFW,
        os_type=Instance.OSType.PANOS,
        status=status,
    )
    App.objects.create(instance=instance, app_type=App.AppType.NGFW, status=status)
    return request, instance


def only_launch_intent():
    """Return the single enqueued launch intent (fails if not exactly one)."""
    from engine.models import ProvisionerLaunchIntent

    return ProvisionerLaunchIntent.objects.get()
