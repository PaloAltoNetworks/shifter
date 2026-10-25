"""Durable preparation progresses only through quiesced, verified and fenced work."""

from datetime import timedelta

import pytest
from django.utils import timezone

from engine.models import PreparationAttempt, PreparationOperation
from engine.services import cancel_artifact_preparation, request_artifact_preparation
from engine.services._preparation_worker import attempt_token, record_preparation_worker_result
from shared.cloud.types import TaskInterruptDisposition
from tests.engine.services.test_preparation_operations import administrator, grant, installed, operator, package_input
from tests.shared.raes.test_prepared_artifacts import admission_arguments

pytestmark = pytest.mark.django_db
__all__ = ["administrator", "grant", "installed", "operator"]


class Task:
    def __init__(self):
        self.dispatched = []
        self.stopped = []
        self.interruption = TaskInterruptDisposition.TERMINAL_ABSENT
        self.state = "RUNNING"
        self.hook = lambda: None

    def dispatch(self, token):
        self.dispatched.append(token)
        self.hook()
        return "test-job"

    def interrupt(self):
        self.stopped.append(True)
        self.hook()
        return self.interruption

    def status(self):
        return self.state


class Observer:
    def __init__(self):
        self.reads = []
        self.reject = False

    def __getattr__(self, name):
        def verify(*args, **kwargs):
            self.reads.append(name)
            if self.reject:
                raise ValueError("changed provider identity")

        return verify


@pytest.fixture
def runtime(monkeypatch):
    from engine.services import _preparation_controller as controller

    task, observer = Task(), Observer()
    monkeypatch.setattr(controller, "get_preparation_task", lambda *args: task)
    monkeypatch.setattr(controller, "get_preparation_readback", lambda *args: observer)
    return controller, task, observer


@pytest.fixture(autouse=True)
def deployment_scope(settings):
    """Keep setup audit evidence and inventory ownership in one deployment."""
    settings.GCP_PROJECT_ID = "test-project"


def receipt(operation_id, evidence=None, *, failed=False):
    operation = PreparationOperation.objects.get(pk=operation_id)
    attempt = PreparationAttempt.objects.get(pk=operation.current_attempt_id)
    record_preparation_worker_result(
        operation.id,
        attempt_token(attempt),
        {
            "protocol": "shifter.artifact-preparation/v1",
            "operation_id": str(operation.id),
            "attempt_id": str(attempt.id),
            "input_digest": attempt.input_digest,
            "phase": attempt.phase,
            "status": "failed" if failed else "succeeded",
            "failure_code": "execution-failed" if failed else "",
            "evidence": evidence or {},
        },
    )
    return attempt


def test_dispatch_is_durable_idempotent_and_does_not_admit_inventory(operator, installed, runtime):
    controller, task, observer = runtime
    operation = request_artifact_preparation(operator, installed.id, package_input())
    controller.reconcile_preparation(operation.id)
    controller.reconcile_preparation(operation.id)
    row = PreparationOperation.objects.get(pk=operation.id)
    attempt = PreparationAttempt.objects.get(pk=row.current_attempt_id)
    assert row.state == "running"
    assert attempt.dispatched_at and attempt.dispatch_count == 1
    assert len(task.dispatched) == 1
    assert not observer.reads


def test_verified_phases_atomically_admit_output_then_cleanup_retains_image(operator, installed, runtime):
    from engine.models import PreparedArtifactAdmission, RaesImageMapping

    controller, task, observer = runtime
    operation = request_artifact_preparation(operator, installed.id, package_input())
    evidence = admission_arguments()
    for phase, key in (("verify-inputs", "inputs"), ("build", "build"), ("verify-output", "output")):
        attempt = receipt(operation.id, evidence[key])
        assert attempt.phase == phase
        controller.reconcile_preparation(operation.id)
    row = PreparationOperation.objects.get(pk=operation.id)
    assert row.state == "available" and row.cleanup_pending
    admission = PreparedArtifactAdmission.objects.get(operation=row)
    assert admission.image_mapping.artifact_digest == evidence["output"]["raw_disk_digest"]
    assert admission.facts["image_id"] == "555"
    assert RaesImageMapping.objects.count() == 1
    controller.reconcile_preparation(operation.id)
    cleanup = PreparationAttempt.objects.get(pk=PreparationOperation.objects.get(pk=row.pk).current_attempt_id)
    assert cleanup.phase == "cleanup"
    assert cleanup.input["evidence"]["retained_image"]["image_id"] == "555"
    receipt(operation.id, {"resources_remaining": []})
    controller.reconcile_preparation(operation.id)
    row.refresh_from_db()
    assert row.state == "available" and not row.cleanup_pending
    assert "verify_cleanup" in observer.reads
    assert len(task.stopped) >= 4


