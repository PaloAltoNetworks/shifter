"""Tests for the dedicated provisioner launcher outbox worker."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

pytestmark = pytest.mark.django_db(databases=["default"])


def _intent(request_id: str = "11111111-1111-1111-1111-111111111111"):
    from django.contrib.auth import get_user_model

    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent, Range, Request

    user = get_user_model().objects.create_user(username=f"launcher-{request_id}@example.com")
    request = Request.objects.create(request_id=request_id, request_type="range", user=user)
    Range.objects.create(request=request, user=user, status=Range.Status.PROVISIONING)

    ref = enqueue_provisioner_launch(["range", "provision", "--request-id", request_id])
    return ProvisionerLaunchIntent.objects.get(intent_id=ref)


def _configure_aws(settings) -> None:
    settings.CLOUD_PROVIDER = "aws"
    settings.ENGINE_TASK_CLUSTER = "cluster"
    settings.ENGINE_TASK_DEFINITION = "task-definition"
    settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-123"
    settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-123"
    settings.ENGINE_ECS_CLUSTER_ARN = ""
    settings.ENGINE_TASK_DEFINITION_ARN = ""


def test_drainer_launches_canonical_command_and_marks_succeeded(settings) -> None:
    row = _intent()
    _configure_aws(settings)
    client = MagicMock()
    client.run_task.return_value = {"tasks": [{"taskArn": "arn:aws:ecs:region:account:task/job-1"}]}

    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    command = client.run_task.call_args.kwargs["overrides"]["containerOverrides"][0]["command"]
    assert command == ["range", "provision", "--request-id", "11111111-1111-1111-1111-111111111111"]
    assert row.status == "SUCCEEDED"
    assert row.task_ref == "arn:aws:ecs:region:account:task/job-1"


def test_drainer_retries_failure_without_leaking_error_details(settings) -> None:
    row = _intent()
    before = timezone.now()
    _configure_aws(settings)
    client = MagicMock()
    client.run_task.side_effect = RuntimeError("token=super-secret")

    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    assert row.status == "PENDING"
    assert row.attempts == 1
    assert row.last_error == "RuntimeError"
    assert row.next_attempt_at >= before + timedelta(seconds=55)
    assert row.last_error == "RuntimeError"


def test_succeeded_intent_is_not_launched_twice(settings) -> None:
    row = _intent()
    row.status = "SUCCEEDED"
    row.save(update_fields=["status"])
    _configure_aws(settings)
    client = MagicMock()

    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    client.run_task.assert_not_called()


def test_expired_running_claim_recovers_with_same_task_identity(settings) -> None:
    row = _intent()
    row.status = "RUNNING"
    row.next_attempt_at = timezone.now() - timedelta(seconds=1)
    row.save(update_fields=["status", "next_attempt_at"])
    _configure_aws(settings)
    client = MagicMock()
    client.run_task.return_value = {"tasks": [{"taskArn": "arn:aws:ecs:region:account:task/job-stable"}]}

    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    assert row.status == "SUCCEEDED"
    assert row.task_ref == "arn:aws:ecs:region:account:task/job-stable"
    assert client.run_task.call_args.kwargs["clientToken"] == str(row.intent_id)


def test_drainer_refreshes_observable_heartbeat_during_launch(settings) -> None:
    from engine.management.commands.drain_provisioner_launch_outbox import HEARTBEAT_FILE

    _intent()
    _configure_aws(settings)
    client = MagicMock()
    client.run_task.return_value = {"tasks": [{"taskArn": "arn:aws:ecs:region:account:task/job-1"}]}
    before = HEARTBEAT_FILE.stat().st_mtime_ns if HEARTBEAT_FILE.exists() else 0

    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    assert HEARTBEAT_FILE.stat().st_mtime_ns > before


def test_batch_claims_each_intent_only_when_it_is_ready_to_dispatch(settings) -> None:
    from engine.models import ProvisionerLaunchStatus

    first = _intent("22222222-2222-2222-2222-222222222222")
    second = _intent("33333333-3333-3333-3333-333333333333")
    observed_statuses: list[tuple[str, str]] = []
    client = MagicMock()
    _configure_aws(settings)

    def observe_claim(**_kwargs):
        first.refresh_from_db()
        second.refresh_from_db()
        observed_statuses.append((first.status, second.status))
        return {"tasks": [{"taskArn": f"arn:aws:ecs:region:account:task/job-{len(observed_statuses)}"}]}

    client.run_task.side_effect = observe_claim
    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", batch_size=2, stdout=StringIO())

    assert observed_statuses == [
        (ProvisionerLaunchStatus.RUNNING, ProvisionerLaunchStatus.PENDING),
        (ProvisionerLaunchStatus.SUCCEEDED, ProvisionerLaunchStatus.RUNNING),
    ]


def test_missing_task_runner_configuration_retries_instead_of_acknowledging(settings) -> None:
    row = _intent()
    settings.CLOUD_PROVIDER = "aws"
    settings.ENGINE_TASK_CLUSTER = ""
    settings.ENGINE_TASK_DEFINITION = ""
    settings.ENGINE_ECS_CLUSTER_ARN = ""
    settings.ENGINE_TASK_DEFINITION_ARN = ""

    call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    assert row.status == "PENDING"
    assert row.attempts == 1


def test_dlq_fails_only_the_current_range_operation(settings) -> None:
    from engine.launch_intents import PROVISIONER_DISPATCH_FAILED
    from engine.models import Range, RangeEventOutbox

    row = _intent()
    row.max_attempts = 1
    row.save(update_fields=["max_attempts"])
    _configure_aws(settings)
    client = MagicMock()
    client.run_task.side_effect = RuntimeError("provider unavailable")

    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    range_row = Range.objects.get(request__request_id="11111111-1111-1111-1111-111111111111")
    assert row.status == "DLQ"
    assert row.last_error == "RuntimeError"
    assert range_row.status == Range.Status.FAILED
    assert range_row.error_message == PROVISIONER_DISPATCH_FAILED
    assert range_row.provisioner_operation == ""
    assert range_row.provisioner_operation_id is None
    failure_event = RangeEventOutbox.objects.get()
    assert failure_event.payload["new_status"] == Range.Status.FAILED
    assert failure_event.payload["error_message"] == PROVISIONER_DISPATCH_FAILED
    assert "provider unavailable" not in str(failure_event.payload)


def test_dlq_from_stale_generation_does_not_overwrite_newer_range_state(settings) -> None:
    from engine.models import Range

    row = _intent()
    row.max_attempts = 1
    row.save(update_fields=["max_attempts"])
    range_row = Range.objects.get(request__request_id="11111111-1111-1111-1111-111111111111")
    newer_operation_id = uuid4()
    range_row.provisioner_operation_id = newer_operation_id
    range_row.save(update_fields=["provisioner_operation_id"])
    _configure_aws(settings)
    client = MagicMock()

    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    range_row.refresh_from_db()
    assert row.status == "DLQ"
    assert range_row.status == Range.Status.PROVISIONING
    assert range_row.provisioner_operation_id == newer_operation_id
    client.run_task.assert_not_called()


def test_dlq_fails_current_ngfw_instance_and_apps(settings) -> None:
    from django.contrib.auth import get_user_model

    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import App, Instance, ProvisionerLaunchIntent, Request

    request_id = uuid4()
    user = get_user_model().objects.create_user(username=f"launcher-{request_id}@example.com")
    request = Request.objects.create(request_id=request_id, request_type="ngfw", user=user)
    instance = Instance.objects.create(
        request=request,
        role=Instance.Role.NGFW,
        os_type=Instance.OSType.PANOS,
        status="provisioning",
    )
    app = App.objects.create(instance=instance, app_type=App.AppType.NGFW, status="provisioning")
    intent_id = enqueue_provisioner_launch(["ngfw", "provision", "--request-id", str(request_id)])
    row = ProvisionerLaunchIntent.objects.get(intent_id=intent_id)
    row.max_attempts = 1
    row.save(update_fields=["max_attempts"])
    _configure_aws(settings)
    client = MagicMock()
    client.run_task.side_effect = RuntimeError("provider unavailable")

    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    instance.refresh_from_db()
    app.refresh_from_db()
    assert row.status == "DLQ"
    assert instance.status == "failed"
    assert app.status == "failed"
    assert instance.provisioner_operation == ""
    assert instance.provisioner_operation_id is None


def test_reclaimed_lease_fences_stale_worker_result() -> None:
    from engine.management.commands.drain_provisioner_launch_outbox import Command
    from engine.models import ProvisionerLaunchStatus

    _intent()
    claimed = Command._claim_next()
    assert claimed is not None
    current = type(claimed).objects.get(pk=claimed.pk)
    current.status = ProvisionerLaunchStatus.SUCCEEDED
    current.next_attempt_at = current.next_attempt_at + timedelta(minutes=5)
    current.save(update_fields=["status", "next_attempt_at"])

    Command()._record_failure(claimed, RuntimeError("late failure"))

    current.refresh_from_db()
    assert current.status == ProvisionerLaunchStatus.SUCCEEDED
    assert current.attempts == 0


def test_drainer_rejects_forged_intent_without_authorized_domain_state(settings) -> None:
    row = _intent()
    from engine.models import Range

    Range.objects.filter(request__request_id=row.payload["request_id"]).update(status=Range.Status.READY)
    _configure_aws(settings)
    client = MagicMock()

    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    assert row.status == "PENDING"
    assert row.last_error == "ValueError"
    client.run_task.assert_not_called()


def test_drainer_rejects_stale_operation_generation_even_when_state_repeats(settings) -> None:
    row = _intent()
    from engine.models import Range

    range_row = Range.objects.get(request__request_id=row.payload["request_id"])
    range_row.provisioner_operation_id = uuid4()
    range_row.save(update_fields=["provisioner_operation_id"])
    _configure_aws(settings)
    client = MagicMock()

    with patch("boto3.client", return_value=client):
        call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    assert row.status == "PENDING"
    assert row.last_error == "ValueError"
    client.run_task.assert_not_called()
