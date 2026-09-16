"""RAES sidecar writes are not Shifter lifecycle audit rows (#1277).

Shifter lifecycle audit remains ``shared.AuditLog`` written through
``shared.audit``. RAES operation records (receipts, status,
runtime snapshots) live in the ``RaesOperationRecord`` sidecar and are evidence
references, not audit rows -- persisting one must not create an ``AuditLog`` row
or stash an RAES payload in ``AuditLog.new_state``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from shared.models import AuditLog, RaesOperationRecord
from shared.raes.operations import RaesOperationRecordWrite, persist_raes_operation_record
from shared.schemas.raes_operation import canonical_raes_payload_digest

SOURCE_TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


def _persist_snapshot() -> RaesOperationRecord:
    payload = {
        "operation_id": "op-1",
        "resources": [
            {
                "address": "node.web",
                "resource_type": "node",
                "status": "provisioned",
            }
        ],
        "status": "running",
    }
    return persist_raes_operation_record(
        RaesOperationRecordWrite(
            request_id=uuid4(),
            operation_id="op-1",
            idempotency_key=f"snapshot:{uuid4()}",
            record_kind=RaesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
            contract_version="runtime-snapshot-v1",
            source_timestamp=SOURCE_TS,
            payload=payload,
            payload_digest=canonical_raes_payload_digest(payload),
        )
    )


@pytest.mark.django_db
def test_persisting_raes_snapshot_creates_no_audit_log_row():
    before = AuditLog.objects.count()

    row = _persist_snapshot()

    assert RaesOperationRecord.objects.filter(pk=row.pk).exists()
    assert AuditLog.objects.count() == before