def test_result_does_not_advance_until_worker_pods_are_absent(operator, installed, runtime):
    controller, task, observer = runtime
    operation = request_artifact_preparation(operator, installed.id, package_input())
    previous = receipt(operation.id, admission_arguments()["inputs"])
    task.interruption = TaskInterruptDisposition.STOPPING
    controller.reconcile_preparation(operation.id)
    assert PreparationOperation.objects.get(pk=operation.id).current_attempt_id == previous.pk
    assert not observer.reads


@pytest.mark.parametrize("failure", ["provider", "cancel-race", "revoked", "expired", "worker"])
def test_failed_or_stale_work_never_reaches_inventory_and_keeps_cleanup(operator, installed, grant, runtime, failure):
    from engine.models import PreparedArtifactAdmission

    controller, task, observer = runtime
    operation = request_artifact_preparation(operator, installed.id, package_input())
    if failure == "expired":
        PreparationAttempt.objects.filter(operation_id=operation.id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
    elif failure == "revoked":
        grant.active = False
        grant.save(update_fields=["active"])
    else:
        receipt(
            operation.id, None if failure == "worker" else admission_arguments()["inputs"], failed=failure == "worker"
        )
        if failure == "provider":
            observer.reject = True
        elif failure == "cancel-race":
            task.hook = lambda: cancel_artifact_preparation(operator, operation.id)
    controller.reconcile_preparation(operation.id)
    row = PreparationOperation.objects.get(pk=operation.id)
    assert row.state in {"failed", "cancelled"} and row.cleanup_pending
    assert not PreparedArtifactAdmission.objects.exists()
    if failure == "worker":
        assert row.failure_code == "execution-failed"
        assert not observer.reads
    elif failure == "provider":
        assert row.failure_code == "verification-failed"


def test_cancellation_cleanup_survives_grant_revocation(operator, installed, grant, runtime):
    controller, task, _observer = runtime
    operation = request_artifact_preparation(operator, installed.id, package_input())
    cancel_artifact_preparation(operator, operation.id)
    grant.active = False
    grant.save(update_fields=["active"])
    controller.reconcile_preparation(operation.id)
    current = PreparationAttempt.objects.get(pk=PreparationOperation.objects.get(pk=operation.id).current_attempt_id)
    assert current.phase == "cleanup" and task.stopped
    receipt(operation.id, {"resources_remaining": []})
    controller.reconcile_preparation(operation.id)
    row = PreparationOperation.objects.get(pk=operation.id)
    assert row.state == "cancelled" and not row.cleanup_pending


def test_failed_cleanup_retries_without_releasing_capacity(operator, installed, runtime):
    controller, _, _ = runtime
    operation = request_artifact_preparation(operator, installed.id, package_input())
    cancel_artifact_preparation(operator, operation.id)
    controller.reconcile_preparation(operation.id)
    previous = receipt(operation.id, failed=True)
    controller.reconcile_preparation(operation.id)
    row = PreparationOperation.objects.get(pk=operation.id)
    assert row.cleanup_pending and row.current_attempt_id != previous.id
    assert PreparationAttempt.objects.get(pk=row.current_attempt_id).phase == "cleanup"


def test_prepared_inventory_projection_rejects_mapping_drift(operator, installed, runtime):
    from engine.models import PreparedArtifactAdmission
    from engine.services import list_backend_artifacts

    controller, _, _ = runtime
    operation = request_artifact_preparation(operator, installed.id, package_input())
    evidence = admission_arguments()
    for key in ("inputs", "build", "output"):
        receipt(operation.id, evidence[key])
        controller.reconcile_preparation(operation.id)
    supplied = list_backend_artifacts(provider="gce")
    assert supplied[0].image_id == "555"
    assert supplied[0].materialization.operation_id == operation.id
    admission = PreparedArtifactAdmission.objects.get(operation_id=operation.id)
    mapping = admission.image_mapping
    mapping.image_ref = "projects/test-project/global/images/changed"
    mapping.save(update_fields=["image_ref"])
    assert list_backend_artifacts(provider="gce") == []


def test_terminal_job_without_a_receipt_is_failed_and_cleaned(operator, installed, runtime):
    controller, task, _ = runtime
    operation = request_artifact_preparation(operator, installed.id, package_input())
    controller.reconcile_preparation(operation.id)
    task.state = "FAILED"
    controller.reconcile_preparation(operation.id)
    row = PreparationOperation.objects.get(pk=operation.id)
    assert row.state == "failed" and row.cleanup_pending
    assert task.stopped
