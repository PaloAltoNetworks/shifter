"""Tests for the ACES range presentation-projection seam (#1276).

Drives real ``AcesOperationRecord`` rows through
``shared.aces.presentation.build_range_aces_projection`` and asserts the compact
UI summary: latest operation status + display label distinct from
``ResourceStatus``, latest snapshot reduced to a resource *count* (never the raw
``resources`` list), latest receipt reference, a JSON-safe ``to_payload()``, and
a ``None`` result for legacy ranges with no ACES rows.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from shared.aces.contracts import SHIFTER_BACKEND_PROFILE
from shared.aces.presentation import (
    ACES_OPERATION_STATUS_LABELS,
    build_range_aces_projection,
)
from shared.aces.status import ACES_STATE_RUNNING, ACES_STATE_SUCCEEDED
from shared.enums import ResourceStatus
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


class TestBuildRangeAcesProjection:
    def test_none_when_no_aces_rows(self):
        assert build_range_aces_projection(uuid4()) is None

    def test_latest_operation_status_and_label(self):
        request_id = uuid4()
        now = timezone.now()
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
            source_timestamp=now - timedelta(minutes=5),
            payload={"operation_id": "op-1", "status": ACES_STATE_RUNNING},
        )
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
            source_timestamp=now,
            payload={"operation_id": "op-1", "status": ACES_STATE_SUCCEEDED, "status_reason": "done"},
        )

        proj = build_range_aces_projection(request_id)

        assert proj is not None
        assert proj.status == ACES_STATE_SUCCEEDED
        assert proj.status_label == ACES_OPERATION_STATUS_LABELS[ACES_STATE_SUCCEEDED]
        assert proj.status_reason == "done"
        assert proj.observed_at is not None

    def test_status_label_is_distinct_from_resource_status(self):
        """ACES operation labels must not collide with Shifter lifecycle labels."""
        resource_status_values = {s.value for s in ResourceStatus}
        for label in ACES_OPERATION_STATUS_LABELS.values():
            assert label not in resource_status_values

    def test_snapshot_reduced_to_resource_count(self):
        request_id = uuid4()
        now = timezone.now()
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
            source_timestamp=now,
            payload={
                "operation_id": "op-1",
                "resources": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "snapshot_ref": "snap-ref-1",
            },
        )

        proj = build_range_aces_projection(request_id)

        assert proj is not None
        assert proj.snapshot is not None
        assert proj.snapshot.resource_count == 3
        assert proj.snapshot.snapshot_ref == "snap-ref-1"

    def test_receipt_reference_summarized(self):
        request_id = uuid4()
        now = timezone.now()
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_RECEIPT,
            source_timestamp=now,
            payload={"operation_id": "op-1", "status": ACES_STATE_RUNNING, "receipt_ref": "rcpt-1"},
        )

        proj = build_range_aces_projection(request_id)

        assert proj is not None
        assert proj.receipt is not None
        assert proj.receipt.receipt_ref == "rcpt-1"

    def test_to_payload_is_json_safe_and_carries_no_raw_resources(self):
        request_id = uuid4()
        now = timezone.now()
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
            source_timestamp=now,
            payload={"operation_id": "op-1", "status": ACES_STATE_RUNNING},
        )
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
            source_timestamp=now,
            payload={
                "operation_id": "op-1",
                "resources": [{"id": "res-a", "detail": "verbose-nested-detail"}],
                "snapshot_ref": "snap-ref-1",
            },
        )

        proj = build_range_aces_projection(request_id)
        assert proj is not None
        payload = proj.to_payload()

        import json

        encoded = json.dumps(payload)  # must not raise (datetimes serialized)
        # Raw nested resource structure never reaches the payload; only a count.
        assert "verbose-nested-detail" not in encoded
        assert "resources" not in payload
        assert payload["snapshot"]["resource_count"] == 1
        assert payload["status"] == ACES_STATE_RUNNING
        assert payload["status_label"] == ACES_OPERATION_STATUS_LABELS[ACES_STATE_RUNNING]

    def test_filters_by_contract_profile(self):
        request_id = uuid4()
        _record(
            request_id,
            record_kind=AcesOperationRecord.RecordKind.OPERATION_STATUS,
            source_timestamp=timezone.now(),
            payload={"operation_id": "op-1", "status": ACES_STATE_RUNNING},
        )
        assert build_range_aces_projection(request_id, contract_profile="other-profile") is None
