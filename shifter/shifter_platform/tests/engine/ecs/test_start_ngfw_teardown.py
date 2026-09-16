"""Behavior tests for start_ngfw_teardown() (NGFW launch-intent enqueue).

Thin wrapper that delegates to ``_start_ngfw_ecs_task`` with an "ngfw
deprovision" command. After ADR-043-R2 (#1833) that no longer calls the
provider TaskRunner synchronously; it persists a durable
``ProvisionerLaunchIntent`` (fenced on the authorizing NGFW Instance) that the
``drain_provisioner_launch_outbox`` worker dispatches. These tests assert the
observable intent (command payload, reserved task ref) and that nothing
reaches the ``boto3`` ECS boundary. The provider dispatch contract is covered
by ``tests/engine/test_provisioner_launch_outbox.py`` and the enqueue fencing
by ``tests/engine/test_launch_intents.py``.
"""

from uuid import UUID

import pytest

from engine.models import ProvisionerLaunchIntent

from .conftest import make_authorized_ngfw

pytestmark = pytest.mark.django_db(databases=["default"])

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


class TestStartNgfwTeardown:
    def test_enqueues_intent_and_returns_reserved_ref(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_ngfw_teardown

        make_authorized_ngfw(TEST_REQUEST_ID, status="ready")
        ref = start_ngfw_teardown(request_id=TEST_REQUEST_ID)

        intent = ProvisionerLaunchIntent.objects.get()
        assert ref == intent.task_ref
        assert intent.payload["resource"] == "ngfw"
        assert intent.payload["operation"] == "deprovision"
        ecs_client.run_task.assert_not_called()

    def test_uses_deprovision_not_provision(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_ngfw_teardown

        make_authorized_ngfw(TEST_REQUEST_ID, status="ready")
        start_ngfw_teardown(request_id=TEST_REQUEST_ID)

        intent = ProvisionerLaunchIntent.objects.get()
        assert intent.payload["operation"] == "deprovision"
        assert intent.payload["operation"] != "provision"

    def test_returns_none_when_ecs_not_configured(self, aws_ecs_unconfigured, ecs_client):
        from engine.ecs import start_ngfw_teardown

        make_authorized_ngfw(TEST_REQUEST_ID, status="ready")
        assert start_ngfw_teardown(request_id=TEST_REQUEST_ID) is None
        assert not ProvisionerLaunchIntent.objects.exists()
        ecs_client.run_task.assert_not_called()

    def test_raises_type_error_for_none_request_id(self, aws_ecs_configured):
        from engine.ecs import start_ngfw_teardown

        with pytest.raises(TypeError):
            start_ngfw_teardown(request_id=None)
