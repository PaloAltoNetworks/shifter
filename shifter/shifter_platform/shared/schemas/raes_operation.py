"""Shared-native validation for RAES operation sidecar records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from shared.raes.contracts import (
    OPERATION_RECORD_KIND_TO_CONTRACT_VERSIONS,
    SHIFTER_BACKEND_PROFILE,
)
from shared.schemas._raes_validation import (
    DIAGNOSTIC_REF_KEYS,
    JsonObject,
    RaesRecordError,
    _reject_secret_key,
    _require_aware_datetime,
    _require_digest,
    _require_json_size,
    _require_single_line_ref,
    _require_uuid,
    _validate_json_value,
    canonical_raes_payload_digest,
    validate_diagnostic_refs,
)

# ``DIAGNOSTIC_REF_KEYS`` is re-exported from the shared validation module so
# existing importers (for example ``shared.raes.status``) keep working while the
# canonical definition lives in one place.
__all__ = [
    "DIAGNOSTIC_REF_KEYS",
    "RaesOperationRecordData",
    "RaesOperationRecordError",
    "ValidatedRaesOperationRecord",
    "canonical_raes_payload_digest",
    "validate_raes_operation_record",
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
_RUNTIME_RESOURCE_KEYS = frozenset({"address", "resource_type", "status"})
_TOPOLOGY_RESOURCE_TYPES = frozenset({"network", "node"})
_COMPOSITION_RESOURCE_TYPES = frozenset(
    {"content-placement", "account-placement", "feature-binding", "domain-controller-placement"}
)


class RaesOperationRecordError(RaesRecordError):
    """Raised when an RAES operation sidecar record violates the storage contract."""


def _validated_runtime_resource(index: int, resource: object) -> tuple[str, object, object]:
    """Validate one resource entry's exact shape and return its typed fields."""
    if not isinstance(resource, dict) or set(resource) != _RUNTIME_RESOURCE_KEYS:
        raise RaesOperationRecordError(
            "runtime_snapshot resource must contain exactly address, resource_type, and status"
        )
    address = resource.get("address")
    if not isinstance(address, str):
        raise RaesOperationRecordError("runtime_snapshot resource address must be a string")
    _require_single_line_ref(
        f"payload.resources[{index}].address",
        address,
        required=True,
        error_cls=RaesOperationRecordError,
    )
    return address, resource.get("resource_type"), resource.get("status")


def _runtime_resource_state_is_valid(resource_type: object, status: object) -> bool:
    """Return whether a resource type carries its one allowed evidence status."""
    if not isinstance(resource_type, str) or not isinstance(status, str):
        return False
    return (resource_type in _TOPOLOGY_RESOURCE_TYPES and status == "provisioned") or (
        resource_type in _COMPOSITION_RESOURCE_TYPES and status == "verified"
    )


def _validate_runtime_snapshot_resources(payload: JsonObject) -> None:
    """Require the bounded topology/composition evidence entry contract."""
    resources = payload.get("resources")
    if not isinstance(resources, list):
        raise RaesOperationRecordError("runtime_snapshot resources must be a list")
    seen: set[str] = set()
    for index, resource in enumerate(resources):
        address, resource_type, status = _validated_runtime_resource(index, resource)
        if address in seen:
            raise RaesOperationRecordError("runtime_snapshot contains a duplicate resource address")
        seen.add(address)
        if not _runtime_resource_state_is_valid(resource_type, status):
            raise RaesOperationRecordError("runtime_snapshot resource has an invalid resource_type/status pair")


@dataclass(frozen=True)
class RaesOperationRecordData:
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
class ValidatedRaesOperationRecord:
    """Normalized JSON fields safe to persist."""

    payload: JsonObject
    diagnostic_refs: JsonObject


