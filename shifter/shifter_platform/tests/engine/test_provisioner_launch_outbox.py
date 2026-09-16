"""Tests for the dedicated provisioner launcher outbox worker.

Since #1826 the provisioner dispatches as a Kubernetes Job on both AWS (EKS) and
GCP (GKE). Per ADR-019-R1 these tests mock the real cloud boundary (the runner's
Kubernetes API loader) via ``monkeypatch.setattr`` rather than patching the
first-party ``get_task_runner`` factory, mirroring how the runner adapter tests
inject a fake ``kubernetes.client``. The drainer behavior under test (canonical
argv, idempotent task identity, retry/DLQ, fencing) is provider-neutral.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from shared.cloud.kubernetes._runner import KubernetesTaskRunner

# Opaque #1325 workspace scope binding (ADR-046-R3). These suites do not
# exercise tenancy; a fixed scalar stands in for the value the CMS launch
# facade resolves in production.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db(databases=["default"])

_JOBS_NAMESPACE = "shifter-jobs"


class _ApiException(Exception):
    def __init__(self, status: int):
        super().__init__(f"status={status}")
        self.status = status


def _make_fake_k8s_client() -> SimpleNamespace:
    """A SimpleNamespace stand-in for kubernetes.client, mirroring the adapter tests."""
    return SimpleNamespace(
        V1EnvVar=lambda **kwargs: SimpleNamespace(**kwargs),
        V1EnvVarSource=lambda **kwargs: SimpleNamespace(**kwargs),
        V1SecretKeySelector=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Secret=lambda **kwargs: SimpleNamespace(**kwargs),
        V1OwnerReference=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Container=lambda **kwargs: SimpleNamespace(**kwargs),
        V1PodSpec=lambda **kwargs: SimpleNamespace(**kwargs),
        V1ObjectMeta=lambda **kwargs: SimpleNamespace(**kwargs),
        V1PodTemplateSpec=lambda **kwargs: SimpleNamespace(**kwargs),
        V1JobSpec=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Job=lambda **kwargs: SimpleNamespace(**kwargs),
        V1SecurityContext=lambda **kwargs: SimpleNamespace(**kwargs),
        V1PodSecurityContext=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Capabilities=lambda **kwargs: SimpleNamespace(**kwargs),
        V1SeccompProfile=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Volume=lambda **kwargs: SimpleNamespace(**kwargs),
        V1VolumeMount=lambda **kwargs: SimpleNamespace(**kwargs),
        V1EmptyDirVolumeSource=lambda **kwargs: SimpleNamespace(**kwargs),
    )


@pytest.fixture
def k8s_boundary(monkeypatch):
    """Install a fake Kubernetes API on the neutral runner's cloud boundary.

    ``read_namespaced_job`` reports the idempotent Job as absent (404) so the
    create path runs; tests set ``create_namespaced_job``'s return/side effect.
    Monkeypatching the loader method (not a ``patch()`` of a first-party seam)
    keeps this an ADR-019 boundary mock.
    """
    batch_api = MagicMock()
    batch_api.read_namespaced_job.side_effect = _ApiException(404)
    core_api = MagicMock()
    client = _make_fake_k8s_client()
    monkeypatch.setattr(
        KubernetesTaskRunner,
        "_load_kubernetes_api",
        lambda _self: (batch_api, core_api, client, _ApiException),
    )
    return SimpleNamespace(batch_api=batch_api, core_api=core_api)


def _job(name: str) -> SimpleNamespace:
    return SimpleNamespace(metadata=SimpleNamespace(name=name))


def _launched_command(k8s_boundary) -> list[str]:
    body = k8s_boundary.batch_api.create_namespaced_job.call_args.kwargs["body"]
    return body.spec.template.spec.containers[0].args


def _intent(request_id: str = "11111111-1111-1111-1111-111111111111"):
    from django.contrib.auth import get_user_model

    from engine.launch_intents import enqueue_provisioner_launch
    from engine.models import ProvisionerLaunchIntent, Range, Request

    user = get_user_model().objects.create_user(username=f"launcher-{request_id}@example.com")
    request = Request.objects.create(request_id=request_id, request_type="range", user=user)
    Range.objects.create(workspace_id=_WORKSPACE_ID, request=request, user=user, status=Range.Status.PROVISIONING)

    ref = enqueue_provisioner_launch(["range", "provision", "--request-id", request_id])
    return ProvisionerLaunchIntent.objects.get(intent_id=ref)


def _configure_aws(settings) -> None:
    """Configure AWS for Kubernetes-Job provisioner dispatch (#1826)."""
    settings.CLOUD_PROVIDER = "aws"
    settings.ENGINE_TASK_CLUSTER = _JOBS_NAMESPACE
    settings.ENGINE_TASK_DEFINITION = "task-image"
    settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "provisioner"
    settings.ENGINE_ECS_CLUSTER_ARN = ""
    settings.ENGINE_TASK_DEFINITION_ARN = ""


def test_drainer_launches_canonical_command_and_marks_succeeded(settings, k8s_boundary) -> None:
    row = _intent()
    _configure_aws(settings)
    k8s_boundary.batch_api.create_namespaced_job.return_value = _job("pulumi-provisioner-job-1")

    call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    # The launched argv carries the canonical operation_id so the provisioner
    # tags its input read / result appends with exactly this operation (ADR-043).
    assert _launched_command(k8s_boundary) == [
        "range",
        "provision",
        "--request-id",
        "11111111-1111-1111-1111-111111111111",
        "--operation-id",
        str(row.operation_id),
    ]
    assert row.status == "SUCCEEDED"
    assert row.task_ref == f"{_JOBS_NAMESPACE}/pulumi-provisioner-job-1"


def test_drainer_retries_failure_without_leaking_error_details(settings, k8s_boundary) -> None:
    row = _intent()
    before = timezone.now()
    _configure_aws(settings)
    k8s_boundary.batch_api.create_namespaced_job.side_effect = RuntimeError("token=super-secret")

    call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    assert row.status == "PENDING"
    assert row.attempts == 1
    # Only the exception type is recorded, never the (potentially secret) message.
    assert "super-secret" not in (row.last_error or "")
    assert " " not in (row.last_error or "x")
    assert row.next_attempt_at >= before + timedelta(seconds=55)


def test_succeeded_intent_is_not_launched_twice(settings, k8s_boundary) -> None:
    """A settled intent is skipped and left exactly as it was."""
    row = _intent()
    row.status = "SUCCEEDED"
    row.save(update_fields=["status"])
    expected_status, expected_attempts, expected_task_ref = row.status, row.attempts, row.task_ref
    _configure_aws(settings)

    call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    k8s_boundary.batch_api.create_namespaced_job.assert_not_called()
    row.refresh_from_db()
    assert row.status == expected_status
    assert row.attempts == expected_attempts
    assert row.task_ref == expected_task_ref


def test_expired_running_claim_recovers_with_same_task_identity(settings, k8s_boundary) -> None:
    row = _intent()
    row.status = "RUNNING"
    row.next_attempt_at = timezone.now() - timedelta(seconds=1)
    row.save(update_fields=["status", "next_attempt_at"])
    _configure_aws(settings)
    k8s_boundary.batch_api.create_namespaced_job.return_value = _job("pulumi-provisioner-job-stable")

    call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    assert row.status == "SUCCEEDED"
    assert row.task_ref == f"{_JOBS_NAMESPACE}/pulumi-provisioner-job-stable"
    # The idempotent Job identity is the intent id, so a redelivered claim
    # reconciles the same Job rather than creating a duplicate.
    body = k8s_boundary.batch_api.create_namespaced_job.call_args.kwargs["body"]
    assert body.metadata.annotations["shifter.dev/task-identity"] == str(row.intent_id)


def test_drainer_refreshes_observable_heartbeat_during_launch(settings, k8s_boundary) -> None:
    from engine.management.commands.drain_provisioner_launch_outbox import HEARTBEAT_FILE

    _intent()
    _configure_aws(settings)
    k8s_boundary.batch_api.create_namespaced_job.return_value = _job("pulumi-provisioner-job-1")
    before = HEARTBEAT_FILE.stat().st_mtime_ns if HEARTBEAT_FILE.exists() else 0

    call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    assert HEARTBEAT_FILE.stat().st_mtime_ns > before


def test_batch_claims_each_intent_only_when_it_is_ready_to_dispatch(settings, k8s_boundary) -> None:
    from engine.models import ProvisionerLaunchStatus

    first = _intent("22222222-2222-2222-2222-222222222222")
    second = _intent("33333333-3333-3333-3333-333333333333")
    observed_statuses: list[tuple[str, str]] = []
    _configure_aws(settings)

    def observe_claim(**_kwargs):
        first.refresh_from_db()
        second.refresh_from_db()
        observed_statuses.append((first.status, second.status))
        return _job(f"pulumi-provisioner-job-{len(observed_statuses)}")

    k8s_boundary.batch_api.create_namespaced_job.side_effect = observe_claim
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


def test_dlq_fails_only_the_current_range_operation(settings, k8s_boundary) -> None:
    from engine.launch_intents import PROVISIONER_DISPATCH_FAILED
    from engine.models import Range, RangeEventOutbox

    row = _intent()
    row.max_attempts = 1
    row.save(update_fields=["max_attempts"])
    _configure_aws(settings)
    k8s_boundary.batch_api.create_namespaced_job.side_effect = RuntimeError("provider unavailable")

    call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    range_row = Range.objects.get(request__request_id="11111111-1111-1111-1111-111111111111")
    assert row.status == "DLQ"
    assert range_row.status == Range.Status.FAILED
    assert range_row.error_message == PROVISIONER_DISPATCH_FAILED
    assert range_row.provisioner_operation == ""
    assert range_row.provisioner_operation_id is None
    failure_event = RangeEventOutbox.objects.get()
    assert failure_event.payload["new_status"] == Range.Status.FAILED
    assert failure_event.payload["error_message"] == PROVISIONER_DISPATCH_FAILED
    assert "provider unavailable" not in str(failure_event.payload)


def test_dlq_from_stale_generation_does_not_overwrite_newer_range_state(settings, k8s_boundary) -> None:
    from engine.models import Range

    row = _intent()
    row.max_attempts = 1
    row.save(update_fields=["max_attempts"])
    range_row = Range.objects.get(request__request_id="11111111-1111-1111-1111-111111111111")
    newer_operation_id = uuid4()
    range_row.provisioner_operation_id = newer_operation_id
    range_row.save(update_fields=["provisioner_operation_id"])
    _configure_aws(settings)

    call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    range_row.refresh_from_db()
    assert row.status == "DLQ"
    assert range_row.status == Range.Status.PROVISIONING
    assert range_row.provisioner_operation_id == newer_operation_id
    k8s_boundary.batch_api.create_namespaced_job.assert_not_called()


def test_dlq_fails_current_ngfw_instance_and_apps(settings, k8s_boundary) -> None:
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
    k8s_boundary.batch_api.create_namespaced_job.side_effect = RuntimeError("provider unavailable")

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


def test_drainer_rejects_forged_intent_without_authorized_domain_state(settings, k8s_boundary) -> None:
    row = _intent()
    from engine.models import Range

    Range.objects.filter(request__request_id=row.payload["request_id"]).update(status=Range.Status.READY)
    _configure_aws(settings)

    call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    assert row.status == "PENDING"
    assert row.last_error == "ValueError"
    k8s_boundary.batch_api.create_namespaced_job.assert_not_called()


def test_drainer_rejects_stale_operation_generation_even_when_state_repeats(settings, k8s_boundary) -> None:
    row = _intent()
    from engine.models import Range

    range_row = Range.objects.get(request__request_id=row.payload["request_id"])
    range_row.provisioner_operation_id = uuid4()
    range_row.save(update_fields=["provisioner_operation_id"])
    _configure_aws(settings)

    call_command("drain_provisioner_launch_outbox", stdout=StringIO())

    row.refresh_from_db()
    assert row.status == "PENDING"
    assert row.last_error == "ValueError"
    k8s_boundary.batch_api.create_namespaced_job.assert_not_called()
