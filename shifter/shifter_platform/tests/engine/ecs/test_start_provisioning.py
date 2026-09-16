"""Behavior tests for start_provisioning() (legacy range-id launch-intent enqueue).

After ADR-043-R2 (#1833) start_provisioning() (the legacy range-id path)
delegates to ``_start_ecs_task``, which no longer calls the provider
TaskRunner synchronously; it persists a durable ``ProvisionerLaunchIntent``
(fenced on the authorizing Range) that the ``drain_provisioner_launch_outbox``
worker dispatches. These tests assert the observable intent (command payload,
reserved task ref) and that nothing reaches the ``boto3`` ECS boundary. The
provider dispatch contract is covered by
``tests/engine/test_provisioner_launch_outbox.py`` and the enqueue fencing by
``tests/engine/test_launch_intents.py``.
"""

import pytest

from engine.models import ProvisionerLaunchIntent

from .conftest import make_authorized_legacy_range

pytestmark = pytest.mark.django_db(databases=["default"])


class TestStartProvisioning:
    def test_enqueues_intent_and_returns_reserved_ref(self, aws_ecs_configured, ecs_client):
        from engine.ecs import start_provisioning

        range_row = make_authorized_legacy_range()
        ref = start_provisioning(range_id=range_row.pk, user_id=range_row.user_id)

        intent = ProvisionerLaunchIntent.objects.get()
        assert ref == intent.task_ref
        assert intent.payload["resource"] == "range"
        assert intent.payload["operation"] == "provision"
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_ecs_not_configured(self, aws_ecs_unconfigured, ecs_client):
        from engine.ecs import start_provisioning

        range_row = make_authorized_legacy_range()
        assert start_provisioning(range_id=range_row.pk, user_id=range_row.user_id) is None
        assert not ProvisionerLaunchIntent.objects.exists()
        ecs_client.run_task.assert_not_called()


class TestStartProvisioningInputValidation:
    """Input validation happens before any config lookup or enqueue."""

    @pytest.mark.parametrize(
        ("range_id", "user_id", "exc_type"),
        [
            pytest.param(None, 7, TypeError, id="none-range_id"),
            pytest.param(-1, 7, ValueError, id="negative-range_id"),
            pytest.param(42, None, TypeError, id="none-user_id"),
            pytest.param(42, -1, ValueError, id="negative-user_id"),
        ],
    )
    def test_raises_on_invalid_input(self, aws_ecs_configured, range_id, user_id, exc_type):
        from engine.ecs import start_provisioning

        with pytest.raises(exc_type):
            start_provisioning(range_id=range_id, user_id=user_id)
