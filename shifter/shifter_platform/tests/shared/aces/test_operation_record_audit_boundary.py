"""ACES sidecar writes are not Shifter lifecycle audit rows (#1277).

Shifter lifecycle audit remains ``risk_register.AuditLog`` written through
``risk_register.services.audit_log``. ACES operation records (receipts, status,
runtime snapshots) live in the ``AcesOperationRecord`` sidecar and are evidence
references, not audit rows -- persisting one must not create an ``AuditLog`` row
or stash an ACES payload in ``AuditLog.new_state``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from risk_register.models import AuditLog
from shared.aces.operations import AcesOperationRecordWrite, persist_aces_operation_record
from shared.models import AcesOperationRecord
from shared.schemas.aces_operation import canonical_aces_payload_digest

SOURCE_TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


def _persist_snapshot() -> AcesOperationRecord:
    payload = {"operation_id": "op-1", "resources": [{"kind": "vm"}], "status": "running"}
    return persist_aces_operation_record(
        AcesOperationRecordWrite(
            request_id=uuid4(),
            operation_id="op-1",
            idempotency_key=f"snapshot:{uuid4()}",
            record_kind=AcesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
            contract_version="runtime-snapshot-v1",
            source_timestamp=SOURCE_TS,
            payload=payload,
            payload_digest=canonical_aces_payload_digest(payload),
        )
    )


@pytest.mark.django_db
def test_persisting_aces_snapshot_creates_no_audit_log_row():
    before = AuditLog.objects.count()

    row = _persist_snapshot()

    assert AcesOperationRecord.objects.filter(pk=row.pk).exists()
    assert AuditLog.objects.count() == before


@pytest.mark.django_db
def test_audit_log_has_no_aces_operation_entity_type():
    # ACES operation records are not an AuditLog entity type; the sidecar (not
    # AuditLog) is their store. This guards against a future EntityType being
    # added that would invite ACES payloads into audit JSON.
    entity_values = {choice.value for choice in AuditLog.EntityType}

    assert not any("aces" in value.lower() for value in entity_values)
    assert "runtime_snapshot" not in entity_values
