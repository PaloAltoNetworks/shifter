"""Behavior tests for start_aces_range_provisioning() (ADR-031).

The ACES-native dispatcher reuses the same request_id-keyed ECS mechanics as the
cyberscript ``start_range_provisioning()``, differing only in the provisioner
subcommand (``"aces-range"`` instead of ``"range"``) so the provisioner realizes
a persisted ProvisioningSpec rather than a wrapped RangeSpec. Driven through the
real dispatch with the ECS client mocked at the ``boto3`` boundary; the
subcommand is asserted by the command line reaching ``boto3``.
"""

from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from shared.cloud.exceptions import CloudTaskError

from .conftest import TASK_ARN, make_ecs_client, run_task_command


@contextmanager
def _boto3_client(client):
    with patch("boto3.client", return_value=client):
        yield


class TestStartAcesRangeProvisioning:
    def test_dispatches_aces_range_provision_command(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_aces_range_provisioning

        request_id = uuid4()
        start_aces_range_provisioning(request_id)
        assert run_task_command(ecs_client) == ["aces-range", "provision", "--request-id", str(request_id)]

    def test_returns_task_arn_on_success(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_aces_range_provisioning

        assert start_aces_range_provisioning(uuid4()) == TASK_ARN

    def test_returns_none_when_ecs_not_configured(self, aws_ecs_unconfigured, ecs_client):
        from engine.ecs import start_aces_range_provisioning

        assert start_aces_range_provisioning(uuid4()) is None
        ecs_client.run_task.assert_not_called()

    def test_raises_type_error_on_non_uuid_request_id(self, aws_ecs_configured):
        from engine.ecs import start_aces_range_provisioning

        with pytest.raises(TypeError):
            start_aces_range_provisioning("not-a-uuid")

    def test_raises_cloud_task_error_on_task_failure(self, aws_ecs_configured):
        from engine.ecs import start_aces_range_provisioning

        client = make_ecs_client()
        client.run_task.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Task launch failed"}}, "RunTask"
        )
        range_id = uuid4()
        with pytest.raises(CloudTaskError), _boto3_client(client):
            start_aces_range_provisioning(range_id)


class TestStartAcesRangeTeardown:
    def test_dispatches_aces_range_destroy_command(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_aces_range_teardown

        request_id = uuid4()
        start_aces_range_teardown(request_id)
        assert run_task_command(ecs_client) == ["aces-range", "destroy", "--request-id", str(request_id)]

    def test_returns_none_when_ecs_not_configured(self, aws_ecs_unconfigured, ecs_client):
        from engine.ecs import start_aces_range_teardown

        assert start_aces_range_teardown(uuid4()) is None
        ecs_client.run_task.assert_not_called()
