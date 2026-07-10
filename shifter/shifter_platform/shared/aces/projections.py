"""Read-only projections of ACES operation sidecar records for product APIs (#1275).

The sidecar (:class:`shared.models.AcesOperationRecord`) is written through
:mod:`shared.aces.operations` after :mod:`shared.schemas.aces_operation`
validation, which already rejects secrets/prompts/scripts/tokens and bounds
sizes. This module is the READ counterpart: it applies a per-record-kind
*response* allowlist -- "safe to persist internally is not the same as safe to
return" (preflight ``docs/architecture/aces-operation-api-projections-preflight-1275.md``)
-- and returns serializer-ready projection objects so API views never touch the
ORM or the raw ``payload``.

This is the single shared read seam (parameterized by ``request_id``,
``record_kind``, ``contract_profile``, and a bounded limit); Mission Control /
CMS callers read through it instead of importing the model, keeping the
redaction rules in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from shared.aces.contracts import SHIFTER_BACKEND_PROFILE
from shared.models import AcesOperationRecord

# Per-record-kind RESPONSE payload allowlist. Each set is a subset of
# ``shared.schemas.aces_operation.PAYLOAD_KEYS_BY_RECORD_KIND``; nested raw
# ``diagnostic_refs`` inside a payload is never surfaced from the payload copy
# (the record-level ``diagnostic_refs`` field carries the already-sanitized,
# reference-only refs instead).
RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND: dict[str, frozenset[str]] = {
    AcesOperationRecord.RecordKind.OPERATION_RECEIPT: frozenset(
        {"operation_id", "status", "accepted", "source_timestamp", "receipt_digest", "receipt_ref"}
    ),
    AcesOperationRecord.RecordKind.OPERATION_STATUS: frozenset(
        {"operation_id", "status", "status_reason", "source_timestamp", "updated_at"}
    ),
    AcesOperationRecord.RecordKind.RUNTIME_SNAPSHOT: frozenset(
        {"operation_id", "status", "captured_at", "resources", "snapshot_digest", "snapshot_ref"}
    ),
}

# Record-kind string constants re-exported here so product API layers
# (mission_control / cms) reference the vocabulary through this shared seam
# instead of importing ``shared.models`` directly (ADR-001-R2 cross-layer rule).
RECORD_KIND_OPERATION_RECEIPT: str = AcesOperationRecord.RecordKind.OPERATION_RECEIPT
RECORD_KIND_OPERATION_STATUS: str = AcesOperationRecord.RecordKind.OPERATION_STATUS
RECORD_KIND_RUNTIME_SNAPSHOT: str = AcesOperationRecord.RecordKind.RUNTIME_SNAPSHOT

#: Record kinds this read API exposes. ``execution_plan_ref`` is intentionally
#: excluded from #1275 (reference-only, out of scope).
PROJECTABLE_RECORD_KINDS: frozenset[str] = frozenset(RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND)

#: Default and hard-cap history sizes for a single projection read.
DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 100


@dataclass(frozen=True)
class AcesOperationRecordProjection:
    """Serializer-ready, redacted view of one :class:`AcesOperationRecord`.

    ``payload`` contains only the record-kind response-allowlisted keys.
    ``diagnostic_refs`` is the already-sanitized, reference-only map persisted by
    the sidecar (bounded single-line refs, secret patterns rejected at write).
    """

    id: UUID
    request_id: UUID
    range_id: UUID | None
    record_kind: str
    contract_kind: str
    contract_version: str
    contract_profile: str
    source_timestamp: datetime
    created_at: datetime
    updated_at: datetime
    payload_digest: str
    payload: dict[str, Any]
    diagnostic_refs: dict[str, Any]


def _redacted_payload(record: AcesOperationRecord) -> dict[str, Any]:
    """Return only the response-allowlisted payload keys for the record kind."""
    allowed = RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND[record.record_kind]
    raw = record.payload if isinstance(record.payload, dict) else {}
    return {key: value for key, value in raw.items() if key in allowed}


def _project(record: AcesOperationRecord) -> AcesOperationRecordProjection:
    """Build a redacted projection from one sidecar row."""
    refs = record.diagnostic_refs if isinstance(record.diagnostic_refs, dict) else {}
    return AcesOperationRecordProjection(
        id=record.id,
        request_id=record.request_id,
        range_id=record.range_id,
        record_kind=record.record_kind,
        contract_kind=record.contract_kind,
        contract_version=record.contract_version,
        contract_profile=record.contract_profile,
        source_timestamp=record.source_timestamp,
        created_at=record.created_at,
        updated_at=record.updated_at,
        payload_digest=record.payload_digest,
        payload=_redacted_payload(record),
        diagnostic_refs=dict(refs),
    )


def list_operation_records(
    request_id: UUID | str,
    record_kind: str,
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
    contract_profile: str = SHIFTER_BACKEND_PROFILE,
) -> list[AcesOperationRecordProjection]:
    """Return newest-first redacted projections for one ``request_id`` + ``record_kind``.

    Callers outside ``shared`` use this seam instead of importing the
    ``AcesOperationRecord`` model. The per-kind response allowlist is applied
    here so redaction lives in one place. ``limit`` is clamped to
    ``[1, MAX_HISTORY_LIMIT]``.

    Raises:
        ValueError: if ``record_kind`` is not an exposed record kind.
    """
    if record_kind not in PROJECTABLE_RECORD_KINDS:
        raise ValueError(f"record_kind must be one of {sorted(PROJECTABLE_RECORD_KINDS)}")
    bounded = max(1, min(int(limit), MAX_HISTORY_LIMIT))
    rows = AcesOperationRecord.objects.filter(
        request_id=request_id,
        record_kind=record_kind,
        contract_profile=contract_profile,
    ).order_by("-source_timestamp", "-created_at")[:bounded]
    return [_project(row) for row in rows]
