"""Tests for RAES operation sidecar retention and bounded cleanup (#1277)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from django.test import override_settings
from django.utils import timezone

from shared.models import RaesOperationRecord
from shared.raes.operations import (
    RaesOperationRecordWrite,
    persist_raes_operation_record,
    prune_expired_raes_operation_records,
)
from shared.schemas.raes_operation import canonical_raes_payload_digest

REQUEST_ID = UUID("12345678-1234-5678-1234-567812345678")
SOURCE_TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


def _persist(**overrides):
    fields = {
        "request_id": overrides.pop("request_id", REQUEST_ID),
        "operation_id": "op-12345678",
        "idempotency_key": "range-provisioned:event-1",
        "record_kind": RaesOperationRecord.RecordKind.OPERATION_RECEIPT,
        "contract_version": "operation-receipt-v1",
        "source_timestamp": SOURCE_TS,
        "payload": {"operation_id": "op-12345678", "accepted": True},
        "diagnostic_refs": {"trace_ref": "traces/request-12345678"},
    }
    fields.update(overrides)
    fields.setdefault("payload_digest", canonical_raes_payload_digest(fields["payload"]))
    return persist_raes_operation_record(RaesOperationRecordWrite(**fields))


def _seed_expired(*, request_id: UUID, retention_expires_at: datetime) -> RaesOperationRecord:
    return _persist(
        request_id=request_id,
        idempotency_key=f"seed:{request_id}",
        retention_expires_at=retention_expires_at,
    )


@override_settings(RAES_OPERATION_RECORD_RETENTION_DAYS=30)
@pytest.mark.django_db
def test_persist_sets_retention_from_settings_when_unset():
    row = _persist()

    assert row.retention_expires_at == SOURCE_TS + timedelta(days=30)


@override_settings(RAES_OPERATION_RECORD_RETENTION_DAYS=30)
@pytest.mark.django_db
def test_persist_preserves_explicit_retention_over_settings_default():
    explicit = SOURCE_TS + timedelta(days=3)
    row = _persist(retention_expires_at=explicit)

    assert row.retention_expires_at == explicit


@override_settings(RAES_OPERATION_RECORD_RETENTION_DAYS=0)
@pytest.mark.django_db
def test_persist_disables_retention_when_days_not_positive():
    row = _persist()

    assert row.retention_expires_at is None


@override_settings(RAES_OPERATION_RECORD_RETENTION_DAYS=30)
@pytest.mark.django_db
def test_persist_retention_is_deterministic_on_replay():
    first = _persist()
    second = _persist()

    assert first.id == second.id
    assert second.retention_expires_at == SOURCE_TS + timedelta(days=30)
    assert RaesOperationRecord.objects.count() == 1


@pytest.mark.django_db
def test_prune_deletes_expired_rows_and_retains_unexpired():
    now = timezone.now()
    expired = _seed_expired(request_id=uuid4(), retention_expires_at=now - timedelta(days=1))
    unexpired = _seed_expired(request_id=uuid4(), retention_expires_at=now + timedelta(days=1))

    deleted = prune_expired_raes_operation_records(batch_size=100)

    assert deleted == 1
    assert not RaesOperationRecord.objects.filter(pk=expired.pk).exists()
    assert RaesOperationRecord.objects.filter(pk=unexpired.pk).exists()


# A non-positive retention window is the documented way to persist a row with no
# boundary (``_resolve_retention_expires_at``). Without it the settings default
# (30 days) stamps ``SOURCE_TS + 30d`` instead, so this exercised an expiring row
# and only passed while that derived boundary was still in the future.
@override_settings(RAES_OPERATION_RECORD_RETENTION_DAYS=0)
@pytest.mark.django_db
def test_prune_ignores_rows_without_retention_boundary():
    kept = _persist(retention_expires_at=None)
    assert kept.retention_expires_at is None

    deleted = prune_expired_raes_operation_records(batch_size=100)

    assert deleted == 0
    assert RaesOperationRecord.objects.filter(pk=kept.pk).exists()


@pytest.mark.django_db
def test_prune_respects_bounded_batch_size():
    now = timezone.now()
    for _ in range(3):
        _seed_expired(request_id=uuid4(), retention_expires_at=now - timedelta(days=1))

    deleted = prune_expired_raes_operation_records(batch_size=2)

    assert deleted == 2
    assert RaesOperationRecord.objects.count() == 1


@pytest.mark.django_db
def test_prune_returns_zero_when_nothing_expired():
    assert prune_expired_raes_operation_records(batch_size=50) == 0
