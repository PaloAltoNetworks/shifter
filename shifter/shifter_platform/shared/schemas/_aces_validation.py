"""Generic ACES sidecar validation primitives shared across record families.

Extracted from :mod:`shared.schemas.aces_operation` (#1288) so new ACES
sidecar record families (participant-runtime, and future ones) reuse the same
secret rejection, bounded-ref, digest, timestamp, and recursive JSON
validation rules instead of copying them. Record-kind-specific vocabulary
(payload key allowlists, contract-version maps, etc.) stays in each family's
own module.

Every raising primitive accepts an ``error_cls`` keyword (default
:class:`AcesRecordError`) so each domain module can raise its own
domain-specific error subclass (for example ``AcesOperationRecordError`` or
``AcesParticipantRuntimeRecordError``) while sharing one validation
implementation.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from hashlib import sha256
from uuid import UUID

Scalar = str | int | float | bool | None
JsonValue = Scalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_REF_LEN = 512
_MAX_SCALAR_LEN = 2048
_MAX_JSON_BYTES = 65536
_FORBIDDEN_CHARS = ("\n", "\r", "\x00")
_SECRET_KEY_FRAGMENTS = (
    "access_key",
    "api_key",
    "bearer",
    "command",
    "credential",
    "flag",
    "package_body",
    "password",
    "private_key",
    "prompt",
    "provider_dump",
    "raw_payload",
    "script",
    "secret",
    "ssm_output",
    "ssh_output",
    "terraform_output",
    "token",
    "transcript",
)
_SECRET_VALUE_RE = re.compile(
    r"(-----BEGIN [A-Z ]*PRIVATE KEY-----|bearer\s+|x-amz-signature=|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16})",
    re.IGNORECASE,
)


class AcesRecordError(ValueError):
    """Raised when an ACES sidecar record violates a shared storage contract."""


def canonical_aces_payload_digest(payload: object, *, error_cls: type[Exception] = AcesRecordError) -> str:
    """Return the deterministic digest used for stored sidecar payloads."""
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise error_cls("payload must be JSON-serializable") from exc
    return "sha256:" + sha256(encoded).hexdigest()


def _reject_secret_key(path: str, key: str, *, error_cls: type[Exception] = AcesRecordError) -> None:
    """Reject field names that indicate embedded secrets or raw provider data."""
    lowered = key.lower()
    if any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS):
        raise error_cls(f"secret-bearing payload field rejected at {path}.{key}")


def _reject_secret_value(path: str, value: str, *, error_cls: type[Exception] = AcesRecordError) -> None:
    """Reject string values that match high-confidence secret patterns."""
    if _SECRET_VALUE_RE.search(value):
        raise error_cls(f"secret-bearing payload value rejected at {path}")


def _require_single_line_ref(
    name: str,
    value: object,
    *,
    required: bool,
    max_len: int = _MAX_REF_LEN,
    error_cls: type[Exception] = AcesRecordError,
) -> str:
    """Normalize bounded reference strings and reject embedded content.

    ``max_len`` defaults to the generic sidecar reference cap but callers pass a
    tighter bound when the persisted column is narrower (for example a 128-char
    ``idempotency_key``), so validation and the storage contract agree instead
    of deferring an over-length value to a database error.
    """
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise error_cls(f"{name} must be a string")
    if not value.strip():
        if required:
            raise error_cls(f"{name} is required")
        return ""
    if len(value) > max_len:
        raise error_cls(f"{name} exceeds {max_len} characters")
    if any(ch in value for ch in _FORBIDDEN_CHARS):
        raise error_cls(f"{name} must be single-line, not embedded content")
    _reject_secret_value(name, value, error_cls=error_cls)
    return value


def _require_digest(name: str, value: object, *, error_cls: type[Exception] = AcesRecordError) -> str:
    """Validate a canonical sha256 digest string."""
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise error_cls(f"{name} must be a 'sha256:<64 hex>' digest")
    return value


def _require_uuid(
    name: str, value: object, *, required: bool, error_cls: type[Exception] = AcesRecordError
) -> UUID | None:
    """Validate or coerce UUID fields while preserving optional projections."""
    if value in (None, ""):
        if required:
            raise error_cls(f"{name} is required")
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise error_cls(f"{name} must be a UUID") from exc


def _require_aware_datetime(name: str, value: object, *, error_cls: type[Exception] = AcesRecordError) -> datetime:
    """Require timezone-aware timestamps for replay comparison."""
    if not isinstance(value, datetime):
        raise error_cls(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise error_cls(f"{name} must be timezone-aware")
    return value


def _require_json_size(
    name: str, value: object, *, max_bytes: int, error_cls: type[Exception] = AcesRecordError
) -> None:
    """Enforce a canonical byte budget before recursive JSON validation."""
    try:
        encoded = json.dumps(value, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise error_cls(f"{name} must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > max_bytes:
        raise error_cls(f"{name} exceeds {max_bytes} bytes")


def _validate_json_value(path: str, value: object, *, error_cls: type[Exception] = AcesRecordError) -> JsonValue:
    """Recursively validate JSON values against the sidecar safety rules."""
    validated: JsonValue
    if isinstance(value, dict):
        validated = _validate_json_object(path, value, error_cls=error_cls)
    elif isinstance(value, list):
        validated = [
            _validate_json_value(f"{path}[{index}]", item, error_cls=error_cls) for index, item in enumerate(value)
        ]
    else:
        validated = _validate_json_scalar(path, value, error_cls=error_cls)
    return validated


def _validate_json_scalar(path: str, value: object, *, error_cls: type[Exception] = AcesRecordError) -> Scalar:
    """Validate one scalar JSON value."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _MAX_SCALAR_LEN:
            raise error_cls(f"{path} exceeds {_MAX_SCALAR_LEN} characters")
        if any(ch in value for ch in _FORBIDDEN_CHARS):
            raise error_cls(f"{path} must be single-line, not embedded content")
        _reject_secret_value(path, value, error_cls=error_cls)
        return value
    raise error_cls(f"{path} must contain JSON-compatible values")


