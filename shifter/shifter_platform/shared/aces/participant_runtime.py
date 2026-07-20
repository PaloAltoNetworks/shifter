"""Persistence helpers for ACES participant-runtime sidecar records (#1288).

Mirrors :mod:`shared.aces.operations` (the incumbent
:class:`shared.models.AcesOperationRecord` write seam from #1273/#1274).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from shared.aces.contracts import SHIFTER_BACKEND_PROFILE
from shared.models import AcesParticipantRuntimeRecord
from shared.schemas.aces_participant_runtime import (
    AcesParticipantRuntimeRecordError,
    canonical_aces_payload_digest,
)

#: Default participant-runtime profile Shifter writes sidecar records under.
DEFAULT_PARTICIPANT_RUNTIME_PROFILE = "shifter-provisioning"


def _bounded_idempotency_key(prefix: str, *parts: str) -> str:
    """Build a deterministic idempotency key that fits the model's 128-char column.

    ``participant_ref`` and the other correlation refs are validated as bounded
    single-line refs (up to hundreds of characters), so concatenating them
    verbatim can exceed the ``idempotency_key`` column. Digesting the parts keeps
    the key both deterministic (identical inputs -> identical key, preserving
    idempotent replay) and safely bounded (``prefix`` + 64 hex chars). Parts are
    JSON-encoded before hashing so distinct inputs cannot collide via delimiter
    ambiguity.
    """
    digest = sha256(json.dumps(list(parts), separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


#: Contract version for ``participant-implementation-v1`` sidecar records.
PARTICIPANT_IMPLEMENTATION_CONTRACT_VERSION = "participant-implementation-v1"

#: Contract version for ``participant-runtime-v1`` sidecar records.
PARTICIPANT_RUNTIME_CONTRACT_VERSION = "participant-runtime-v1"

#: Contract version for ``participant-behavior-history-v1`` sidecar records (#1289).
PARTICIPANT_BEHAVIOR_HISTORY_CONTRACT_VERSION = "participant-behavior-history-v1"

#: Contract version for ``participant-evidence-v1`` sidecar records (#1289).
PARTICIPANT_EVIDENCE_CONTRACT_VERSION = "participant-evidence-v1"


class AcesParticipantRuntimeRecordConflict(ValueError):
    """Raised when an idempotent replay carries conflicting participant-runtime content."""


def _reconcile_payload_identity(payload: dict[str, Any], **identity: object) -> None:
    """Reject a payload whose echoed identity fields disagree with the key inputs.

    The typed helpers build the deterministic idempotency key from scalar
    arguments while persisting the caller-supplied ``payload`` verbatim. If the
    payload echoes an identity field (for example ``participant_ref`` or
    ``provenance_ref``) with a different value, the row content would drift from
    the identity the key was built on -- letting two logically distinct records
    collide, or a replay falsely conflict. Reconcile them before the write so the
    key always reflects the persisted content.
    """
    for key, expected in identity.items():
        actual = payload.get(key)
        if actual is not None and actual != expected:
            raise AcesParticipantRuntimeRecordConflict(
                f"payload {key!r}={actual!r} conflicts with identity argument {expected!r}"
            )


def _payload_identity(payload: dict[str, Any], key: str) -> str:
    """Return a required, non-empty string identity field from the payload.

    The #1289 reference writers derive the idempotency key from the payload's own
    validated identity fields (evidence/event kind and provenance/event ref), so
    the key can never drift from the persisted content. Missing or non-string
    identity fields are rejected here rather than producing a malformed key.
    """
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AcesParticipantRuntimeRecordError(f"payload {key!r} is required to identify the record")
    return value


@dataclass(frozen=True)
class ParticipantRecordWriteOptions:
    """Optional envelope and correlation fields for the #1289 reference writers.

    Bundled into one argument so the typed writers stay within the parameter
    budget while keeping the required correlation (request_id, participant_ref,
    source_timestamp) and the reference ``payload`` explicit.
    """

    diagnostic_refs: dict[str, Any] | None = None
    owner: str = AcesParticipantRuntimeRecord.Owner.SHARED
    range_id: UUID | str | None = None
    range_instance_id: UUID | str | None = None


@dataclass(frozen=True)
class AcesParticipantRuntimeRecordWrite:
    """Input contract for writing one ACES participant-runtime sidecar record."""

    request_id: UUID | str
    participant_ref: str
    idempotency_key: str
    record_kind: str
    contract_version: str
    source_timestamp: datetime
    payload: dict[str, Any]
    payload_digest: str | None = None
    diagnostic_refs: dict[str, Any] | None = None
    range_id: UUID | str | None = None
    range_instance_id: UUID | str | None = None
    contract_kind: str = AcesParticipantRuntimeRecord.ContractKind.ACES
    contract_profile: str = SHIFTER_BACKEND_PROFILE
    participant_runtime_profile: str = DEFAULT_PARTICIPANT_RUNTIME_PROFILE
    owner: str = AcesParticipantRuntimeRecord.Owner.SHARED
    retention_class: str = AcesParticipantRuntimeRecord.RetentionClass.DEFAULT
    redaction_state: str = AcesParticipantRuntimeRecord.RedactionState.SANITIZED
    retention_expires_at: datetime | None = None


def _idempotency_lookup(write: AcesParticipantRuntimeRecordWrite) -> dict[str, Any]:
    """Build the database lookup tuple that defines replay identity."""
    return {
        "request_id": write.request_id,
        "participant_ref": write.participant_ref,
        "record_kind": write.record_kind,
        "participant_runtime_profile": write.participant_runtime_profile,
        "contract_version": write.contract_version,
        "idempotency_key": write.idempotency_key,
    }


def _assert_replay_matches(
    existing: AcesParticipantRuntimeRecord,
    *,
    write: AcesParticipantRuntimeRecordWrite,
    payload_digest: str,
) -> None:
    """Reject idempotency-key reuse with different canonical content."""
    if existing.source_timestamp != write.source_timestamp or existing.payload_digest != payload_digest:
        raise AcesParticipantRuntimeRecordConflict(
            "idempotency conflict: replay has different source_timestamp or payload_digest"
        )


def persist_aces_participant_runtime_record(
    write: AcesParticipantRuntimeRecordWrite,
) -> AcesParticipantRuntimeRecord:
    """Create or return an idempotent ACES participant-runtime sidecar record.

    The database enforces the replay key. The service enforces deterministic
    replay semantics by rejecting drift in the canonical content identity.
    """
    normalized_payload_digest = write.payload_digest or canonical_aces_payload_digest(write.payload)
    lookup = _idempotency_lookup(write)
    defaults = {
        "range_id": write.range_id,
        "range_instance_id": write.range_instance_id,
        "contract_kind": write.contract_kind,
        "contract_profile": write.contract_profile,
        "source_timestamp": write.source_timestamp,
        "payload_digest": normalized_payload_digest,
        "payload": write.payload,
        "diagnostic_refs": write.diagnostic_refs or {},
        "owner": write.owner,
        "retention_class": write.retention_class,
        "redaction_state": write.redaction_state,
        "retention_expires_at": write.retention_expires_at,
    }

    try:
        with transaction.atomic():
            record, created = AcesParticipantRuntimeRecord.objects.get_or_create(**lookup, defaults=defaults)
    except IntegrityError:
        record = AcesParticipantRuntimeRecord.objects.get(**lookup)
        created = False

    if not created:
        _assert_replay_matches(record, write=write, payload_digest=normalized_payload_digest)
    return record


def persist_participant_implementation_record(
    *,
    request_id: UUID | str,
    participant_ref: str,
    implementation_ref: str,
    source_timestamp: datetime,
    payload: dict[str, Any],
    diagnostic_refs: dict[str, Any] | None = None,
    owner: str = AcesParticipantRuntimeRecord.Owner.PROVISIONER,
) -> AcesParticipantRuntimeRecord:
    """Persist one ``participant_implementation`` sidecar record idempotently.

    Encapsulates the ``record_kind`` and idempotency-key convention for
    participant-implementation declarations so callers outside ``shared`` do
    not touch the ``AcesParticipantRuntimeRecord`` model. The idempotency key
    is deterministic in the participant and implementation refs, so
    re-delivery of the same declaration is a no-op (or a conflict when the
    content drifts). The contract version is fixed for this record kind
    (``PARTICIPANT_IMPLEMENTATION_CONTRACT_VERSION``); callers needing a
    non-default version use ``persist_aces_participant_runtime_record`` directly.
    """
    _reconcile_payload_identity(payload, participant_ref=participant_ref, implementation_ref=implementation_ref)
    write = AcesParticipantRuntimeRecordWrite(
        request_id=request_id,
        participant_ref=participant_ref,
        idempotency_key=_bounded_idempotency_key("participant_implementation", participant_ref, implementation_ref),
        record_kind=AcesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION,
        contract_version=PARTICIPANT_IMPLEMENTATION_CONTRACT_VERSION,
        source_timestamp=source_timestamp,
        payload=payload,
        diagnostic_refs=diagnostic_refs or {},
        owner=owner,
    )
    return persist_aces_participant_runtime_record(write)


def persist_participant_runtime_record(
    *,
    request_id: UUID | str,
    participant_ref: str,
    source_timestamp: datetime,
    payload: dict[str, Any],
    diagnostic_refs: dict[str, Any] | None = None,
    owner: str = AcesParticipantRuntimeRecord.Owner.ENGINE,
) -> AcesParticipantRuntimeRecord:
    """Persist one ``participant_runtime`` sidecar record idempotently.

    Encapsulates the ``record_kind`` and idempotency-key convention for
    participant-runtime status observations so callers outside ``shared`` do
    not touch the ``AcesParticipantRuntimeRecord`` model. The idempotency key
    is deterministic in the participant ref and observation timestamp, so
    re-delivery of the same observation is a no-op (or a conflict when the
    content drifts). The contract version is fixed for this record kind
    (``PARTICIPANT_RUNTIME_CONTRACT_VERSION``); callers needing a non-default
    version use ``persist_aces_participant_runtime_record`` directly.
    """
    _reconcile_payload_identity(payload, participant_ref=participant_ref)
    write = AcesParticipantRuntimeRecordWrite(
        request_id=request_id,
        participant_ref=participant_ref,
        idempotency_key=_bounded_idempotency_key("participant_runtime", participant_ref, source_timestamp.isoformat()),
        record_kind=AcesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
        contract_version=PARTICIPANT_RUNTIME_CONTRACT_VERSION,
        source_timestamp=source_timestamp,
        payload=payload,
        diagnostic_refs=diagnostic_refs or {},
        owner=owner,
    )
    return persist_aces_participant_runtime_record(write)


def persist_participant_behavior_history_record(
    *,
    request_id: UUID | str,
    participant_ref: str,
    source_timestamp: datetime,
    payload: dict[str, Any],
    options: ParticipantRecordWriteOptions | None = None,
) -> AcesParticipantRuntimeRecord:
    """Persist one ``participant_behavior_history`` reference record idempotently (#1289).

    Records a reference to one participant behavior event (event kind + bounded
    ref + digest), never the event body. The ``event_kind`` and ``event_ref``
    that identify the event live in ``payload`` (they are required, validated
    fields); the idempotency key is derived from them plus ``participant_ref``,
    so the key can never drift from the persisted content and re-delivery of the
    same event reference is a no-op (or a conflict when the content drifts).
    Callers outside ``shared`` use this helper instead of touching the model;
    those needing a non-default contract version use
    ``persist_aces_participant_runtime_record`` directly.
    """
    opts = options or ParticipantRecordWriteOptions()
    _reconcile_payload_identity(payload, participant_ref=participant_ref)
    event_kind = _payload_identity(payload, "event_kind")
    event_ref = _payload_identity(payload, "event_ref")
    write = AcesParticipantRuntimeRecordWrite(
        request_id=request_id,
        participant_ref=participant_ref,
        idempotency_key=_bounded_idempotency_key(
            "participant_behavior_history", participant_ref, event_kind, event_ref
        ),
        record_kind=AcesParticipantRuntimeRecord.RecordKind.PARTICIPANT_BEHAVIOR_HISTORY,
        contract_version=PARTICIPANT_BEHAVIOR_HISTORY_CONTRACT_VERSION,
        source_timestamp=source_timestamp,
        payload=payload,
        diagnostic_refs=opts.diagnostic_refs or {},
        owner=opts.owner,
        range_id=opts.range_id,
        range_instance_id=opts.range_instance_id,
    )
    return persist_aces_participant_runtime_record(write)


def persist_participant_evidence_record(
    *,
    request_id: UUID | str,
    participant_ref: str,
    source_timestamp: datetime,
    payload: dict[str, Any],
    options: ParticipantRecordWriteOptions | None = None,
) -> AcesParticipantRuntimeRecord:
    """Persist one ``participant_evidence`` reference record idempotently (#1289).

    Records a reference to one piece of participant evidence (evidence kind +
    provenance source + ref + digest), never the raw material -- scripts,
    prompts, dispatch receipts, transcripts, artifacts, and terminal sessions
    stay behind their owning Shifter boundaries. The ``evidence_kind``,
    ``provenance_source``, and ``provenance_ref`` that identify the evidence live
    in ``payload`` (required, validated fields); the idempotency key is derived
    from them plus ``participant_ref``. A ``provenance_ref`` is only meaningful
    inside its ``provenance_source`` namespace, so the key spans both: two
    boundaries emitting the same local ref under different sources are distinct
    evidence, and re-delivery of the same reference is a no-op (or a conflict
    when the content drifts). Callers outside ``shared`` use this helper instead
    of touching the model; those needing a non-default contract version use
    ``persist_aces_participant_runtime_record`` directly.
    """
    opts = options or ParticipantRecordWriteOptions()
    _reconcile_payload_identity(payload, participant_ref=participant_ref)
    evidence_kind = _payload_identity(payload, "evidence_kind")
    provenance_source = _payload_identity(payload, "provenance_source")
    provenance_ref = _payload_identity(payload, "provenance_ref")
    write = AcesParticipantRuntimeRecordWrite(
        request_id=request_id,
        participant_ref=participant_ref,
        idempotency_key=_bounded_idempotency_key(
            "participant_evidence", participant_ref, evidence_kind, provenance_source, provenance_ref
        ),
        record_kind=AcesParticipantRuntimeRecord.RecordKind.PARTICIPANT_EVIDENCE,
        contract_version=PARTICIPANT_EVIDENCE_CONTRACT_VERSION,
        source_timestamp=source_timestamp,
        payload=payload,
        diagnostic_refs=opts.diagnostic_refs or {},
        owner=opts.owner,
        range_id=opts.range_id,
        range_instance_id=opts.range_instance_id,
    )
    return persist_aces_participant_runtime_record(write)
