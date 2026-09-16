"""Closed payload shapes for the operation-result contract (ADR-043).

Split out of ``operation_results.py`` (Sonar S104), which grew past the
file-size budget when the RAES family was added in phase 5 (#1837). The seam is
deliberate rather than arbitrary: this module owns *what a result payload looks
like and how it is validated*, while ``operation_results`` owns *which steps
exist for a (resource, operation), what order they may arrive in, and how a
result is identified*.

Dependencies point one way -- ``operation_results`` imports this module, never
the reverse -- so the step tables can compose these shapes without a cycle.

Dependency-light on purpose: the standalone provisioner image imports this
without Django or the platform schema graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from shared.enums import ResourceStatus
from shared.exceptions import ValidationError as OperationResultError
from shared.operation_result_members import _parse_raes_member
from shared.raes.status import RAES_OPERATION_STATES, RAES_STATE_SUCCEEDED

__all__ = [
    "MAX_DIAGNOSTIC_CHARS",
    "MAX_INSTANCE_OUTCOMES",
    "MAX_RAES_MEMBERS",
    "MAX_SNAPSHOT_RESOURCES",
    "NGFW_STATE_KEYS",
    "PARSERS",
    "REASON_CODES",
    "SNAPSHOT_ENTRY_KEYS",
    "OperationResultError",
    "Shape",
    "StepSpec",
    "failure",
    "progress",
    "raes_progress",
    "raes_ready",
    "raes_snapshot",
    "raes_success",
    "success",
]


class Shape(StrEnum):
    """Which closed payload parser a step uses."""

    INSTANCES = "instances"
    NGFW = "ngfw"
    RANGE_TERMINAL = "range_terminal"
    FAILURE = "failure"
    RAES_OPERATION = "raes_operation"
    RAES_SNAPSHOT = "raes_snapshot"
    RAES_READY = "raes_ready"


# Result kinds mirror ``engine.models.OperationResultKind`` without importing
# Django; the applier cross-checks the stored kind against this table.
_RESOURCE_STATE = "RESOURCE_STATE"
_TERMINAL_SUCCESS = "TERMINAL_SUCCESS"
_TERMINAL_FAILURE = "TERMINAL_FAILURE"

# Field label used in every parser error, so a caller can tell which contract
# rejected the value.
_PAYLOAD_FIELD = "result payload"

# Bounded per ADR-043: results carry summaries, never snapshots.
MAX_INSTANCE_OUTCOMES = 256
MAX_DIAGNOSTIC_CHARS = 512
# The RAES runtime snapshot is already byte-bounded by ``raes_snapshot`` before
# it is published; this is the transport-side count bound so an oversized
# topology fails at the wire rather than at the sidecar's size validator.
MAX_SNAPSHOT_RESOURCES = 512

# Exactly the bounded fields ``raes_snapshot.snapshot_resources`` emits. RAES
# addresses are compiled handles carrying no authored values or infrastructure
# detail, which is what makes the snapshot safe for the redacted sidecar; an IP,
# hostname, or provider id appearing here would defeat that.
SNAPSHOT_ENTRY_KEYS = frozenset({"address", "resource_type", "status"})

# Upper bound on realized members in one RAES terminal-ready result (#1710). The
# bounded per-member key set and its fail-closed parser live in
# ``operation_result_members`` (split out for Sonar S104).
MAX_RAES_MEMBERS = 256

# Closed failure vocabulary. An authored code, never an exception string.
REASON_CODES = frozenset(
    {
        "cloud_operation_failed",
        "cloud_timeout",
        "dependency_unavailable",
        "invalid_state",
        "internal_error",
        # ADR-039 unsupported-capability (issue #614): the range's realized asset
        # mix cannot be losslessly paused/resumed on its substrate adapter, so the
        # operation is refused before any mutation rather than faking success.
        "unsupported_capability",
    }
)

# The provider-neutral NGFW state already shaped by
# ``ngfw_terraform_state._build_provider_state``. Raw Terraform output is not
# transported; only these normalized fields are.
NGFW_STATE_KEYS = frozenset(
    {
        "cloud_provider",
        "route_next_hop_ip",
        "attachment_mode",
        "data_attachment_id",
        "attached_ranges",
        "provider_metadata",
    }
)


@dataclass(frozen=True)
class StepSpec:
    """Declared properties of one step within one ``(resource, operation)``.

    ``status`` carries two meanings depending on the shape. For the families
    whose payload reports a ``ResourceStatus`` directly it *pins* that reported
    value. For the RAES shapes -- whose payload reports a coarse RAES operation
    state instead -- it is the range status the step projects, or ``None`` when
    the step is evidence only and must not move lifecycle state. ``raes_state``
    is what pins the RAES payload.
    """

    rank: int
    result_kind: str
    shape: Shape
    status: ResourceStatus | None
    terminal: bool = False
    raes_state: str | None = None


def progress(rank: int, shape: Shape, status: ResourceStatus) -> StepSpec:
    """Declare a non-terminal progress step."""
    return StepSpec(rank=rank, result_kind=_RESOURCE_STATE, shape=shape, status=status)


def success(rank: int, shape: Shape, status: ResourceStatus) -> StepSpec:
    """Declare a terminal-success step."""
    return StepSpec(rank=rank, result_kind=_TERMINAL_SUCCESS, shape=shape, status=status, terminal=True)


def failure(rank: int) -> StepSpec:
    """Declare a terminal-failure step."""
    return StepSpec(rank=rank, result_kind=_TERMINAL_FAILURE, shape=Shape.FAILURE, status=None, terminal=True)


def raes_progress(rank: int, raes_state: str, status: ResourceStatus | None) -> StepSpec:
    """Declare a non-terminal RAES observation, optionally projecting a range status."""
    return StepSpec(
        rank=rank, result_kind=_RESOURCE_STATE, shape=Shape.RAES_OPERATION, status=status, raes_state=raes_state
    )


def raes_success(rank: int, status: ResourceStatus) -> StepSpec:
    """Declare an RAES terminal-success observation."""
    return StepSpec(
        rank=rank,
        result_kind=_TERMINAL_SUCCESS,
        shape=Shape.RAES_OPERATION,
        status=status,
        terminal=True,
        raes_state=RAES_STATE_SUCCEEDED,
    )


def raes_ready(rank: int, status: ResourceStatus) -> StepSpec:
    """Declare the RAES terminal-success step that carries realized access.

    The realized member/access projection travels *in* this generation's
    terminal result rather than a separate pre-terminal one (ADR-032-R10), so
    the applier validates it, persists it, audits, and transitions READY in a
    single transaction. Splitting them would drop the generation association at
    persistence, letting stale state satisfy the gate.
    """
    return StepSpec(
        rank=rank,
        result_kind=_TERMINAL_SUCCESS,
        shape=Shape.RAES_READY,
        status=status,
        terminal=True,
        raes_state=RAES_STATE_SUCCEEDED,
    )


def raes_snapshot(rank: int) -> StepSpec:
    """Declare the bounded runtime-snapshot evidence step.

    Evidence only: ``status=None`` keeps it out of the lifecycle write path, so
    a snapshot can never produce an audit row or a range event.
    """
    return StepSpec(rank=rank, result_kind=_RESOURCE_STATE, shape=Shape.RAES_SNAPSHOT, status=None)


def _require_dict(value: object, field: str) -> dict[str, Any]:
    """Return ``value`` if it is a mapping, else fail closed."""
    if not isinstance(value, dict):
        raise OperationResultError(f"{field} must be an object")
    return value


def _require_exact_keys(value: dict[str, Any], allowed: frozenset[str], field: str) -> None:
    """Fail closed unless ``value`` carries exactly ``allowed``."""
    actual = frozenset(value)
    unexpected = sorted(actual - allowed)
    if unexpected:
        raise OperationResultError(f"{field} has unexpected field(s): {', '.join(unexpected)}")
    missing = sorted(allowed - actual)
    if missing:
        raise OperationResultError(f"{field} is missing field(s): {', '.join(missing)}")


def _require_uuid(value: object, field: str) -> str:
    """Return the canonical UUID string, else fail closed."""
    if not isinstance(value, str):
        raise OperationResultError(f"{field} must be a UUID string")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise OperationResultError(f"{field} must be a valid UUID") from exc


def _require_status(value: object, expected: ResourceStatus | None, field: str) -> str:
    """Return a known status, optionally pinned to the one the step reports."""
    if not isinstance(value, str):
        raise OperationResultError(f"{field} must be a status string")
    try:
        status = ResourceStatus(value)
    except ValueError:
        raise OperationResultError(f"{field} is not a known resource status") from None
    if expected is not None and status != expected:
        raise OperationResultError(f"{field} must be '{expected.value}' for this step, got '{status.value}'")
    return status.value


def _parse_instances(payload: dict[str, Any], spec: StepSpec) -> dict[str, Any]:
    """Parse a bounded set of per-instance outcomes."""
    _require_exact_keys(payload, frozenset({"instances"}), _PAYLOAD_FIELD)
    raw = payload["instances"]
    if not isinstance(raw, list):
        raise OperationResultError("result payload instances must be a list")
    if len(raw) > MAX_INSTANCE_OUTCOMES:
        raise OperationResultError(f"result payload carries more than {MAX_INSTANCE_OUTCOMES} instance outcomes")
    outcomes = []
    for index, item in enumerate(raw):
        entry = _require_dict(item, f"result payload instances[{index}]")
        _require_exact_keys(entry, frozenset({"instance_uuid", "status"}), f"result payload instances[{index}]")
        outcomes.append(
            {
                "instance_uuid": _require_uuid(entry["instance_uuid"], f"result payload instances[{index}] uuid"),
                "status": _require_status(entry["status"], spec.status, f"result payload instances[{index}] status"),
            }
        )
    return {"instances": outcomes}


def _parse_ngfw_state(value: object) -> dict[str, Any]:
    """Parse the normalized, provider-neutral NGFW state block."""
    state = _require_dict(value, "result payload ngfw_state")
    unexpected = sorted(frozenset(state) - NGFW_STATE_KEYS)
    if unexpected:
        raise OperationResultError(f"result payload ngfw_state has unexpected field(s): {', '.join(unexpected)}")
    return dict(state)


def _parse_ngfw(payload: dict[str, Any], spec: StepSpec) -> dict[str, Any]:
    """Parse an NGFW transition result, with optional normalized state."""
    required = frozenset({"ngfw_instance_uuid", "status"})
    unexpected = sorted(frozenset(payload) - (required | {"ngfw_state"}))
    if unexpected:
        raise OperationResultError(f"result payload has unexpected field(s): {', '.join(unexpected)}")
    missing = sorted(required - frozenset(payload))
    if missing:
        raise OperationResultError(f"result payload is missing field(s): {', '.join(missing)}")
    parsed: dict[str, Any] = {
        "ngfw_instance_uuid": _require_uuid(payload["ngfw_instance_uuid"], "result payload ngfw_instance_uuid"),
        "status": _require_status(payload["status"], spec.status, "result payload status"),
    }
    if "ngfw_state" in payload:
        parsed["ngfw_state"] = _parse_ngfw_state(payload["ngfw_state"])
    return parsed


def _parse_range_terminal(payload: dict[str, Any], spec: StepSpec) -> dict[str, Any]:
    """Parse a range operation's terminal status result."""
    _require_exact_keys(payload, frozenset({"status"}), _PAYLOAD_FIELD)
    return {"status": _require_status(payload["status"], spec.status, "result payload status")}


