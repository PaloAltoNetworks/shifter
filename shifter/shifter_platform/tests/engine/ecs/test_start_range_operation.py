"""Behavior tests for start_range_operation() (request-id launch-intent enqueue).

After ADR-043-R2 (#1833) the pause/resume request-id dispatch entrypoint no
longer calls the provider TaskRunner synchronously; it persists a durable
``ProvisionerLaunchIntent`` (fenced on the authorizing Range) that the
``drain_provisioner_launch_outbox`` worker dispatches. These tests assert the
observable intent (command payload, reserved task ref) and that nothing
reaches the ``boto3`` ECS boundary. The provider dispatch contract is covered
by ``tests/engine/test_provisioner_launch_outbox.py`` and the enqueue fencing
by ``tests/engine/test_launch_intents.py``.
"""

import logging
from uuid import UUID

import pytest

from engine.models import ProvisionerLaunchIntent, Range

from .conftest import make_authorized_range

pytestmark = pytest.mark.django_db(databases=["default"])

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


class TestStartRangeOperation:
    def test_enqueues_pause_intent_and_returns_reserved_ref(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_range_operation

        make_authorized_range(TEST_REQUEST_ID, status=Range.Status.PAUSING)
        ref = start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

        intent = ProvisionerLaunchIntent.objects.get()
        assert ref == intent.task_ref
        assert intent.payload["resource"] == "range"
        assert intent.payload["operation"] == "pause"
        ecs_client.run_task.assert_not_called()

    def test_enqueues_resume_intent_and_returns_reserved_ref(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_range_operation

        make_authorized_range(TEST_REQUEST_ID, status=Range.Status.RESUMING)
        ref = start_range_operation(request_id=TEST_REQUEST_ID, operation="resume")

        intent = ProvisionerLaunchIntent.objects.get()
        assert ref == intent.task_ref
        assert intent.payload["resource"] == "range"
        assert intent.payload["operation"] == "resume"
        ecs_client.run_task.assert_not_called()

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

        make_authorized_range(TEST_REQUEST_ID, status=Range.Status.PAUSING)
        assert start_range_operation(request_id=TEST_REQUEST_ID, operation="pause") is None
        assert not ProvisionerLaunchIntent.objects.exists()
        ecs_client.run_task.assert_not_called()

    def test_logs_enqueue_with_request_id(self, aws_ecs_configured, ecs_client, caplog):
        from engine.ecs import start_range_operation

        make_authorized_range(TEST_REQUEST_ID, status=Range.Status.PAUSING)
        with caplog.at_level(logging.INFO, logger="engine.ecs"):
            start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")
        assert "enqueuing" in caplog.text.lower()
        assert str(TEST_REQUEST_ID) in caplog.text
