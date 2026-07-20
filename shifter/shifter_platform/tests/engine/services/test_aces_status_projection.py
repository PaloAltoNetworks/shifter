"""Behavior tests for ACES operation-status projection (engine.services, #1274)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from engine.models import OutboxStatus, Range, RangeEventOutbox, Request
from engine.services import project_aces_operation_status
from shared.aces.status import AcesOperationStatusObservation, ProjectionDecision, RangeOperation
from shared.enums import ResourceStatus
from shared.messages.events import EVENT_TYPE_STATUS_UPDATED
from shared.models import AcesOperationRecord

TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)

# The full envelope of keys a range.status.updated event may carry. The event
# must never grow snapshot/secret/provider keys beyond these.
ALLOWED_EVENT_KEYS = {
    "event_type",
    "event_id",
    "timestamp",
    "request_id",
    "range_id",
    "user_id",
    "new_status",
    "error_message",
}


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="aces-proj@example.com", email="aces-proj@example.com")


def _make_range(user, *, status=Range.Status.PROVISIONING):
    request_id = uuid4()
    request = Request.objects.create(request_id=request_id, request_type="range", user=user)
    range_obj = Range.objects.create(user=user, request=request, status=status)
    return request_id, range_obj


def _project(**kwargs):
    """Build an observation from kwargs and run the projection."""
    return project_aces_operation_status(AcesOperationStatusObservation(**kwargs))


def _status_records(request_id):
    return AcesOperationRecord.objects.filter(
        request_id=request_id,
        record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
    )


@pytest.mark.django_db
def test_apply_persists_sidecar_and_enqueues_status_event(user):
    request_id, range_obj = _make_range(user, status=Range.Status.PROVISIONING)

    result = _project(
        request_id=request_id,
        operation_id="op-1",
        intent=RangeOperation.PROVISION,
        operation_state="succeeded",
        source_timestamp=TS,
    )

    assert result.decision is ProjectionDecision.APPLY
    assert result.target_status is ResourceStatus.READY

    # Observation persisted to the #1273 sidecar.
    assert _status_records(request_id).count() == 1

    # One standard range.status.updated event enqueued, notification-shaped.
    outbox = RangeEventOutbox.objects.get()
    assert outbox.event_type == EVENT_TYPE_STATUS_UPDATED
    assert outbox.status == OutboxStatus.PENDING
    assert set(outbox.payload) <= ALLOWED_EVENT_KEYS
    assert outbox.payload["new_status"] == ResourceStatus.READY.value
    assert outbox.payload["range_id"] == range_obj.id
    assert outbox.payload["user_id"] == user.id
    assert outbox.payload["request_id"] == str(request_id)


@pytest.mark.django_db
def test_duplicate_observation_does_not_enqueue_twice(user):
    request_id, _ = _make_range(user, status=Range.Status.PROVISIONING)
    kwargs = {
        "request_id": request_id,
        "operation_id": "op-1",
        "intent": RangeOperation.PROVISION,
        "operation_state": "succeeded",
        "source_timestamp": TS,
    }

    first = _project(**kwargs)
    second = _project(**kwargs)

    assert first.decision is ProjectionDecision.APPLY
    assert second.decision is ProjectionDecision.DUPLICATE
    assert _status_records(request_id).count() == 1  # idempotent sidecar write
    assert RangeEventOutbox.objects.count() == 1  # no duplicate event


@pytest.mark.django_db
def test_stale_observation_persists_sidecar_without_event(user):
    request_id, _ = _make_range(user, status=Range.Status.PROVISIONING)

    _project(
        request_id=request_id,
        operation_id="op-2",
        intent=RangeOperation.PROVISION,
        operation_state="succeeded",
        source_timestamp=TS,
    )
    stale = _project(
        request_id=request_id,
        operation_id="op-1",
        intent=RangeOperation.PROVISION,
        operation_state="running",
        source_timestamp=TS - timedelta(minutes=5),
    )

    assert stale.decision is ProjectionDecision.STALE
    assert _status_records(request_id).count() == 2  # both observations recorded
    assert RangeEventOutbox.objects.count() == 1  # only the fresh one enqueued


@pytest.mark.django_db
def test_unmappable_state_records_sidecar_without_event(user):
    request_id, _ = _make_range(user, status=Range.Status.PROVISIONING)

    result = _project(
        request_id=request_id,
        operation_id="op-1",
        intent=RangeOperation.PROVISION,
        operation_state="bogus-state",
        source_timestamp=TS,
    )

    assert result.decision is ProjectionDecision.UNMAPPABLE
    assert _status_records(request_id).count() == 1
    assert RangeEventOutbox.objects.count() == 0


@pytest.mark.django_db
def test_no_event_when_target_equals_current_status(user):
    request_id, _ = _make_range(user, status=Range.Status.PROVISIONING)

    result = _project(
        request_id=request_id,
        operation_id="op-1",
        intent=RangeOperation.PROVISION,
        operation_state="running",  # -> PROVISIONING, already current
        source_timestamp=TS,
    )

    assert result.decision is ProjectionDecision.APPLY
    assert result.target_status is ResourceStatus.PROVISIONING
    assert _status_records(request_id).count() == 1
    assert RangeEventOutbox.objects.count() == 0  # redundant transition suppressed


@pytest.mark.django_db
def test_unknown_range_records_sidecar_without_event(user):
    request_id = uuid4()  # no Range/Request for this id

    result = _project(
        request_id=request_id,
        operation_id="op-1",
        intent=RangeOperation.PROVISION,
        operation_state="succeeded",
        source_timestamp=TS,
    )

    assert result.decision is ProjectionDecision.APPLY
    assert _status_records(request_id).count() == 1
    assert RangeEventOutbox.objects.count() == 0


@pytest.mark.django_db
def test_failed_status_sets_bounded_error_message(user):
    request_id, _ = _make_range(user, status=Range.Status.PROVISIONING)

    _project(
        request_id=request_id,
        operation_id="op-1",
        intent=RangeOperation.PROVISION,
        operation_state="failed",
        source_timestamp=TS,
        status_reason="provision operation failed",
    )

    outbox = RangeEventOutbox.objects.get()
    assert outbox.payload["new_status"] == ResourceStatus.FAILED.value
    assert outbox.payload["error_message"] == "provision operation failed"


@pytest.mark.django_db
def test_long_status_reason_is_bounded_in_event_and_sidecar(user):
    from shared.aces.status import MAX_DIAGNOSTIC_TEXT_LEN

    request_id, _ = _make_range(user, status=Range.Status.PROVISIONING)
    reason = "boom\n" + "x" * 500  # unbounded, multi-line caller text

    _project(
        request_id=request_id,
        operation_id="op-1",
        intent=RangeOperation.PROVISION,
        operation_state="failed",
        source_timestamp=TS,
        status_reason=reason,
    )

    outbox = RangeEventOutbox.objects.get()
    assert "\n" not in outbox.payload["error_message"]
    assert len(outbox.payload["error_message"]) <= MAX_DIAGNOSTIC_TEXT_LEN

    record = _status_records(request_id).get()
    assert len(record.payload["status_reason"]) <= MAX_DIAGNOSTIC_TEXT_LEN


@pytest.mark.django_db
def test_destroy_success_projects_destroyed(user):
    request_id, _ = _make_range(user, status=Range.Status.DESTROYING)

    result = _project(
        request_id=request_id,
        operation_id="op-1",
        intent=RangeOperation.DESTROY,
        operation_state="succeeded",
        source_timestamp=TS,
    )

    assert result.target_status is ResourceStatus.DESTROYED
    outbox = RangeEventOutbox.objects.get()
    assert outbox.payload["new_status"] == ResourceStatus.DESTROYED.value


@pytest.mark.django_db
def test_sanitized_diagnostic_ref_stored_on_sidecar_not_event(user):
    request_id, _ = _make_range(user, status=Range.Status.PROVISIONING)

    _project(
        request_id=request_id,
        operation_id="op-1",
        intent=RangeOperation.PROVISION,
        operation_state="failed",
        source_timestamp=TS,
        status_reason="terraform apply failed",
        diagnostic_refs={"error_class": "TerraformError", "aws_secret_access_key": "AKIAEXAMPLE"},
    )

    record = _status_records(request_id).get()
    # Only allow-listed diagnostic keys survive; the secret is dropped.
    assert "aws_secret_access_key" not in record.diagnostic_refs
    assert record.diagnostic_refs.get("error_class") == "TerraformError"
    # Event carries no diagnostic blob.
    outbox = RangeEventOutbox.objects.get()
    assert set(outbox.payload) <= ALLOWED_EVENT_KEYS
