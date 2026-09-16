"""Tests for RAES operation sidecar persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from shared.models import RaesOperationRecord
from shared.raes.operations import (
    RaesOperationRecordConflict,
    RaesOperationRecordWrite,
    persist_raes_operation_record,
    persist_runtime_snapshot_record,
)
from shared.schemas.raes_operation import RaesOperationRecordError, canonical_raes_payload_digest

REQUEST_ID = UUID("12345678-1234-5678-1234-567812345678")
SOURCE_TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


def _persist(**overrides):
    fields = {
        "request_id": REQUEST_ID,
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


@pytest.mark.django_db
def test_persist_runtime_snapshot_record_writes_and_is_idempotent():
    payload = {
        "operation_id": "op-1",
        "resources": [{"address": "provision.node.web", "resource_type": "node", "status": "provisioned"}],
    }
    first = persist_runtime_snapshot_record(
        request_id=REQUEST_ID, operation_id="op-1", source_timestamp=SOURCE_TS, payload=payload, range_id=REQUEST_ID
    )
    assert first.record_kind == RaesOperationRecord.RecordKind.RUNTIME_SNAPSHOT
    assert first.contract_version == "runtime-snapshot-v1"
    again = persist_runtime_snapshot_record(
        request_id=REQUEST_ID, operation_id="op-1", source_timestamp=SOURCE_TS, payload=payload, range_id=REQUEST_ID
    )
    assert again.pk == first.pk  # idempotent on (operation_id, source_timestamp)


@pytest.mark.django_db
def test_persist_runtime_snapshot_record_rejects_secret_bearing_resources():
    payload = {"operation_id": "op-1", "resources": [{"address": "n", "ssh_key_secret_arn": "arn:...:secret"}]}
    with pytest.raises(RaesOperationRecordError):
        persist_runtime_snapshot_record(
            request_id=REQUEST_ID, operation_id="op-1", source_timestamp=SOURCE_TS, payload=payload
        )


@pytest.mark.django_db
def test_persist_operation_record_is_idempotent_for_same_source_event():
    first = _persist()
    second = _persist()

    assert first.id == second.id
    assert RaesOperationRecord.objects.count() == 1


@pytest.mark.django_db
def test_persist_operation_record_conflicts_when_replay_payload_drifts():
    _persist()
    changed_payload = {"operation_id": "op-12345678", "accepted": False}

    canonical_raes_payload_digest_2 = canonical_raes_payload_digest(changed_payload)
    with pytest.raises(RaesOperationRecordConflict, match="idempotency conflict"):
        _persist(payload=changed_payload, payload_digest=canonical_raes_payload_digest_2)

    assert RaesOperationRecord.objects.count() == 1


@pytest.mark.django_db
def test_persist_operation_record_conflicts_when_replay_timestamp_drifts():
    _persist()

    arg = SOURCE_TS + timedelta(seconds=1)
    with pytest.raises(RaesOperationRecordConflict, match="idempotency conflict"):
        _persist(source_timestamp=arg)


@pytest.mark.django_db
def test_persist_operation_record_records_explicit_discriminators_and_projection_key():
    range_id = uuid4()
    row = _persist(
        range_id=range_id,
        record_kind=RaesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
        contract_version="runtime-snapshot-v1",
        payload={
            "operation_id": "op-12345678",
            "resources": [
                {
                    "address": "node.web",
                    "resource_type": "node",
                    "status": "provisioned",
                }
            ],
        },
        diagnostic_refs={"fingerprint": "diag-fingerprint-1"},
        retention_expires_at=SOURCE_TS + timedelta(days=7),
    )

    assert row.request_id == REQUEST_ID
    assert row.range_id == range_id
    assert row.contract_kind == "raes"
    assert row.contract_version == "runtime-snapshot-v1"
    assert row.contract_profile == "provisioning-only"
    assert row.record_kind == "runtime_snapshot"
    assert row.operation_id == "op-12345678"
    assert row.idempotency_key == "range-provisioned:event-1"
    assert row.source_timestamp == SOURCE_TS
    assert row.diagnostic_refs == {"fingerprint": "diag-fingerprint-1"}
    assert row.owner == "shared"
    assert row.retention_expires_at == SOURCE_TS + timedelta(days=7)


@pytest.mark.django_db
def test_persist_operation_record_rejects_unsupported_profile_before_write():
    with pytest.raises(RaesOperationRecordError, match="contract_profile"):
        _persist(contract_profile="orchestration")

    assert RaesOperationRecord.objects.count() == 0


@pytest.mark.django_db
def test_persist_operation_record_rejects_digest_mismatch_before_write():
    with pytest.raises(RaesOperationRecordError, match="payload_digest"):
        _persist(payload_digest="sha256:" + "f" * 64)

    assert RaesOperationRecord.objects.count() == 0


@pytest.mark.django_db
def test_persist_operation_record_rejects_secret_bearing_payload_before_write():
    with pytest.raises(RaesOperationRecordError, match="secret-bearing"):
        _persist(payload={"operation_id": "op-12345678", "private_key": "redacted-key-material"})

    assert RaesOperationRecord.objects.count() == 0


def test_operation_record_model_uses_first_class_sidecar_table():
    assert RaesOperationRecord._meta.db_table == "shared_raes_operation_record"
    field_names = {field.name for field in RaesOperationRecord._meta.fields}

    assert {
        "request_id",
        "range_id",
        "contract_kind",
        "contract_version",
        "contract_profile",
        "record_kind",
        "operation_id",
        "idempotency_key",
        "source_timestamp",
        "payload_digest",
        "diagnostic_refs",
        "retention_expires_at",
    } <= field_names