def _parse_failure(payload: dict[str, Any], _spec_unused: StepSpec) -> dict[str, Any]:
    """Parse a terminal failure: authored reason code plus bounded diagnostic."""
    _require_exact_keys(payload, frozenset({"reason_code", "diagnostic"}), _PAYLOAD_FIELD)
    reason_code = payload["reason_code"]
    if not isinstance(reason_code, str) or reason_code not in REASON_CODES:
        raise OperationResultError(f"result payload reason_code must be one of: {', '.join(sorted(REASON_CODES))}")
    diagnostic = payload["diagnostic"]
    if not isinstance(diagnostic, str):
        raise OperationResultError("result payload diagnostic must be a string")
    if len(diagnostic) > MAX_DIAGNOSTIC_CHARS:
        raise OperationResultError(f"result payload diagnostic exceeds {MAX_DIAGNOSTIC_CHARS} characters")
    return {"reason_code": reason_code, "diagnostic": diagnostic}


def _parse_raes_operation(payload: dict[str, Any], spec: StepSpec) -> dict[str, Any]:
    """Parse an RAES operation observation, with an optional bounded reason.

    ``raes_status`` is pinned to the step's declared state: the RAES vocabulary
    is coarse and direction-free, so an unpinned body would let a late
    ``running`` result be recorded under a terminal step (or the reverse).
    """
    # ``cleanup_inventory`` (#2086, ADR-063-R4) is the optional scoped provider
    # inventory/readback evidence carried by a terminal destroy result.
    _require_raes_keys(payload)
    parsed: dict[str, Any] = {"raes_status": _validated_raes_state(payload, spec)}
    reason = _parse_optional_status_reason(payload)
    if reason is not None:
        parsed["status_reason"] = reason
    if "cleanup_inventory" in payload:
        parsed["cleanup_inventory"] = _parse_cleanup_inventory(payload["cleanup_inventory"])
    return parsed