def _validate_json_object(
    path: str, value: dict[object, object], *, error_cls: type[Exception] = AcesRecordError
) -> JsonObject:
    """Validate a JSON object and its recursively nested fields."""
    validated: JsonObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise error_cls(f"{path} keys must be strings")
        _reject_secret_key(path, key, error_cls=error_cls)
        validated[key] = _validate_json_value(f"{path}.{key}", item, error_cls=error_cls)
    return validated


#: Allowlisted, reference-only diagnostic keys shared by every ACES sidecar
#: family. Diagnostic references are bounded single-line refs, never raw logs,
#: provider dumps, or nested payloads.
DIAGNOSTIC_REF_KEYS = frozenset(
    {
        "artifact_ref",
        "error_class",
        "fingerprint",
        "log_ref",
        "provider_ref",
        "report_ref",
        "source_event_id",
        "status_reason",
        "trace_ref",
    }
)
_MAX_DIAGNOSTIC_BYTES = 4096
_MAX_DIAGNOSTIC_LIST_LEN = 32


def validate_diagnostic_refs(
    diagnostic_refs: object,
    *,
    allowed_keys: frozenset[str] = DIAGNOSTIC_REF_KEYS,
    max_bytes: int = _MAX_DIAGNOSTIC_BYTES,
    max_list_len: int = _MAX_DIAGNOSTIC_LIST_LEN,
    error_cls: type[Exception] = AcesRecordError,
) -> JsonObject:
    """Validate a bounded, allowlisted diagnostic-reference map.

    Diagnostic refs are reference-only: keys must be in ``allowed_keys`` and
    values are bounded single-line refs (or a bounded list of them). This is the
    single implementation shared by every ACES sidecar family so the
    reference-only contract cannot drift between record types.
    """
    if diagnostic_refs is None:
        return {}
    if not isinstance(diagnostic_refs, dict):
        raise error_cls("diagnostic_refs must be a JSON object")
    _require_json_size("diagnostic_refs", diagnostic_refs, max_bytes=max_bytes, error_cls=error_cls)
    validated: JsonObject = {}
    for key, value in diagnostic_refs.items():
        if not isinstance(key, str):
            raise error_cls("diagnostic_refs keys must be strings")
        if key not in allowed_keys:
            raise error_cls(f"diagnostic_refs key '{key}' is not an allowed reference key")
        if isinstance(value, list):
            if len(value) > max_list_len:
                raise error_cls(f"diagnostic_refs '{key}' list exceeds {max_list_len} items")
            validated[key] = [
                _require_single_line_ref(f"diagnostic_refs.{key}", item, required=False, error_cls=error_cls)
                for item in value
            ]
            continue
        validated[key] = _require_single_line_ref(f"diagnostic_refs.{key}", value, required=False, error_cls=error_cls)
    return validated