def _validate_payload(record_kind: str, payload: object) -> JsonObject:
    """Validate record-kind-specific sidecar payload shape and contents."""
    if not isinstance(payload, dict):
        raise RaesOperationRecordError("payload must be a JSON object")
    for key in payload:
        if not isinstance(key, str):
            raise RaesOperationRecordError("payload keys must be strings")
        _reject_secret_key("payload", key, error_cls=RaesOperationRecordError)
    allowed_keys = PAYLOAD_KEYS_BY_RECORD_KIND[record_kind]
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        if record_kind == "execution_plan_ref":
            raise RaesOperationRecordError("execution_plan_ref payload is reference-only")
        raise RaesOperationRecordError(
            f"payload keys {sorted(extra_keys)} are not allowed for record_kind {record_kind!r}"
        )
    missing_keys = REQUIRED_PAYLOAD_KEYS_BY_RECORD_KIND[record_kind] - set(payload)
    if missing_keys:
        raise RaesOperationRecordError(
            f"payload keys {sorted(missing_keys)} are required for record_kind {record_kind!r}"
        )
    _require_json_size("payload", payload, max_bytes=_MAX_JSON_BYTES, error_cls=RaesOperationRecordError)
    validated = _validate_json_value("payload", payload, error_cls=RaesOperationRecordError)
    if not isinstance(validated, dict):
        raise RaesOperationRecordError("payload must be a JSON object")
    if record_kind == "execution_plan_ref":
        _require_single_line_ref(
            "payload.execution_plan_ref",
            validated.get("execution_plan_ref"),
            required=True,
            error_cls=RaesOperationRecordError,
        )
        if "execution_plan_digest" in validated:
            _require_digest(
                "payload.execution_plan_digest", validated["execution_plan_digest"], error_cls=RaesOperationRecordError
            )
    elif record_kind == "runtime_snapshot":
        _validate_runtime_snapshot_resources(validated)
    return validated


def _validate_record_kind_contract(record_kind: str, contract_version: str) -> None:
    """Validate that a record kind and contract version are compatible."""
    versions = OPERATION_RECORD_KIND_TO_CONTRACT_VERSIONS.get(record_kind)
    if versions is None:
        raise RaesOperationRecordError(
            f"record_kind must be one of {sorted(OPERATION_RECORD_KIND_TO_CONTRACT_VERSIONS)}"
        )
    if contract_version not in versions:
        raise RaesOperationRecordError(
            f"contract_version {contract_version!r} is not valid for record_kind {record_kind!r}"
        )


def validate_raes_operation_record(record: RaesOperationRecordData) -> ValidatedRaesOperationRecord:
    """Validate an RAES operation sidecar record before persistence."""

    _require_uuid("request_id", record.request_id, required=True, error_cls=RaesOperationRecordError)
    _require_uuid("range_id", record.range_id, required=False, error_cls=RaesOperationRecordError)
    _require_single_line_ref("operation_id", record.operation_id, required=True, error_cls=RaesOperationRecordError)
    _require_single_line_ref(
        "idempotency_key", record.idempotency_key, required=True, error_cls=RaesOperationRecordError
    )
    if record.contract_kind != "raes":
        raise RaesOperationRecordError("contract_kind must be 'raes'")
    if record.contract_profile != SHIFTER_BACKEND_PROFILE:
        raise RaesOperationRecordError(f"contract_profile must be {SHIFTER_BACKEND_PROFILE!r}")
    _validate_record_kind_contract(record.record_kind, record.contract_version)
    if record.owner not in OWNER_VALUES:
        raise RaesOperationRecordError(f"owner must be one of {sorted(OWNER_VALUES)}")
    _require_aware_datetime("source_timestamp", record.source_timestamp, error_cls=RaesOperationRecordError)
    _require_digest("payload_digest", record.payload_digest, error_cls=RaesOperationRecordError)
    payload = _validate_payload(record.record_kind, record.payload)
    expected_digest = canonical_raes_payload_digest(payload, error_cls=RaesOperationRecordError)
    if record.payload_digest != expected_digest:
        raise RaesOperationRecordError("payload_digest must match canonical payload digest")
    return ValidatedRaesOperationRecord(
        payload=payload,
        diagnostic_refs=validate_diagnostic_refs(record.diagnostic_refs, error_cls=RaesOperationRecordError),
    )