def _require_raes_keys(payload: dict[str, Any]) -> None:
    """Reject unexpected keys and require ``raes_status`` on an RAES result payload."""
    unexpected = sorted(frozenset(payload) - frozenset({"raes_status", "status_reason", "cleanup_inventory"}))
    if unexpected:
        raise OperationResultError(f"{_PAYLOAD_FIELD} has unexpected field(s): {', '.join(unexpected)}")
    if "raes_status" not in payload:
        raise OperationResultError(f"{_PAYLOAD_FIELD} is missing field(s): raes_status")


def _validated_raes_state(payload: dict[str, Any], spec: StepSpec) -> str:
    """Return the ``raes_status`` value, pinned to the step's declared state."""
    state = payload["raes_status"]
    if not isinstance(state, str) or state not in RAES_OPERATION_STATES:
        raise OperationResultError(
            f"{_PAYLOAD_FIELD} raes_status must be one of: {', '.join(sorted(RAES_OPERATION_STATES))}"
        )
    if spec.raes_state is not None and state != spec.raes_state:
        raise OperationResultError(f"{_PAYLOAD_FIELD} raes_status must be '{spec.raes_state}' for this step")
    return state


def _parse_optional_status_reason(payload: dict[str, Any]) -> str | None:
    """Return the bounded ``status_reason`` string when present, else ``None``."""
    if "status_reason" not in payload:
        return None
    reason = payload["status_reason"]
    if not isinstance(reason, str):
        raise OperationResultError(f"{_PAYLOAD_FIELD} status_reason must be a string")
    if len(reason) > MAX_DIAGNOSTIC_CHARS:
        raise OperationResultError(f"{_PAYLOAD_FIELD} status_reason exceeds {MAX_DIAGNOSTIC_CHARS} characters")
    return reason


