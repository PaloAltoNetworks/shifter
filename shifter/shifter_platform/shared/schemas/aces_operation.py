"""Shared-native validation for ACES operation sidecar records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from shared.aces.contracts import (
    OPERATION_RECORD_KIND_TO_CONTRACT_VERSIONS,
    SHIFTER_BACKEND_PROFILE,
)
from shared.schemas._aces_validation import (
    DIAGNOSTIC_REF_KEYS,
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

# ``DIAGNOSTIC_REF_KEYS`` is re-exported from the shared validation module so
# existing importers (for example ``shared.aces.status``) keep working while the
# canonical definition lives in one place.
__all__ = [
    "DIAGNOSTIC_REF_KEYS",
    "AcesOperationRecordData",
    "AcesOperationRecordError",
    "ValidatedAcesOperationRecord",
    "canonical_aces_payload_digest",
    "validate_aces_operation_record",
]

EXECUTION_PLAN_REF_KEYS = frozenset(
    {
        "execution_plan_ref",
        "execution_plan_digest",
        "generated_at",
        "notes",
        "tool",
        "tool_version",
    }
)
PAYLOAD_KEYS_BY_RECORD_KIND = {
    "operation_receipt": frozenset(
        {
            "accepted",
            "diagnostic_refs",
            "operation_id",
            "receipt_digest",
            "receipt_ref",
            "request_id",
            "source_timestamp",
            "status",
        }
    ),
    "operation_status": frozenset(
        {
            "diagnostic_refs",
            "operation_id",
            "request_id",
            "source_timestamp",
            "status",
            "status_reason",
            "updated_at",
        }
    ),
    "runtime_snapshot": frozenset(
        {
            "captured_at",
            "diagnostic_refs",
            "operation_id",
            "request_id",
            "resources",
            "snapshot_digest",
            "snapshot_ref",
            "status",
        }
    ),
    "execution_plan_ref": EXECUTION_PLAN_REF_KEYS,
}
REQUIRED_PAYLOAD_KEYS_BY_RECORD_KIND = {
    "operation_receipt": frozenset({"operation_id"}),
    "operation_status": frozenset({"operation_id", "status"}),
    "runtime_snapshot": frozenset({"operation_id", "resources"}),
    "execution_plan_ref": frozenset({"execution_plan_ref"}),
}
OWNER_VALUES = frozenset({"shared", "engine", "provisioner", "cms"})

_MAX_JSON_BYTES = 65536


class AcesOperationRecordError(AcesRecordError):
    """Raised when an ACES operation sidecar record violates the storage contract."""


@dataclass(frozen=True)
class AcesOperationRecordData:
    """Bundle of sidecar fields validated together at the model/service boundary."""

    request_id: UUID
    operation_id: str
    idempotency_key: str
    record_kind: str
    contract_kind: str
    contract_version: str
    contract_profile: str
    source_timestamp: datetime
    payload_digest: str
    payload: object
    diagnostic_refs: object = None
    range_id: UUID | None = None
    owner: str = "shared"


@dataclass(frozen=True)
class ValidatedAcesOperationRecord:
    """Normalized JSON fields safe to persist."""

    payload: JsonObject
    diagnostic_refs: JsonObject


def _validate_payload(record_kind: str, payload: object) -> JsonObject:
    """Validate record-kind-specific sidecar payload shape and contents."""
    if not isinstance(payload, dict):
        raise AcesOperationRecordError("payload must be a JSON object")
    for key in payload:
        if not isinstance(key, str):
            raise AcesOperationRecordError("payload keys must be strings")
        _reject_secret_key("payload", key, error_cls=AcesOperationRecordError)
    allowed_keys = PAYLOAD_KEYS_BY_RECORD_KIND[record_kind]
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        if record_kind == "execution_plan_ref":
            raise AcesOperationRecordError("execution_plan_ref payload is reference-only")
        raise AcesOperationRecordError(
            f"payload keys {sorted(extra_keys)} are not allowed for record_kind {record_kind!r}"
        )
    missing_keys = REQUIRED_PAYLOAD_KEYS_BY_RECORD_KIND[record_kind] - set(payload)
    if missing_keys:
        raise AcesOperationRecordError(
            f"payload keys {sorted(missing_keys)} are required for record_kind {record_kind!r}"
        )
    _require_json_size("payload", payload, max_bytes=_MAX_JSON_BYTES, error_cls=AcesOperationRecordError)
    validated = _validate_json_value("payload", payload, error_cls=AcesOperationRecordError)
    if not isinstance(validated, dict):
        raise AcesOperationRecordError("payload must be a JSON object")
    if record_kind == "execution_plan_ref":
        _require_single_line_ref(
            "payload.execution_plan_ref",
            validated.get("execution_plan_ref"),
            required=True,
            error_cls=AcesOperationRecordError,
        )
        if "execution_plan_digest" in validated:
            _require_digest(
                "payload.execution_plan_digest", validated["execution_plan_digest"], error_cls=AcesOperationRecordError
            )
    return validated


def _validate_record_kind_contract(record_kind: str, contract_version: str) -> None:
    """Validate that a record kind and contract version are compatible."""
    versions = OPERATION_RECORD_KIND_TO_CONTRACT_VERSIONS.get(record_kind)
    if versions is None:
        raise AcesOperationRecordError(
            f"record_kind must be one of {sorted(OPERATION_RECORD_KIND_TO_CONTRACT_VERSIONS)}"
        )
    if contract_version not in versions:
        raise AcesOperationRecordError(
            f"contract_version {contract_version!r} is not valid for record_kind {record_kind!r}"
        )


def validate_aces_operation_record(record: AcesOperationRecordData) -> ValidatedAcesOperationRecord:
    """Validate an ACES operation sidecar record before persistence."""

    _require_uuid("request_id", record.request_id, required=True, error_cls=AcesOperationRecordError)
    _require_uuid("range_id", record.range_id, required=False, error_cls=AcesOperationRecordError)
    _require_single_line_ref("operation_id", record.operation_id, required=True, error_cls=AcesOperationRecordError)
    _require_single_line_ref(
        "idempotency_key", record.idempotency_key, required=True, error_cls=AcesOperationRecordError
    )
    if record.contract_kind != "aces":
        raise AcesOperationRecordError("contract_kind must be 'aces'")
    if record.contract_profile != SHIFTER_BACKEND_PROFILE:
        raise AcesOperationRecordError(f"contract_profile must be {SHIFTER_BACKEND_PROFILE!r}")
    _validate_record_kind_contract(record.record_kind, record.contract_version)
    if record.owner not in OWNER_VALUES:
        raise AcesOperationRecordError(f"owner must be one of {sorted(OWNER_VALUES)}")
    _require_aware_datetime("source_timestamp", record.source_timestamp, error_cls=AcesOperationRecordError)
    _require_digest("payload_digest", record.payload_digest, error_cls=AcesOperationRecordError)
    payload = _validate_payload(record.record_kind, record.payload)
    expected_digest = canonical_aces_payload_digest(payload, error_cls=AcesOperationRecordError)
    if record.payload_digest != expected_digest:
        raise AcesOperationRecordError("payload_digest must match canonical payload digest")
    return ValidatedAcesOperationRecord(
        payload=payload,
        diagnostic_refs=validate_diagnostic_refs(record.diagnostic_refs, error_cls=AcesOperationRecordError),
    )
