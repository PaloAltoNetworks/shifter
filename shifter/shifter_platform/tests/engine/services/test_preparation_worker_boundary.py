"""Opaque preparation IDs do not confer input, result or admission authority."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from engine.models import PreparationAttempt, PreparationOperation
from engine.services import (
    cancel_artifact_preparation,
    read_preparation_worker_input,
    record_preparation_worker_result,
    request_artifact_preparation,
)
from engine.services._preparation_worker import attempt_token
from shared.exceptions import ValidationError
from tests.engine.services.test_preparation_operations import administrator, grant, installed, operator, package_input

pytestmark = pytest.mark.django_db
__all__ = ["administrator", "grant", "installed", "operator"]


@pytest.fixture
def attempt(operator, installed):
    operation = request_artifact_preparation(operator, installed.id, package_input())
    return PreparationAttempt.objects.get(operation_id=operation.id)


def result_for(attempt):
    return {
        "protocol": "shifter.artifact-preparation/v1",
        "attempt_id": str(attempt.id),
        "operation_id": str(attempt.operation_id),
        "input_digest": attempt.input_digest,
        "phase": attempt.phase,
        "status": "failed",
        "failure_code": "input-verification-failed",
        "evidence": {},
    }


def test_correct_attempt_can_read_only_its_immutable_input(attempt):
    envelope = read_preparation_worker_input(attempt.operation_id, attempt_token(attempt))
    assert envelope["input_digest"] == attempt.input_digest
    assert envelope["input"] == attempt.input
    assert envelope["input"]["package"]["package_digest"] == package_input()["package_digest"]
    with pytest.raises(ValidationError):
        read_preparation_worker_input(uuid4(), attempt_token(attempt))
    with pytest.raises(ValidationError):
        read_preparation_worker_input(attempt.operation_id, str(attempt.id))


def test_expired_attempt_cannot_read_or_submit(attempt):
    attempt.expires_at = timezone.now() - timedelta(seconds=1)
    attempt.save()
    token = attempt_token(attempt)
    with pytest.raises(ValidationError):
        read_preparation_worker_input(attempt.operation_id, token)
    with pytest.raises(ValidationError):
        record_preparation_worker_result(attempt.operation_id, token, result_for(attempt))
    assert PreparationAttempt.objects.get(pk=attempt.id).result is None


def test_cancellation_revokes_worker_input_and_result_authority(attempt, operator):
    token = attempt_token(attempt)
    cancel_artifact_preparation(operator, attempt.operation_id)
    with pytest.raises(ValidationError):
        read_preparation_worker_input(attempt.operation_id, token)
    with pytest.raises(ValidationError):
        record_preparation_worker_result(attempt.operation_id, token, result_for(attempt))
    assert PreparationOperation.objects.get(pk=attempt.operation_id).state == "cancelled"


def test_result_is_an_inbox_receipt_and_does_not_admit_inventory(attempt):
    token = attempt_token(attempt)
    result = result_for(attempt)
    assert record_preparation_worker_result(attempt.operation_id, token, result) == "received"
    assert record_preparation_worker_result(attempt.operation_id, token, result) == "received"
    row = PreparationAttempt.objects.get(pk=attempt.id)
    assert row.result == result
    assert PreparationOperation.objects.get(pk=attempt.operation_id).state == "queued"


def test_conflicting_result_cannot_replace_first_receipt(attempt):
    token = attempt_token(attempt)
    original = result_for(attempt)
    record_preparation_worker_result(attempt.operation_id, token, original)
    conflict = result_for(attempt)
    conflict["failure_code"] = "execution-failed"
    with pytest.raises(ValidationError):
        record_preparation_worker_result(attempt.operation_id, token, conflict)
    assert PreparationAttempt.objects.get(pk=attempt.id).result == original


@pytest.mark.parametrize("field,value", [("phase", "verify-output"), ("input_digest", "sha256:" + "f" * 64)])
def test_worker_cannot_change_its_role_or_immutable_input(attempt, field, value):
    result = result_for(attempt)
    result[field] = value
    with pytest.raises(ValidationError):
        record_preparation_worker_result(attempt.operation_id, attempt_token(attempt), result)
    assert PreparationAttempt.objects.get(pk=attempt.id).result is None


def test_worker_cannot_inject_arbitrary_error_payload(attempt):
    result = result_for(attempt)
    result["failure_code"] = "private registry credential: do not emit"
    with pytest.raises(ValidationError):
        record_preparation_worker_result(attempt.operation_id, attempt_token(attempt), result)
    assert PreparationAttempt.objects.get(pk=attempt.id).result is None


def test_revoked_requester_cannot_continue_private_execution(attempt, operator):
    operator.user_permissions.clear()
    with pytest.raises(ValidationError):
        read_preparation_worker_input(attempt.operation_id, attempt_token(attempt))


def test_mutated_grant_cannot_extend_existing_worker_authority(attempt, grant):
    grant.configuration["max_duration_seconds"] = 7200
    grant.save()
    with pytest.raises(ValidationError):
        read_preparation_worker_input(attempt.operation_id, attempt_token(attempt))


def test_cleanup_survives_revocation_but_cannot_change_its_pinned_cloud_scope(attempt, grant, operator):
    from engine.services._preparation_operations import new_preparation_attempt

    cancel_artifact_preparation(operator, attempt.operation_id)
    row = PreparationOperation.objects.get(pk=attempt.operation_id)
    cleanup = new_preparation_attempt(row, "cleanup", evidence={"attempts": [str(attempt.id)]})
    grant.active = False
    grant.save(update_fields=["active"])
    operator.user_permissions.clear()
    token = attempt_token(cleanup)
    assert read_preparation_worker_input(row.id, token)["input"]["grant"]["project_id"] == "test-project"
    changed = cleanup.input
    changed["grant"]["project_id"] = "foreign-project"
    PreparationAttempt.objects.filter(pk=cleanup.id).update(input=changed)
    with pytest.raises(ValidationError):
        read_preparation_worker_input(row.id, token)
