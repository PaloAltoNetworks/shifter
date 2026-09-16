"""Behavior tests for start_raes_range_provisioning() / start_raes_range_teardown() (ADR-031).

The RAES-native dispatcher reuses the same request_id-keyed launch-intent
mechanics as the cyberscript ``start_range_provisioning()``/
``start_range_teardown()``, differing only in the provisioner subcommand
(``"raes-range"`` instead of ``"range"``) so the provisioner realizes a
persisted ProvisioningSpec rather than a wrapped RangeSpec. After
ADR-043-R2 (#1833) that dispatch no longer calls the provider TaskRunner
synchronously; it persists a durable ``ProvisionerLaunchIntent`` (fenced on
the authorizing Range) that the ``drain_provisioner_launch_outbox`` worker
dispatches. These tests assert the observable intent (command payload,
reserved task ref) and that nothing reaches the ``boto3`` ECS boundary. The
provider dispatch contract is covered by
``tests/engine/test_provisioner_launch_outbox.py`` and the enqueue fencing by
``tests/engine/test_launch_intents.py``.
"""

from uuid import uuid4

import pytest

from engine.models import ProvisionerLaunchIntent, Range

from .conftest import make_authorized_range

pytestmark = pytest.mark.django_db(databases=["default"])


class TestStartRaesRangeProvisioning:
    def test_enqueues_intent_and_returns_reserved_ref(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_raes_range_provisioning

        request_id = uuid4()
        make_authorized_range(request_id, status=Range.Status.PROVISIONING)
        ref = start_raes_range_provisioning(request_id)

        intent = ProvisionerLaunchIntent.objects.get()
        assert ref == intent.task_ref
        assert intent.payload["resource"] == "raes-range"
        assert intent.payload["operation"] == "provision"
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_ecs_not_configured(self, aws_ecs_unconfigured, ecs_client):
        from engine.ecs import start_raes_range_provisioning

        request_id = uuid4()
        make_authorized_range(request_id, status=Range.Status.PROVISIONING)
        assert start_raes_range_provisioning(request_id) is None
        assert not ProvisionerLaunchIntent.objects.exists()
        ecs_client.run_task.assert_not_called()

    def test_raises_type_error_on_non_uuid_request_id(self, aws_ecs_configured):
        from engine.ecs import start_raes_range_provisioning

        with pytest.raises(TypeError):
            start_raes_range_provisioning("not-a-uuid")


class TestStartRaesRangeTeardown:
    def test_enqueues_intent_and_returns_reserved_ref(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_raes_range_teardown

        request_id = uuid4()
        make_authorized_range(request_id, status=Range.Status.DESTROYING)
        ref = start_raes_range_teardown(request_id)

        intent = ProvisionerLaunchIntent.objects.get()
        assert ref == intent.task_ref
        assert intent.payload["resource"] == "raes-range"
        assert intent.payload["operation"] == "destroy"
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_ecs_not_configured(self, aws_ecs_unconfigured, ecs_client):
        from engine.ecs import start_raes_range_teardown

        request_id = uuid4()
        make_authorized_range(request_id, status=Range.Status.DESTROYING)
        assert start_raes_range_teardown(request_id) is None
        assert not ProvisionerLaunchIntent.objects.exists()
        ecs_client.run_task.assert_not_called()
