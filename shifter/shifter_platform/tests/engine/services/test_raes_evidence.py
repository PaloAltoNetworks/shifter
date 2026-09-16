"""Tests for the RAES provisioner-evidence consume path (#1478).

The provisioner emits range.raes.operation / range.raes.snapshot outbox events;
the engine consume-side persists them as operation_status / runtime_snapshot
sidecar records through the validated (redacted) persisters.
"""

from __future__ import annotations

import pytest

from engine.services import record_raes_operation_status, record_raes_runtime_snapshot
from shared.models import RaesOperationRecord

REQUEST_ID = "12345678-1234-5678-1234-567812345678"
_TS = "2026-07-11T00:00:00+00:00"


def _operation_event(status: str = "running", **overrides) -> dict:
    event = {
        "event_type": "range.raes.operation",
        "event_id": "evt-op-1",
        "request_id": REQUEST_ID,
        "range_id": 7,
        "user_id": 3,
        "operation_id": REQUEST_ID,
        "raes_status": status,
        "source_timestamp": _TS,
    }
    event.update(overrides)
    return event


def _snapshot_event(**overrides) -> dict:
    event = {
        "event_type": "range.raes.snapshot",
        "event_id": "evt-snap-1",
        "request_id": REQUEST_ID,
        "range_id": 7,
        "user_id": 3,
        "operation_id": REQUEST_ID,
        "resources": [{"address": "provision.node.web", "resource_type": "node", "status": "provisioned"}],
        "source_timestamp": _TS,
    }
    event.update(overrides)
    return event


@pytest.mark.django_db
def test_operation_event_persists_operation_status_record():
    record_raes_operation_status(_operation_event(status="succeeded", status_reason="done"))
    rec = RaesOperationRecord.objects.get(record_kind=RaesOperationRecord.RecordKind.OPERATION_STATUS)
    assert rec.payload["status"] == "succeeded"
    assert rec.payload["operation_id"] == REQUEST_ID
    assert rec.payload["status_reason"] == "done"


@pytest.mark.django_db
def test_snapshot_event_persists_runtime_snapshot_record():
    record_raes_runtime_snapshot(_snapshot_event())
    rec = RaesOperationRecord.objects.get(record_kind=RaesOperationRecord.RecordKind.RUNTIME_SNAPSHOT)
    assert rec.payload["resources"][0]["address"] == "provision.node.web"
    assert rec.range_id is None  # keyed by request_id; range_id UUID projection key unset


@pytest.mark.django_db
def test_malformed_operation_event_is_ignored_not_fatal():
    record_raes_operation_status({"event_type": "range.raes.operation", "event_id": "e"})
    assert not RaesOperationRecord.objects.filter(record_kind=RaesOperationRecord.RecordKind.OPERATION_STATUS).exists()


@pytest.mark.django_db
def test_process_range_event_routes_raes_events_to_records():
    from engine.handlers import process_range_event

    process_range_event(_operation_event(status="running"))
    process_range_event(_snapshot_event())
    kinds = set(RaesOperationRecord.objects.values_list("record_kind", flat=True))
    assert {
        RaesOperationRecord.RecordKind.OPERATION_STATUS,
        RaesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
    } <= kinds
