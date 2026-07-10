"""Tests for the ACES read-projection seam (#1275).

Drives real ``AcesOperationRecord`` rows through ``list_operation_records`` and
asserts the response allowlist (redaction), ordering, and bounds. Rows are
persisted through the model's own validating ``save()`` (valid canonical
payloads), and the redaction test uses a payload key that is valid to persist
but excluded from the API response allowlist (``request_id`` inside the
payload), proving the read seam strips persisted-but-not-returned keys.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from shared.aces.contracts import SHIFTER_BACKEND_PROFILE
from shared.aces.projections import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    list_operation_records,
)
from shared.models import AcesOperationRecord
from shared.schemas.aces_operation import canonical_aces_payload_digest

pytestmark = pytest.mark.django_db

_CONTRACT_VERSION = {
    AcesOperationRecord.RecordKind.OPERATION_RECEIPT: "operation-receipt-v1",
    AcesOperationRecord.RecordKind.OPERATION_STATUS: "operation-status-v1",
    AcesOperationRecord.RecordKind.RUNTIME_SNAPSHOT: "runtime-snapshot-v1",
}


def _record(request_id, *, record_kind, payload, source_timestamp):
    """Persist one valid sidecar row through the model's validating save()."""
    return AcesOperationRecord.objects.create(
        request_id=request_id,
        operation_id=payload["operation_id"],
        idempotency_key=f"{record_kind}:{source_timestamp.isoformat()}",
        contract_kind=AcesOperationRecord.ContractKind.ACES,
        contract_version=_CONTRACT_VERSION[record_kind],
        contract_profile=SHIFTER_BACKEND_PROFILE,
        record_kind=record_kind,
        source_timestamp=source_timestamp,
        payload_digest=canonical_aces_payload_digest(payload),
        payload=payload,
    )


def _status_payload(status="running", **extra):
    return {"operation_id": "op-1", "status": status, **extra}


class TestListOperationRecords:
    def test_redacts_persisted_but_non_response_keys(self):
        request_id = uuid4()
        # ``request_id`` is a valid persisted operation_status payload key, but it
        # is NOT in the API response allowlist, so it must be stripped on read.
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
            source_timestamp=timezone.now(),
            payload=_status_payload(status_reason="provisioning subnet", request_id=str(request_id)),
        )
        [proj] = list_operation_records(request_id, AcesOperationRecord.RecordKind.OPERATION_STATUS)
        assert set(proj.payload) == {"operation_id", "status", "status_reason"}
        assert "request_id" not in proj.payload

    def test_runtime_snapshot_response_allowlist_strips_non_returned_keys(self):
        request_id = uuid4()
        # ``request_id`` is a valid persisted runtime_snapshot payload key but is
        # NOT in the response allowlist, so the read seam must strip it.
        payload = {
            "operation_id": "op-1",
            "status": "running",
            "resources": [{"kind": "vm"}],
            "snapshot_digest": "sha256:" + "a" * 64,
            "request_id": str(request_id),
        }
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
            source_timestamp=timezone.now(),
            payload=payload,
        )
        [proj] = list_operation_records(request_id, AcesOperationRecord.RecordKind.RUNTIME_SNAPSHOT)
        assert set(proj.payload) == {"operation_id", "status", "resources", "snapshot_digest"}
        assert "request_id" not in proj.payload

    def test_orders_newest_first(self):
        request_id = uuid4()
        now = timezone.now()
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
            source_timestamp=now - timedelta(minutes=5),
            payload=_status_payload(status="accepted"),
        )
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
            source_timestamp=now,
            payload=_status_payload(status="running"),
        )
        projections = list_operation_records(request_id, AcesOperationRecord.RecordKind.OPERATION_STATUS)
        assert [p.payload["status"] for p in projections] == ["running", "accepted"]

    def test_limit_is_clamped_to_max(self):
        request_id = uuid4()
        now = timezone.now()
        for i in range(MAX_HISTORY_LIMIT + 5):
            _record(
                request_id,
                record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
                source_timestamp=now - timedelta(seconds=i),
                payload=_status_payload(),
            )
        results = list_operation_records(request_id, AcesOperationRecord.RecordKind.OPERATION_STATUS, limit=10_000)
        assert len(results) == MAX_HISTORY_LIMIT

    def test_default_limit_applied(self):
        request_id = uuid4()
        now = timezone.now()
        for i in range(DEFAULT_HISTORY_LIMIT + 5):
            _record(
                request_id,
                record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
                source_timestamp=now - timedelta(seconds=i),
                payload=_status_payload(),
            )
        results = list_operation_records(request_id, AcesOperationRecord.RecordKind.OPERATION_STATUS)
        assert len(results) == DEFAULT_HISTORY_LIMIT

    def test_filters_by_record_kind_and_request_id(self):
        request_id = uuid4()
        other_request = uuid4()
        now = timezone.now()
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
            source_timestamp=now,
            payload=_status_payload(),
        )
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
            source_timestamp=now,
            payload={"operation_id": "op-1", "resources": []},
        )
        _record(
            other_request,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
            source_timestamp=now,
            payload=_status_payload(),
        )
        results = list_operation_records(request_id, AcesOperationRecord.RecordKind.OPERATION_STATUS)
        assert len(results) == 1
        assert results[0].request_id == request_id

    def test_filters_by_contract_profile(self):
        request_id = uuid4()
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
            source_timestamp=timezone.now(),
            payload=_status_payload(),
        )
        # Querying a non-matching profile excludes the row.
        assert (
            list_operation_records(
                request_id,
                AcesOperationRecord.RecordKind.OPERATION_STATUS,
                contract_profile="some-other-profile",
            )
            == []
        )

    def test_empty_when_no_rows(self):
        assert list_operation_records(uuid4(), AcesOperationRecord.RecordKind.RUNTIME_SNAPSHOT) == []

    def test_unknown_record_kind_raises(self):
        with pytest.raises(ValueError, match="record_kind must be one of"):
            list_operation_records(uuid4(), "execution_plan_ref")