_CLEANUP_OUTCOMES = frozenset({"VERIFIED_ABSENT", "RESIDUALS_FOUND", "INCOMPLETE"})
_CLEANUP_MAX_RESIDUAL_CATEGORIES = 32


def _parse_cleanup_inventory(value: object) -> dict[str, Any]:
    """Validate the bounded provider inventory/readback evidence (#2086, ADR-063-R4)."""
    if not isinstance(value, dict):
        raise OperationResultError(f"{_PAYLOAD_FIELD} cleanup_inventory must be an object")
    _require_exact_keys(
        value, frozenset({"outcome", "residual_categories", "scope"}), f"{_PAYLOAD_FIELD} cleanup_inventory"
    )
    outcome = value["outcome"]
    if outcome not in _CLEANUP_OUTCOMES:
        raise OperationResultError(
            f"{_PAYLOAD_FIELD} cleanup_inventory outcome must be one of: {', '.join(sorted(_CLEANUP_OUTCOMES))}"
        )
    residuals = value["residual_categories"]
    if not isinstance(residuals, list) or len(residuals) > _CLEANUP_MAX_RESIDUAL_CATEGORIES:
        raise OperationResultError(f"{_PAYLOAD_FIELD} cleanup_inventory residual_categories must be a bounded list")
    for index, entry in enumerate(residuals):
        if not isinstance(entry, dict):
            raise OperationResultError(
                f"{_PAYLOAD_FIELD} cleanup_inventory residual_categories[{index}] must be an object"
            )
        _require_exact_keys(
            entry, frozenset({"category", "count"}), f"{_PAYLOAD_FIELD} cleanup_inventory residual_categories[{index}]"
        )
    if not isinstance(value["scope"], dict):
        raise OperationResultError(f"{_PAYLOAD_FIELD} cleanup_inventory scope must be an object")
    return {"outcome": outcome, "residual_categories": residuals, "scope": value["scope"]}


