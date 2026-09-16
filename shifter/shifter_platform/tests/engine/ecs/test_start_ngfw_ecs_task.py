"""Behavior tests for _start_ngfw_ecs_task() (NGFW launch-intent enqueue).

After ADR-043-R2 (#1833) the internal NGFW dispatch entrypoint no longer
calls the provider TaskRunner synchronously; it persists a durable
``ProvisionerLaunchIntent`` (fenced on the authorizing NGFW Instance) that the
``drain_provisioner_launch_outbox`` worker dispatches. These tests assert the
observable intent (command payload, reserved task ref) and that nothing
reaches the ``boto3`` ECS boundary. The provider dispatch contract is covered
by ``tests/engine/test_provisioner_launch_outbox.py`` and the enqueue fencing
by ``tests/engine/test_launch_intents.py``.
"""

import logging
from uuid import UUID

import pytest

from engine.models import ProvisionerLaunchIntent

from .conftest import make_authorized_ngfw

pytestmark = pytest.mark.django_db(databases=["default"])

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TEST_REQUEST_ID_2 = UUID("660e8400-e29b-41d4-a716-446655440001")


class TestStartNgfwEcsTask:
    def test_enqueues_provision_intent_and_returns_reserved_ref(self, aws_ecs_configured, ecs_client):
        from engine.ecs import _start_ngfw_ecs_task

        make_authorized_ngfw(TEST_REQUEST_ID, status="provisioning")
        command = ["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID)]
        ref = _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=command)

        intent = ProvisionerLaunchIntent.objects.get()
        assert ref == intent.task_ref
        assert intent.payload["resource"] == "ngfw"
        assert intent.payload["operation"] == "provision"
        ecs_client.run_task.assert_not_called()

    def test_enqueues_deprovision_intent_and_returns_reserved_ref(self, aws_ecs_configured, ecs_client):
        from engine.ecs import _start_ngfw_ecs_task

        make_authorized_ngfw(TEST_REQUEST_ID_2, status="ready")
        command = ["ngfw", "deprovision", "--request-id", str(TEST_REQUEST_ID_2)]
        ref = _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID_2, command=command)

        intent = ProvisionerLaunchIntent.objects.get()
        assert ref == intent.task_ref
        assert intent.payload["resource"] == "ngfw"
        assert intent.payload["operation"] == "deprovision"
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_cluster_missing(self, aws_ecs_unconfigured, settings, ecs_client):
        from engine.ecs import _start_ngfw_ecs_task

        # #1826: the provisioner dispatches as a Kubernetes Job, so the config
        # gate needs only the namespace + image; an image without a namespace is
        # incomplete and dispatch is a no-op.
        settings.ENGINE_TASK_DEFINITION = "test-taskdef"

        make_authorized_ngfw(TEST_REQUEST_ID, status="provisioning")
        assert _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=["ngfw", "provision"]) is None
        assert not ProvisionerLaunchIntent.objects.exists()
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

    def test_logs_request_id_on_enqueue(self, aws_ecs_configured, ecs_client, caplog):
        from engine.ecs import _start_ngfw_ecs_task

        make_authorized_ngfw(TEST_REQUEST_ID, status="provisioning")
        with caplog.at_level(logging.INFO, logger="engine.ecs"):
            _start_ngfw_ecs_task(
                request_id=TEST_REQUEST_ID,
                command=["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID)],
            )
        assert str(TEST_REQUEST_ID) in caplog.text
