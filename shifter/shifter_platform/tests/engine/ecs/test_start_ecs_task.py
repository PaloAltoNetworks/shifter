"""Behavior tests for _start_ecs_task() (legacy range-id launch-intent enqueue).

After ADR-043-R2 (#1833) the legacy range-id dispatch entrypoint no longer calls
the provider TaskRunner synchronously; it persists a durable
``ProvisionerLaunchIntent`` (fenced on the authorizing Range) that the
``drain_provisioner_launch_outbox`` worker dispatches. These tests drive the real
enqueue against AWS settings and assert the observable intent (command payload,
reserved task ref) and that nothing reaches the ``boto3`` ECS boundary. The
provider dispatch contract is covered by
``tests/engine/test_provisioner_launch_outbox.py`` and the enqueue fencing by
``tests/engine/test_launch_intents.py``.
"""

import logging

import pytest

from engine.models import ProvisionerLaunchIntent, Range

from .conftest import make_authorized_legacy_range

pytestmark = pytest.mark.django_db(databases=["default"])


class TestStartEcsTaskEnqueue:
    """The legacy dispatch entrypoint enqueues a fenced launch intent for the
    launcher worker instead of synchronously starting an ECS task."""

    def test_enqueues_intent_and_returns_reserved_ref(self, aws_ecs_configured, ecs_client):
        from engine.ecs import _start_ecs_task

        range_row = make_authorized_legacy_range()
        ref = _start_ecs_task(range_id=range_row.pk, user_id=range_row.user_id, command="provision")

        intent = ProvisionerLaunchIntent.objects.get()
        assert ref == intent.task_ref
        assert intent.payload["resource"] == "range"
        assert intent.payload["operation"] == "provision"
        range_row.refresh_from_db()
        assert intent.operation_id == range_row.provisioner_operation_id
        ecs_client.run_task.assert_not_called()

    def test_enqueues_destroy_for_a_destroying_range(self, aws_ecs_configured, ecs_client):
        from engine.ecs import _start_ecs_task

        range_row = make_authorized_legacy_range(status=Range.Status.DESTROYING)
        _start_ecs_task(range_id=range_row.pk, user_id=range_row.user_id, command="destroy")

        intent = ProvisionerLaunchIntent.objects.get()
        assert intent.payload["operation"] == "destroy"
        ecs_client.run_task.assert_not_called()


class TestStartEcsTaskConfigurationValidation:
    """Incomplete task-runner config makes the entrypoint a no-op (returns None):
    it persists no intent (no ghost launch) and never reaches the provider port.

    Since #1826 the provisioner dispatches as a Kubernetes Job on both AWS (EKS)
    and GCP (GKE), so the config gate requires only the namespace
    (``ENGINE_TASK_CLUSTER``) and image (``ENGINE_TASK_DEFINITION``); the former
    ECS security-group / subnet requirements no longer gate dispatch."""

    def test_returns_none_when_cluster_missing(self, aws_ecs_unconfigured, settings, ecs_client):
        from engine.ecs import _start_ecs_task

        settings.ENGINE_TASK_DEFINITION = "test-taskdef"

        range_row = make_authorized_legacy_range()
        assert _start_ecs_task(range_id=range_row.pk, user_id=range_row.user_id, command="provision") is None
        assert not ProvisionerLaunchIntent.objects.exists()
        ecs_client.run_task.assert_not_called()

    def test_returns_none_when_task_definition_missing(self, aws_ecs_unconfigured, settings, ecs_client):
        from engine.ecs import _start_ecs_task

        settings.ENGINE_TASK_CLUSTER = "test-cluster"

        range_row = make_authorized_legacy_range()
        assert _start_ecs_task(range_id=range_row.pk, user_id=range_row.user_id, command="provision") is None
        assert not ProvisionerLaunchIntent.objects.exists()
        ecs_client.run_task.assert_not_called()


class TestStartEcsTaskInputValidation:
    """Input validation happens before any config lookup or enqueue."""

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


class TestStartEcsTaskLogging:
    def test_logs_enqueue_on_success(self, aws_ecs_configured, ecs_client, caplog):
        from engine.ecs import _start_ecs_task

        range_row = make_authorized_legacy_range()
        with caplog.at_level(logging.INFO, logger="engine.ecs"):
            _start_ecs_task(range_id=range_row.pk, user_id=range_row.user_id, command="provision")
        assert "enqueuing" in caplog.text.lower()
        assert str(range_row.pk) in caplog.text

    def test_logs_warning_when_config_incomplete(self, aws_ecs_unconfigured, ecs_client, caplog):
        from engine.ecs import _start_ecs_task

        range_row = make_authorized_legacy_range()
        with caplog.at_level(logging.WARNING, logger="engine.ecs"):
            _start_ecs_task(range_id=range_row.pk, user_id=range_row.user_id, command="provision")
        assert "incomplete" in caplog.text.lower() or "skipping" in caplog.text.lower()
