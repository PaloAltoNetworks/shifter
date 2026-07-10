"""Shared-native validation for ACES participant-runtime sidecar records (#1288).

Mirrors :mod:`shared.schemas.aces_operation` (the incumbent
:class:`shared.models.AcesOperationRecord` validation pattern), reusing the
generic primitives extracted to :mod:`shared.schemas._aces_validation`. This
is the first participant-runtime storage slice: it validates
``participant_implementation`` and ``participant_runtime`` sidecar records
before persistence. It does not move lifecycle, access, scoring, or runtime
authority out of existing product tables/services (see
``docs/architecture/aces-participant-runtime-api-sidecars-preflight-1288.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from shared.aces.contracts import (
    PARTICIPANT_RECORD_KIND_TO_CONTRACT_VERSIONS,
    SHIFTER_BACKEND_PROFILE,
    SHIFTER_SUPPORTED_PARTICIPANT_RUNTIME_PROFILES,
)
from shared.schemas._aces_validation import (
    AcesRecordError,
    JsonObject,
    _reject_secret_key,
    _require_aware_datetime,
    _require_digest,
    _require_json_size,
    _require_single_line_ref,
    _require_uuid,
    _validate_json_value,
    canonical_aces_payload_digest,
    validate_diagnostic_refs,
)

PAYLOAD_KEYS_BY_RECORD_KIND = {
    "participant_implementation": frozenset(
        {
            "backend_name",
            "capability_refs",
            "implementation_digest",
            "implementation_ref",
            "participant_ref",
            "request_id",
            "source_timestamp",
            "status",
        }
    ),
    "participant_runtime": frozenset(
        {
            "participant_ref",
            "request_id",
            "runtime_digest",
            "runtime_ref",
            "source_timestamp",
            "status",
            "status_reason",
            "updated_at",
        }
    ),
    "participant_behavior_history": frozenset(
        {
            "event_digest",
            "event_kind",
            "event_ref",
            "operation_id",
            "participant_ref",
            "request_id",
            "sequence",
            "source_timestamp",
            "status",
            "status_reason",
        }
    ),
    "participant_evidence": frozenset(
        {
            "artifact_digest",
            "artifact_ref",
            "capture_profile",
            "evidence_kind",
            "operation_id",
            "operation_record_id",
            "participant_ref",
            "provenance_ref",
            "provenance_source",
            "receipt_ref",
            "redaction_policy",
            "request_id",
            "source_timestamp",
        }
    ),
}
REQUIRED_PAYLOAD_KEYS_BY_RECORD_KIND = {
    "participant_implementation": frozenset({"participant_ref", "implementation_ref"}),
    "participant_runtime": frozenset({"participant_ref", "status"}),
    "participant_behavior_history": frozenset({"participant_ref", "event_kind", "event_ref"}),
    "participant_evidence": frozenset(
        {
            "participant_ref",
            "evidence_kind",
            "capture_profile",
            "provenance_source",
            "provenance_ref",
            "redaction_policy",
        }
    ),
}

#: Reference-oriented evidence vocabularies (#1289). Small, validated frozensets;
#: the extensibility seam for a new evidence class / capture profile / provenance
#: boundary is a new frozenset member, mirroring the profile-version seam.
EVIDENCE_KIND_VALUES = frozenset(
    {
        "script_input",
        "prompt_input",
        "dispatch_receipt",
        "transcript_ref",
        "artifact_ref",
        "terminal_session_ref",
        "manual_evidence",
    }
)
CAPTURE_PROFILE_VALUES = frozenset({"reference_only", "digest_only"})
PROVENANCE_SOURCE_VALUES = frozenset(
    {
        "script_execution_context",
        "upload_inspection",
        "object_storage",
        "terminal_session",
        "ctf_attachment",
        "operation_sidecar",
        "manual",
    }
)
REDACTION_POLICY_VALUES = frozenset({"reference_only"})

#: Behavior-history event classes (#1289). References to participant behavior
#: events (dispatch, script/prompt use, transcript/artifact production, range
#: events), never the event bodies.
BEHAVIOR_EVENT_KIND_VALUES = frozenset(
    {
        "command_dispatched",
        "script_executed",
        "prompt_issued",
        "transcript_recorded",
        "artifact_produced",
        "terminal_session",
        "range_event",
        "manual_note",
    }
)

#: Component boundaries permitted to own a participant-runtime sidecar write.
OWNER_VALUES = frozenset({"shared", "engine", "provisioner", "cms", "ctf"})

#: Small validated vocabularies; single value today, extensibility seam for
#: later retention/redaction policies (per preflight #1288).
RETENTION_CLASS_VALUES = frozenset({"default"})
REDACTION_STATE_VALUES = frozenset({"sanitized"})

_MAX_JSON_BYTES = 65536
#: Column-aligned caps (see ``shared.models.AcesParticipantRuntimeRecord``): the
#: validator rejects over-length values instead of deferring to a database error.
_MAX_PARTICIPANT_REF_LEN = 256
_MAX_IDEMPOTENCY_KEY_LEN = 128


class AcesParticipantRuntimeRecordError(AcesRecordError):
    """Raised when an ACES participant-runtime sidecar record violates the storage contract."""


@dataclass(frozen=True)
class AcesParticipantRuntimeRecordData:
    """Bundle of sidecar fields validated together at the model/service boundary."""

    request_id: UUID
    participant_ref: str
    idempotency_key: str
    record_kind: str
    contract_kind: str
    contract_version: str
    contract_profile: str
    participant_runtime_profile: str
    source_timestamp: datetime
    payload_digest: str
    payload: object
    diagnostic_refs: object = None
    range_id: UUID | None = None
    range_instance_id: UUID | None = None
    owner: str = "shared"
    retention_class: str = "default"
    redaction_state: str = "sanitized"


@dataclass(frozen=True)
class ValidatedAcesParticipantRuntimeRecord:
    """Normalized JSON fields safe to persist."""

    payload: JsonObject
    diagnostic_refs: JsonObject


def _validate_payload(record_kind: str, payload: object) -> JsonObject:
    """Validate record-kind-specific sidecar payload shape and contents."""
    if not isinstance(payload, dict):
        raise AcesParticipantRuntimeRecordError("payload must be a JSON object")
    for key in payload:
        if not isinstance(key, str):
            raise AcesParticipantRuntimeRecordError("payload keys must be strings")
        _reject_secret_key("payload", key, error_cls=AcesParticipantRuntimeRecordError)
    allowed_keys = PAYLOAD_KEYS_BY_RECORD_KIND[record_kind]
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise AcesParticipantRuntimeRecordError(
            f"payload keys {sorted(extra_keys)} are not allowed for record_kind {record_kind!r}"
        )
    missing_keys = REQUIRED_PAYLOAD_KEYS_BY_RECORD_KIND[record_kind] - set(payload)
    if missing_keys:
        raise AcesParticipantRuntimeRecordError(
            f"payload keys {sorted(missing_keys)} are required for record_kind {record_kind!r}"
        )
    _require_json_size("payload", payload, max_bytes=_MAX_JSON_BYTES, error_cls=AcesParticipantRuntimeRecordError)
    validated = _validate_json_value("payload", payload, error_cls=AcesParticipantRuntimeRecordError)
    if not isinstance(validated, dict):
        raise AcesParticipantRuntimeRecordError("payload must be a JSON object")
    field_validator = _FIELD_VALIDATORS_BY_RECORD_KIND.get(record_kind)
    if field_validator is not None:
        field_validator(validated)
    return validated


def _require_enum(name: str, value: object, allowed: frozenset[str]) -> None:
    """Reject a payload field whose value is outside a small validated vocabulary."""
    if value not in allowed:
        raise AcesParticipantRuntimeRecordError(f"{name} must be one of {sorted(allowed)}")


#: Optional evidence ref fields validated as bounded single-line refs when present
#: (``provenance_ref`` is required and validated separately).
_EVIDENCE_OPTIONAL_REF_FIELDS = ("artifact_ref", "receipt_ref", "operation_id", "operation_record_id")

#: Evidence kinds that point at mutable external material (a script, prompt,
#: transcript, artifact, or terminal session). These MUST pin the referenced
#: material with an ``artifact_digest`` so a ref cannot be silently swapped;
#: ``dispatch_receipt`` (an immutable operation-sidecar receipt) and
#: ``manual_evidence`` do not.
_EVIDENCE_KINDS_REQUIRING_DIGEST = frozenset(
    {"script_input", "prompt_input", "transcript_ref", "artifact_ref", "terminal_session_ref"}
)


def _validate_evidence_fields(payload: JsonObject) -> None:
    """Validate ``participant_evidence`` reference-profile fields (#1289).

    Enum vocabularies are checked, and every ref-bearing field is validated as a
    bounded single-line reference so raw prompt/script/transcript/provider bodies
    (multi-line or secret-shaped values) cannot enter an allowed ref field even
    though the key is allowlisted. Mutable-material evidence kinds must pin the
    reference with a digest.
    """
    _require_enum("evidence_kind", payload.get("evidence_kind"), EVIDENCE_KIND_VALUES)
    _require_enum("capture_profile", payload.get("capture_profile"), CAPTURE_PROFILE_VALUES)
    _require_enum("provenance_source", payload.get("provenance_source"), PROVENANCE_SOURCE_VALUES)
    _require_enum("redaction_policy", payload.get("redaction_policy"), REDACTION_POLICY_VALUES)
    _require_single_line_ref(
        "provenance_ref", payload.get("provenance_ref"), required=True, error_cls=AcesParticipantRuntimeRecordError
    )
    for field in _EVIDENCE_OPTIONAL_REF_FIELDS:
        if field in payload:
            _require_single_line_ref(field, payload[field], required=False, error_cls=AcesParticipantRuntimeRecordError)
    if "artifact_digest" in payload:
        _require_digest("artifact_digest", payload["artifact_digest"], error_cls=AcesParticipantRuntimeRecordError)
    if payload.get("evidence_kind") in _EVIDENCE_KINDS_REQUIRING_DIGEST and "artifact_digest" not in payload:
        raise AcesParticipantRuntimeRecordError(
            f"artifact_digest is required for evidence_kind {payload.get('evidence_kind')!r}"
        )


def _validate_behavior_history_fields(payload: JsonObject) -> None:
    """Validate ``participant_behavior_history`` reference fields (#1289).

    ``event_ref`` and the optional ``operation_id`` are validated as bounded
    single-line references so behavior events are cited by id, never by body.
    """
    _require_enum("event_kind", payload.get("event_kind"), BEHAVIOR_EVENT_KIND_VALUES)
    _require_single_line_ref(
        "event_ref", payload.get("event_ref"), required=True, error_cls=AcesParticipantRuntimeRecordError
    )
    if "operation_id" in payload:
        _require_single_line_ref(
            "operation_id", payload["operation_id"], required=False, error_cls=AcesParticipantRuntimeRecordError
        )
    if "event_digest" in payload:
        _require_digest("event_digest", payload["event_digest"], error_cls=AcesParticipantRuntimeRecordError)
    if "sequence" in payload:
        sequence = payload["sequence"]
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise AcesParticipantRuntimeRecordError("sequence must be a non-negative integer")


#: Per-record-kind payload field validators layered on top of the generic
#: allowlist/secret/size checks. Record kinds without an entry (the #1288 base
#: kinds) keep their allowlist-only validation unchanged.
_FIELD_VALIDATORS_BY_RECORD_KIND = {
    "participant_evidence": _validate_evidence_fields,
    "participant_behavior_history": _validate_behavior_history_fields,
}


def _validate_record_kind_contract(record_kind: str, contract_version: str) -> None:
    """Validate that a record kind and contract version are compatible."""
    versions = PARTICIPANT_RECORD_KIND_TO_CONTRACT_VERSIONS.get(record_kind)
    if versions is None:
        raise AcesParticipantRuntimeRecordError(
            f"record_kind must be one of {sorted(PARTICIPANT_RECORD_KIND_TO_CONTRACT_VERSIONS)}"
        )
    if contract_version not in versions:
        raise AcesParticipantRuntimeRecordError(
            f"contract_version {contract_version!r} is not valid for record_kind {record_kind!r}"
        )


def validate_aces_participant_runtime_record(
    record: AcesParticipantRuntimeRecordData,
) -> ValidatedAcesParticipantRuntimeRecord:
    """Validate an ACES participant-runtime sidecar record before persistence."""

    _require_uuid("request_id", record.request_id, required=True, error_cls=AcesParticipantRuntimeRecordError)
    _require_uuid("range_id", record.range_id, required=False, error_cls=AcesParticipantRuntimeRecordError)
    _require_uuid(
        "range_instance_id", record.range_instance_id, required=False, error_cls=AcesParticipantRuntimeRecordError
    )
    _require_single_line_ref(
        "participant_ref",
        record.participant_ref,
        required=True,
        max_len=_MAX_PARTICIPANT_REF_LEN,
        error_cls=AcesParticipantRuntimeRecordError,
    )
    _require_single_line_ref(
        "idempotency_key",
        record.idempotency_key,
        required=True,
        max_len=_MAX_IDEMPOTENCY_KEY_LEN,
        error_cls=AcesParticipantRuntimeRecordError,
    )
    if record.contract_kind != "aces":
        raise AcesParticipantRuntimeRecordError("contract_kind must be 'aces'")
    if record.contract_profile != SHIFTER_BACKEND_PROFILE:
        raise AcesParticipantRuntimeRecordError(f"contract_profile must be {SHIFTER_BACKEND_PROFILE!r}")
    if record.participant_runtime_profile not in SHIFTER_SUPPORTED_PARTICIPANT_RUNTIME_PROFILES:
        raise AcesParticipantRuntimeRecordError(
            f"participant_runtime_profile must be one of {sorted(SHIFTER_SUPPORTED_PARTICIPANT_RUNTIME_PROFILES)}"
        )
    _validate_record_kind_contract(record.record_kind, record.contract_version)
    if record.owner not in OWNER_VALUES:
        raise AcesParticipantRuntimeRecordError(f"owner must be one of {sorted(OWNER_VALUES)}")
    if record.retention_class not in RETENTION_CLASS_VALUES:
        raise AcesParticipantRuntimeRecordError(f"retention_class must be one of {sorted(RETENTION_CLASS_VALUES)}")
    if record.redaction_state not in REDACTION_STATE_VALUES:
        raise AcesParticipantRuntimeRecordError(f"redaction_state must be one of {sorted(REDACTION_STATE_VALUES)}")
    _require_aware_datetime("source_timestamp", record.source_timestamp, error_cls=AcesParticipantRuntimeRecordError)
    _require_digest("payload_digest", record.payload_digest, error_cls=AcesParticipantRuntimeRecordError)
    payload = _validate_payload(record.record_kind, record.payload)
    expected_digest = canonical_aces_payload_digest(payload, error_cls=AcesParticipantRuntimeRecordError)
    if record.payload_digest != expected_digest:
        raise AcesParticipantRuntimeRecordError("payload_digest must match canonical payload digest")
    return ValidatedAcesParticipantRuntimeRecord(
        payload=payload,
        diagnostic_refs=validate_diagnostic_refs(record.diagnostic_refs, error_cls=AcesParticipantRuntimeRecordError),
    )
