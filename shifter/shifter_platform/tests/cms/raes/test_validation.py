"""Tests for the RAES live-validation evidence collector (#1264).

Seeds redacted-safe operation records through the low-level persister and asserts
collect_evidence + validate_evidence read them back and enforce a non-vacuous
realization ("real receipt + succeeded status + snapshot with resources").
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cms.raes.validation import RaesEvidenceError, collect_evidence, validate_evidence
from shared.models import RaesOperationRecord
from shared.raes.operations import RaesOperationRecordWrite, persist_raes_operation_record
from shared.schemas.raes_operation import canonical_raes_payload_digest

_OP = "op-validate-1"
_TS = datetime(2026, 7, 11, tzinfo=UTC)


def _seed(request_id, record_kind, contract_version, payload, suffix):
    write = RaesOperationRecordWrite(
        request_id=request_id,
        operation_id=_OP,
        idempotency_key=f"{record_kind}:{request_id}:{suffix}",
        record_kind=record_kind,
        contract_version=contract_version,
        source_timestamp=_TS,
        payload=payload,
        payload_digest=canonical_raes_payload_digest(payload),
    )
    return persist_raes_operation_record(write)


def _seed_receipt(request_id):
    _seed(
        request_id,
        RaesOperationRecord.RecordKind.OPERATION_RECEIPT,
        "operation-receipt-v1",
        {"operation_id": _OP, "accepted": True, "status": "accepted"},
        "receipt",
    )


def _seed_status(request_id, status):
    _seed(
        request_id,
        RaesOperationRecord.RecordKind.OPERATION_STATUS,
        "operation-status-v1",
        {"operation_id": _OP, "status": status},
        f"status-{status}",
    )


def _seed_snapshot(request_id, resources):
    _seed(
        request_id,
        RaesOperationRecord.RecordKind.RUNTIME_SNAPSHOT,
        "runtime-snapshot-v1",
        {"operation_id": _OP, "resources": resources},
        "snapshot",
    )


@pytest.mark.django_db
def test_collect_and_validate_full_evidence_passes():
    rid = str(uuid4())
    _seed_receipt(rid)
    _seed_status(rid, "succeeded")
    _seed_snapshot(
        rid,
        [
            {"address": "provision.node.web", "resource_type": "node", "status": "provisioned"},
            {"address": "content.seed", "resource_type": "content-placement", "status": "verified"},
            {"address": "account.operator", "resource_type": "account-placement", "status": "verified"},
            {"address": "feature.config", "resource_type": "feature-binding", "status": "verified"},
        ],
    )

    summary = collect_evidence(rid)
    assert summary.receipt_count == 1
    assert summary.status_count == 1
    assert summary.snapshot_count == 1
    assert summary.has_succeeded_status is True
    assert summary.snapshot_resource_count == 4
    assert summary.composition_resource_count == 3
    assert summary.verified_composition_types == frozenset(
        {"content-placement", "account-placement", "feature-binding"}
    )
    assert validate_evidence(summary) == []


@pytest.mark.django_db
def test_validate_flags_missing_receipt_unsucceeded_status_and_vacuous_snapshot():
    rid = str(uuid4())
    _seed_status(rid, "running")
    _seed_snapshot(rid, [])

    problems = validate_evidence(collect_evidence(rid))
    assert any("operation_receipt" in p for p in problems)
    assert any("succeeded" in p for p in problems)
    assert any("vacuous" in p for p in problems)


@pytest.mark.django_db
def test_no_evidence_flags_everything():
    problems = validate_evidence(collect_evidence(str(uuid4())))
    assert any("operation_receipt" in p for p in problems)
    assert any("operation_status" in p for p in problems)
    assert any("runtime_snapshot" in p for p in problems)


@pytest.mark.django_db
def test_topology_only_snapshot_fails_composition_realization_gate():
    rid = str(uuid4())
    _seed_receipt(rid)
    _seed_status(rid, "succeeded")
    _seed_snapshot(
        rid,
        [{"address": "provision.node.web", "resource_type": "node", "status": "provisioned"}],
    )

    problems = validate_evidence(collect_evidence(rid))
    assert any("content-placement" in problem for problem in problems)
    assert any("account-placement" in problem for problem in problems)
    assert any("feature-binding" in problem for problem in problems)


def test_collect_rejects_unverified_composition_entry(monkeypatch):
    resources = [
        {"address": "content.unverified", "resource_type": "content-placement", "status": "provisioned"},
    ]
    projected = SimpleNamespace(payload={"operation_id": _OP, "resources": resources})
    monkeypatch.setattr("cms.raes.validation.list_operation_records", lambda *a, **k: [projected])
    request_id = str(uuid4())

    with pytest.raises(RaesEvidenceError, match="composition evidence is not verified"):
        collect_evidence(request_id)


def test_collect_rejects_duplicate_composition_address(monkeypatch):
    resources = [
        {"address": "content.seed", "resource_type": "content-placement", "status": "verified"},
        {"address": "content.seed", "resource_type": "content-placement", "status": "verified"},
    ]
    projected = SimpleNamespace(payload={"operation_id": _OP, "resources": resources})
    monkeypatch.setattr("cms.raes.validation.list_operation_records", lambda *a, **k: [projected])
    request_id = str(uuid4())

    with pytest.raises(RaesEvidenceError, match="invalid or duplicate address"):
        collect_evidence(request_id)


def test_collect_evidence_rejects_forbidden_substring(monkeypatch):
    # The read seam redacts, but collect_evidence re-asserts the redaction
    # contract: a projected payload leaking realization detail is a hard failure.
    leaked = SimpleNamespace(payload={"operation_id": _OP, "resources": [{"address": "cidr-10.0.0.0/24"}]})
    monkeypatch.setattr("cms.raes.validation.list_operation_records", lambda *a, **k: [leaked])
    str_ = str(uuid4())
    with pytest.raises(RaesEvidenceError):
        collect_evidence(str_)
