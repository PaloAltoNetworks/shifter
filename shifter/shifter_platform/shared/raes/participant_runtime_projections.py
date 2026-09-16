"""Read-only projections of RAES participant-runtime sidecar records (#1288).

Mirrors :mod:`shared.raes.projections` (the incumbent
:class:`shared.models.RaesOperationRecord` read seam from #1275). The sidecar
(:class:`shared.models.RaesParticipantRuntimeRecord`) is written through
:mod:`shared.raes.participant_runtime` after
:mod:`shared.schemas.raes_participant_runtime` validation, which already
rejects secrets/prompts/scripts/tokens and bounds sizes. This module is the
READ counterpart: it applies a per-record-kind *response* allowlist -- "safe
to persist internally is not the same as safe to return" -- and returns
serializer-ready projection objects so API views never touch the ORM or the
raw ``payload``.

This is the single shared read seam (parameterized by ``request_id``,
``record_kind``, ``participant_ref``, ``contract_profile``, and a bounded
limit); Mission Control callers read through it instead of importing the
model, keeping the redaction rules in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from shared.models import RaesParticipantRuntimeRecord
from shared.raes.contracts import SHIFTER_BACKEND_PROFILE
from shared.raes.projections import DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT

# Per-record-kind RESPONSE payload allowlist. Each set is a subset of
# ``shared.schemas.raes_participant_runtime.PAYLOAD_KEYS_BY_RECORD_KIND``;
# ``request_id`` is a valid persisted payload key (mirrors the top-level
# projection field) but is never surfaced from the payload copy.
RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND: dict[str, frozenset[str]] = {
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION: frozenset(
        {
            "backend_name",
            "capability_refs",
            "implementation_digest",
            "implementation_ref",
            "participant_ref",
            "source_timestamp",
            "status",
        }
    ),
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME: frozenset(
        {
            "participant_ref",
            "runtime_digest",
            "runtime_ref",
            "source_timestamp",
            "status",
            "status_reason",
            "updated_at",
        }
    ),
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_BEHAVIOR_HISTORY: frozenset(
        {
            "participant_ref",
            "source_timestamp",
            "event_kind",
            "event_ref",
            "event_digest",
            "sequence",
            "status",
            "status_reason",
            "operation_id",
        }
    ),
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_EVIDENCE: frozenset(
        {
            "participant_ref",
            "source_timestamp",
            "evidence_kind",
            "capture_profile",
            "provenance_source",
            "provenance_ref",
            "artifact_ref",
            "artifact_digest",
            "redaction_policy",
            "operation_id",
            "operation_record_id",
            "receipt_ref",
        }
    ),
}

# Record-kind string constants re-exported here so product API layers
# (mission_control / cms) reference the vocabulary through this shared seam
# instead of importing ``shared.models`` directly (ADR-001-R2 cross-layer rule).
RECORD_KIND_PARTICIPANT_IMPLEMENTATION: str = RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION
RECORD_KIND_PARTICIPANT_RUNTIME: str = RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME
RECORD_KIND_PARTICIPANT_BEHAVIOR_HISTORY: str = RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_BEHAVIOR_HISTORY
RECORD_KIND_PARTICIPANT_EVIDENCE: str = RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_EVIDENCE

#: Record kinds this read API exposes.
PROJECTABLE_RECORD_KINDS: frozenset[str] = frozenset(RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND)


@dataclass(frozen=True)
class RaesParticipantRuntimeRecordProjection:
    """Serializer-ready, redacted view of one :class:`RaesParticipantRuntimeRecord`.

    ``payload`` contains only the record-kind response-allowlisted keys.
    ``diagnostic_refs`` is the already-sanitized reference-only map persisted
    by the sidecar.
    """

    id: UUID
    request_id: UUID
    range_id: UUID | None
    range_instance_id: UUID | None
    participant_ref: str
    record_kind: str
    contract_kind: str
    contract_version: str
    contract_profile: str
    participant_runtime_profile: str
    source_timestamp: datetime
    created_at: datetime
    updated_at: datetime
    payload_digest: str
    retention_class: str
    redaction_state: str
    payload: dict[str, Any]
    diagnostic_refs: dict[str, Any]


def _redacted_payload(record: RaesParticipantRuntimeRecord) -> dict[str, Any]:
    """Return only the response-allowlisted payload keys for the record kind."""
    allowed = RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND[record.record_kind]
    raw = record.payload if isinstance(record.payload, dict) else {}
    return {key: value for key, value in raw.items() if key in allowed}


def _project(record: RaesParticipantRuntimeRecord) -> RaesParticipantRuntimeRecordProjection:
    """Build a redacted projection from one sidecar row."""
    refs = record.diagnostic_refs if isinstance(record.diagnostic_refs, dict) else {}
    return RaesParticipantRuntimeRecordProjection(
        id=record.id,
        request_id=record.request_id,
        range_id=record.range_id,
        range_instance_id=record.range_instance_id,
        participant_ref=record.participant_ref,
        record_kind=record.record_kind,
        contract_kind=record.contract_kind,
        contract_version=record.contract_version,
        contract_profile=record.contract_profile,
        participant_runtime_profile=record.participant_runtime_profile,
        source_timestamp=record.source_timestamp,
        created_at=record.created_at,
        updated_at=record.updated_at,
        payload_digest=record.payload_digest,
        retention_class=record.retention_class,
        redaction_state=record.redaction_state,
        payload=_redacted_payload(record),
        diagnostic_refs=dict(refs),
    )


def list_participant_runtime_records(
    request_id: UUID | str,
    record_kind: str,
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
    participant_ref: str | None = None,
    contract_profile: str = SHIFTER_BACKEND_PROFILE,
) -> list[RaesParticipantRuntimeRecordProjection]:
    """Return newest-first redacted projections for one ``request_id`` + ``record_kind``.

    Callers outside ``shared`` use this seam instead of importing the
    ``RaesParticipantRuntimeRecord`` model. The per-kind response allowlist is
    applied here so redaction lives in one place. ``limit`` is clamped to
    ``[1, MAX_HISTORY_LIMIT]``. ``participant_ref``, when given, narrows the
    result to that one participant's records.

    Raises:
        ValueError: if ``record_kind`` is not an exposed record kind.
    """
    if record_kind not in PROJECTABLE_RECORD_KINDS:
        raise ValueError(f"record_kind must be one of {sorted(PROJECTABLE_RECORD_KINDS)}")
    bounded = max(1, min(int(limit), MAX_HISTORY_LIMIT))
    filters: dict[str, Any] = {
        "request_id": request_id,
        "record_kind": record_kind,
        "contract_profile": contract_profile,
    }
    if participant_ref:
        filters["participant_ref"] = participant_ref
    rows = RaesParticipantRuntimeRecord.objects.filter(**filters).order_by("-source_timestamp", "-created_at")[:bounded]
    return [_project(row) for row in rows]
