"""Tests for ACES operation sidecar retention and bounded cleanup (#1277)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from django.test import override_settings
from django.utils import timezone

from shared.aces.operations import (
    AcesOperationRecordWrite,
    persist_aces_operation_record,
    prune_expired_aces_operation_records,
)
from shared.models import AcesOperationRecord
from shared.schemas.aces_operation import canonical_aces_payload_digest

REQUEST_ID = UUID("12345678-1234-5678-1234-567812345678")
SOURCE_TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


def _persist(**overrides):
    fields = {
        "request_id": overrides.pop("request_id", REQUEST_ID),
        "operation_id": "op-12345678",
        "idempotency_key": "range-provisioned:event-1",
        "record_kind": AcesOperationRecord.RecordKind.OPERATION_RECEIPT,
        "contract_version": "operation-receipt-v1",
        "source_timestamp": SOURCE_TS,
        "payload": {"operation_id": "op-12345678", "accepted": True},
        "diagnostic_refs": {"trace_ref": "traces/request-12345678"},
    }
    fields.update(overrides)
    fields.setdefault("payload_digest", canonical_aces_payload_digest(fields["payload"]))
    return persist_aces_operation_record(AcesOperationRecordWrite(**fields))


def _seed_expired(*, request_id: UUID, retention_expires_at: datetime) -> AcesOperationRecord:
    return _persist(
        request_id=request_id,
        idempotency_key=f"seed:{request_id}",
        retention_expires_at=retention_expires_at,
    )


@override_settings(ACES_OPERATION_RECORD_RETENTION_DAYS=30)
@pytest.mark.django_db
def test_persist_sets_retention_from_settings_when_unset():
    row = _persist()

    assert row.retention_expires_at == SOURCE_TS + timedelta(days=30)


@override_settings(ACES_OPERATION_RECORD_RETENTION_DAYS=30)
@pytest.mark.django_db
def test_persist_preserves_explicit_retention_over_settings_default():
    explicit = SOURCE_TS + timedelta(days=3)
    row = _persist(retention_expires_at=explicit)

    assert row.retention_expires_at == explicit


@override_settings(ACES_OPERATION_RECORD_RETENTION_DAYS=0)
@pytest.mark.django_db
def test_persist_disables_retention_when_days_not_positive():
    row = _persist()

    assert row.retention_expires_at is None


@override_settings(ACES_OPERATION_RECORD_RETENTION_DAYS=30)
@pytest.mark.django_db
def test_persist_retention_is_deterministic_on_replay():
    first = _persist()
    second = _persist()

    assert first.id == second.id
    assert second.retention_expires_at == SOURCE_TS + timedelta(days=30)
    assert AcesOperationRecord.objects.count() == 1


@pytest.mark.django_db
def test_prune_deletes_expired_rows_and_retains_unexpired():
    now = timezone.now()
    expired = _seed_expired(request_id=uuid4(), retention_expires_at=now - timedelta(days=1))
    unexpired = _seed_expired(request_id=uuid4(), retention_expires_at=now + timedelta(days=1))

    deleted = prune_expired_aces_operation_records(batch_size=100)

    assert deleted == 1
    assert not AcesOperationRecord.objects.filter(pk=expired.pk).exists()
    assert AcesOperationRecord.objects.filter(pk=unexpired.pk).exists()


@pytest.mark.django_db
def test_prune_ignores_rows_without_retention_boundary():
    kept = _persist(retention_expires_at=None)

    deleted = prune_expired_aces_operation_records(batch_size=100)

    assert deleted == 0
    assert AcesOperationRecord.objects.filter(pk=kept.pk).exists()


@pytest.mark.django_db
def test_prune_respects_bounded_batch_size():
    now = timezone.now()
    for _ in range(3):
        _seed_expired(request_id=uuid4(), retention_expires_at=now - timedelta(days=1))

    deleted = prune_expired_aces_operation_records(batch_size=2)

    assert deleted == 2
    assert AcesOperationRecord.objects.count() == 1


@pytest.mark.django_db
def test_prune_returns_zero_when_nothing_expired():
    assert prune_expired_aces_operation_records(batch_size=50) == 0
