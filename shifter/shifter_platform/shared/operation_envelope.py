"""Closed, versioned transport envelope for the provisioner operation boundary.

ADR-043: the engine and the separately deployed provisioner exchange operation
inputs and results as one operation-shaped envelope anchored to the canonical
``operation_id`` generation, not as ORM/table projections. This module owns the
*transport* shape and the canonical digest; the bounded operation-specific
``payload`` composes the existing persisted contracts (RangeSpec / RAES
ProvisioningPlan / ``shared.range_cells`` / ``shared.remote_access`` / …) and is
validated by those contracts, not re-modelled here.

This module stays dependency-light: the standalone provisioner image imports it
without loading Django or the platform schema graph. There is exactly one native
shared boundary error type; callers do not add a parallel exception hierarchy.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from shared.exceptions import ValidationError as OperationEnvelopeError

__all__ = [
    "ACCEPTED_CONTRACT_VERSIONS",
    "CONTRACT_KEY",
    "CONTRACT_VERSION",
    "MAX_ENVELOPE_BYTES",
    "OPERATIONS",
    "RESOURCES",
    "OperationEnvelopeError",
    "build_operation_envelope",
    "canonical_payload_digest",
    "validate_operation_envelope",
]

CONTRACT_KEY = "shifter.provisioner-operation"
# Contract version is independent of application / image release versions. Both
# producer and consumer honour a rolling compatibility window; removing an
# accepted version requires evidence no retained input or replayable result
# still uses it (ADR-043-R2/R7).
CONTRACT_VERSION = "1"
ACCEPTED_CONTRACT_VERSIONS = frozenset({"1"})

# Closed discriminators. The specific operation legal for a resource is enforced
# by the domain authorization (engine.launch_intents); the envelope only bounds
# the vocabulary so an unknown discriminator fails closed at the wire.
RESOURCES = frozenset({"range", "raes-range", "ngfw"})
# ``activate`` (#28, ADR-039-R11) hands an atomically claimed warm generation to
# its claimant with fresh, fully sanitized access. Like every other value here it
# is only a wire discriminator; engine.launch_intents authorizes which resource
# may carry it (raes-range only).
OPERATIONS = frozenset({"provision", "destroy", "pause", "resume", "deprovision", "start", "stop", "activate"})

_ENVELOPE_KEYS = frozenset({"contract_version", "operation_id", "request_id", "resource", "operation", "payload"})
_DIGEST_PREFIX = "sha256:"
# Bounded transport size; operation payloads compose reference-only contracts and
# must never carry raw provider state, so a few hundred KiB is generous.
MAX_ENVELOPE_BYTES = 262144

ContractDict = dict[str, Any]


def _require_dict(value: object, field: str) -> ContractDict:
    """Return ``value`` if it is a dict, else raise a contract error."""
    if not isinstance(value, dict):
        raise OperationEnvelopeError(f"{field} must be an object")
    return value


def _require_exact_keys(value: ContractDict, field: str) -> None:
    """Raise a contract error unless ``value`` has exactly the envelope keys."""
    actual = frozenset(value)
    unexpected = sorted(actual - _ENVELOPE_KEYS)
    if unexpected:
        raise OperationEnvelopeError(f"{field} has unexpected field(s): {', '.join(unexpected)}")
    missing = sorted(_ENVELOPE_KEYS - actual)
    if missing:
        raise OperationEnvelopeError(f"{field} is missing field(s): {', '.join(missing)}")


def _require_uuid(value: object, field: str) -> str:
    """Return the canonical string form of a UUID or raise a contract error."""
    if not isinstance(value, str):
        raise OperationEnvelopeError(f"{field} must be a UUID string")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise OperationEnvelopeError(f"{field} must be a valid UUID") from exc


def _require_choice(value: object, choices: frozenset[str], field: str) -> str:
    """Return ``value`` if it is one of ``choices``, else raise a contract error."""
    if not isinstance(value, str) or value not in choices:
        raise OperationEnvelopeError(f"{field} must be one of: {', '.join(sorted(choices))}")
    return value


def canonical_payload_digest(payload: ContractDict) -> str:
    """Return a deterministic content digest independent of key order.

    Result identity replay detection compares this digest: the same result
    identity with an equal digest is a harmless replay; an unequal digest is a
    conflict that must fail closed (ADR-043-R2). Mirrors the RAES operation-record
    digest so both sides agree byte-for-byte.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _DIGEST_PREFIX + hashlib.sha256(encoded).hexdigest()


def validate_operation_envelope(envelope: object) -> ContractDict:
    """Validate the transport envelope shape and return the normalized copy.

    Closed on keys, types, enum values, UUID form, and serialized byte size. This
    is the wire contract only; the bounded ``payload`` is validated by the
    operation-specific contract it composes, not here.
    """
    obj = _require_dict(envelope, "operation envelope")
    _require_exact_keys(obj, "operation envelope")

    version = obj["contract_version"]
    if version not in ACCEPTED_CONTRACT_VERSIONS:
        raise OperationEnvelopeError(
            f"operation envelope contract_version must be one of: {', '.join(sorted(ACCEPTED_CONTRACT_VERSIONS))}"
        )

    normalized: ContractDict = {
        "contract_version": version,
        "operation_id": _require_uuid(obj["operation_id"], "operation envelope operation_id"),
        "request_id": _require_uuid(obj["request_id"], "operation envelope request_id"),
        "resource": _require_choice(obj["resource"], RESOURCES, "operation envelope resource"),
        "operation": _require_choice(obj["operation"], OPERATIONS, "operation envelope operation"),
        "payload": _require_dict(obj["payload"], "operation envelope payload"),
    }

    serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(serialized) > MAX_ENVELOPE_BYTES:
        raise OperationEnvelopeError(f"operation envelope exceeds {MAX_ENVELOPE_BYTES} bytes ({len(serialized)} bytes)")
    return normalized


def build_operation_envelope(
    *,
    operation_id: str | UUID,
    request_id: str | UUID,
    resource: str,
    operation: str,
    payload: ContractDict,
    contract_version: str = CONTRACT_VERSION,
) -> ContractDict:
    """Construct and validate an operation envelope in one step."""
    return validate_operation_envelope(
        {
            "contract_version": contract_version,
            "operation_id": str(operation_id),
            "request_id": str(request_id),
            "resource": resource,
            "operation": operation,
            "payload": payload,
        }
    )