def _parse_raes_snapshot(payload: dict[str, Any], _spec_unused: StepSpec) -> dict[str, Any]:
    """Parse the bounded RAES runtime-snapshot evidence."""
    _require_exact_keys(payload, frozenset({"resources"}), _PAYLOAD_FIELD)
    raw = payload["resources"]
    if not isinstance(raw, list):
        raise OperationResultError(f"{_PAYLOAD_FIELD} resources must be a list")
    if len(raw) > MAX_SNAPSHOT_RESOURCES:
        raise OperationResultError(f"{_PAYLOAD_FIELD} carries more than {MAX_SNAPSHOT_RESOURCES} snapshot resources")
    resources = []
    for index, item in enumerate(raw):
        field = f"{_PAYLOAD_FIELD} resources[{index}]"
        entry = _require_dict(item, field)
        _require_exact_keys(entry, SNAPSHOT_ENTRY_KEYS, field)
        for key in sorted(SNAPSHOT_ENTRY_KEYS):
            if not isinstance(entry[key], str) or not entry[key]:
                raise OperationResultError(f"{field} {key} must be a non-empty string")
        resources.append({key: entry[key] for key in sorted(SNAPSHOT_ENTRY_KEYS)})
    return {"resources": resources}


def _parse_raes_ready(payload: dict[str, Any], spec: StepSpec) -> dict[str, Any]:
    """Parse an RAES terminal-ready result plus its realized access projection."""
    required = frozenset({"raes_status", "members"})
    unexpected = sorted(frozenset(payload) - (required | {"status_reason", "completion"}))
    if unexpected:
        raise OperationResultError(f"{_PAYLOAD_FIELD} has unexpected field(s): {', '.join(unexpected)}")
    missing = sorted(required - frozenset(payload))
    if missing:
        raise OperationResultError(f"{_PAYLOAD_FIELD} is missing field(s): {', '.join(missing)}")

    operation = _parse_raes_operation(
        {key: payload[key] for key in payload if key not in {"members", "completion"}},
        spec,
    )
    raw = payload["members"]
    if not isinstance(raw, list):
        raise OperationResultError(f"{_PAYLOAD_FIELD} members must be a list")
    if len(raw) > MAX_RAES_MEMBERS:
        raise OperationResultError(f"{_PAYLOAD_FIELD} carries more than {MAX_RAES_MEMBERS} members")
    members = []
    for index, item in enumerate(raw):
        field = f"{_PAYLOAD_FIELD} members[{index}]"
        members.append(_parse_raes_member(_require_dict(item, field), field))
    identities = [member["uuid"] for member in members]
    if len(set(identities)) != len(identities):
        raise OperationResultError(f"{_PAYLOAD_FIELD} members contains a duplicate uuid")
    result = {**operation, "members": members}
    if "completion" in payload:
        from shared.raes.completion_evidence import validate_completion_evidence

        try:
            result["completion"] = validate_completion_evidence(payload["completion"])
        except ValueError:
            raise OperationResultError("invalid RAES completion evidence") from None
    return result


PARSERS = {
    Shape.INSTANCES: _parse_instances,
    Shape.NGFW: _parse_ngfw,
    Shape.RANGE_TERMINAL: _parse_range_terminal,
    Shape.FAILURE: _parse_failure,
    Shape.RAES_OPERATION: _parse_raes_operation,
    Shape.RAES_SNAPSHOT: _parse_raes_snapshot,
    Shape.RAES_READY: _parse_raes_ready,
}
