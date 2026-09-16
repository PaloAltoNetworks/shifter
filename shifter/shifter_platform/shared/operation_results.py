"""Closed operation-result contract for the pause/resume, NGFW, and RAES families.

ADR-043 phase 4 (#1836) and phase 5 (#1837). ``shared.operation_envelope`` owns
the *transport* shape; this module owns the bounded, operation-specific
``payload`` that rides inside it, plus the two things the transport
deliberately does not model:

* **Step identity.** ``f"{operation_id}:{result_kind}"`` cannot identify a result
  when one operation emits several ``RESOURCE_STATE`` results — a range pause
  reports its instances, then its NGFW cascade, then its terminal state, and the
  cascade itself reports both ``pausing`` and ``paused``. Identity is
  therefore parameterized by a closed, deterministic per-operation step key. The
  same semantic step on retry reproduces the same key and the same digest; wall
  clock, thread-pool completion order, and delivery UUIDs are not ordering keys.
* **Legal order and terminality.** Declared per ``(resource, operation)`` so the
  applier can refuse a progress result that arrives after a terminal one instead
  of regressing domain state.

The payload is closed on keys: no ``**state_updates`` passthrough, no raw
Terraform/provider responses, no exception strings, no table column names, no
full state snapshots. Correlation is by UUID only — Engine integer primary keys
are never identity here.

Dependency-light on purpose: the standalone provisioner image imports this
without Django or the platform schema graph. There is one native shared boundary
error type; callers do not add a parallel exception hierarchy.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any
from uuid import UUID

from shared.enums import ResourceStatus
from shared.exceptions import ValidationError as OperationResultError
from shared.operation_result_payloads import (
    MAX_DIAGNOSTIC_CHARS,
    MAX_INSTANCE_OUTCOMES,
    MAX_SNAPSHOT_RESOURCES,
    NGFW_STATE_KEYS,
    PARSERS,
    REASON_CODES,
    SNAPSHOT_ENTRY_KEYS,
    Shape,
    StepSpec,
    failure,
    progress,
    raes_progress,
    raes_ready,
    raes_snapshot,
    raes_success,
    success,
)
from shared.raes.status import RAES_STATE_RUNNING

__all__ = [
    "MAX_DIAGNOSTIC_CHARS",
    "MAX_INSTANCE_OUTCOMES",
    "MAX_SNAPSHOT_RESOURCES",
    "NGFW_STATE_KEYS",
    "REASON_CODES",
    "SNAPSHOT_ENTRY_KEYS",
    "OperationResultError",
    "ResultStep",
    "build_result_identity",
    "has_contract",
    "is_terminal_step",
    "latest_step",
    "parse_result_payload",
    "range_status_for",
    "result_kind_for",
    "step_follows",
    "steps_for",
]


class ResultStep(StrEnum):
    """Closed, deterministic step keys. Scoped to a ``(resource, operation)``."""

    # range pause
    RANGE_INSTANCES_PAUSED = "range_instances_paused"
    RANGE_NGFW_CASCADE_PAUSING = "range_ngfw_cascade_pausing"
    RANGE_NGFW_CASCADE_PAUSED = "range_ngfw_cascade_paused"
    RANGE_TERMINAL_PAUSED = "range_terminal_paused"
    # range resume
    RANGE_NGFW_CASCADE_RESUMING = "range_ngfw_cascade_resuming"
    RANGE_NGFW_CASCADE_READY = "range_ngfw_cascade_ready"
    RANGE_INSTANCES_READY = "range_instances_ready"
    RANGE_TERMINAL_READY = "range_terminal_ready"
    # range, either direction
    RANGE_NGFW_CASCADE_FAILED = "range_ngfw_cascade_failed"
    RANGE_TERMINAL_FAILED = "range_terminal_failed"
    # ngfw provision: three observations all report ``provisioning``, so the step
    # key -- not the status -- is what distinguishes and orders them.
    NGFW_PROVISION_REQUESTED = "ngfw_provision_requested"
    NGFW_PROVISION_INFRA = "ngfw_provision_infra"
    NGFW_PROVISION_READY = "ngfw_provision_ready"
    # The auto-stop that ends provisioning is a step OF the provision generation,
    # not a second `stop` operation (ADR-043 phase 4 preflight).
    NGFW_PROVISION_AUTOSTOP = "ngfw_provision_autostop"
    # ngfw deprovision / power
    NGFW_DEPROVISION_DESTROYING = "ngfw_deprovision_destroying"
    NGFW_POWER_STARTING = "ngfw_power_starting"
    NGFW_POWER_STOPPING = "ngfw_power_stopping"
    # ngfw terminals
    NGFW_TERMINAL_READY = "ngfw_terminal_ready"
    NGFW_TERMINAL_PAUSED = "ngfw_terminal_paused"
    NGFW_TERMINAL_DESTROYED = "ngfw_terminal_destroyed"
    NGFW_TERMINAL_FAILED = "ngfw_terminal_failed"
    # raes-range provision/destroy (phase 5). The RAES operation vocabulary is
    # coarse (running/succeeded/failed) and carries no lifecycle direction, so
    # the step -- not the reported state -- is what distinguishes and orders a
    # provision observation from a destroy one.
    RAES_PROVISION_RUNNING = "raes_provision_running"
    RAES_PROVISION_SNAPSHOT = "raes_provision_snapshot"
    RAES_DESTROY_RUNNING = "raes_destroy_running"
    RAES_TERMINAL_READY = "raes_terminal_ready"
    RAES_TERMINAL_DESTROYED = "raes_terminal_destroyed"
    RAES_TERMINAL_FAILED = "raes_terminal_failed"
    # raes-range activate (#28): hand a claimed warm generation to its claimant.
    # Distinct running/snapshot steps keep an activate observation orderable and
    # distinguishable from the warm-prepare provision that preceded it; the
    # terminal ready/failed steps are the shared RAES terminals above.
    RAES_ACTIVATE_RUNNING = "raes_activate_running"
    RAES_ACTIVATE_SNAPSHOT = "raes_activate_snapshot"


_RANGE_PAUSE_STEPS: dict[ResultStep, StepSpec] = {
    ResultStep.RANGE_INSTANCES_PAUSED: progress(10, Shape.INSTANCES, ResourceStatus.PAUSED),
    ResultStep.RANGE_NGFW_CASCADE_PAUSING: progress(20, Shape.NGFW, ResourceStatus.PAUSING),
    ResultStep.RANGE_NGFW_CASCADE_PAUSED: progress(30, Shape.NGFW, ResourceStatus.PAUSED),
    ResultStep.RANGE_NGFW_CASCADE_FAILED: progress(30, Shape.NGFW, ResourceStatus.FAILED),
    ResultStep.RANGE_TERMINAL_PAUSED: success(40, Shape.RANGE_TERMINAL, ResourceStatus.PAUSED),
    ResultStep.RANGE_TERMINAL_FAILED: failure(40),
}

_RANGE_RESUME_STEPS: dict[ResultStep, StepSpec] = {
    ResultStep.RANGE_NGFW_CASCADE_RESUMING: progress(10, Shape.NGFW, ResourceStatus.RESUMING),
    ResultStep.RANGE_NGFW_CASCADE_READY: progress(20, Shape.NGFW, ResourceStatus.READY),
    ResultStep.RANGE_NGFW_CASCADE_FAILED: progress(20, Shape.NGFW, ResourceStatus.FAILED),
    ResultStep.RANGE_INSTANCES_READY: progress(30, Shape.INSTANCES, ResourceStatus.READY),
    ResultStep.RANGE_TERMINAL_READY: success(40, Shape.RANGE_TERMINAL, ResourceStatus.READY),
    ResultStep.RANGE_TERMINAL_FAILED: failure(40),
}

_NGFW_PROVISION_STEPS: dict[ResultStep, StepSpec] = {
    ResultStep.NGFW_PROVISION_REQUESTED: progress(10, Shape.NGFW, ResourceStatus.PROVISIONING),
    ResultStep.NGFW_PROVISION_INFRA: progress(20, Shape.NGFW, ResourceStatus.PROVISIONING),
    ResultStep.NGFW_PROVISION_READY: progress(30, Shape.NGFW, ResourceStatus.READY),
    # Provisioning ends paused: the NGFW is auto-stopped once it is ready.
    ResultStep.NGFW_PROVISION_AUTOSTOP: success(40, Shape.NGFW, ResourceStatus.PAUSED),
    ResultStep.NGFW_TERMINAL_FAILED: failure(40),
}

_NGFW_DEPROVISION_STEPS: dict[ResultStep, StepSpec] = {
    ResultStep.NGFW_DEPROVISION_DESTROYING: progress(10, Shape.NGFW, ResourceStatus.DESTROYING),
    ResultStep.NGFW_TERMINAL_DESTROYED: success(20, Shape.NGFW, ResourceStatus.DESTROYED),
    ResultStep.NGFW_TERMINAL_FAILED: failure(20),
}

_NGFW_START_STEPS: dict[ResultStep, StepSpec] = {
    ResultStep.NGFW_POWER_STARTING: progress(10, Shape.NGFW, ResourceStatus.RESUMING),
    ResultStep.NGFW_TERMINAL_READY: success(20, Shape.NGFW, ResourceStatus.READY),
    ResultStep.NGFW_TERMINAL_FAILED: failure(20),
}

_NGFW_STOP_STEPS: dict[ResultStep, StepSpec] = {
    ResultStep.NGFW_POWER_STOPPING: progress(10, Shape.NGFW, ResourceStatus.PAUSING),
    ResultStep.NGFW_TERMINAL_PAUSED: success(20, Shape.NGFW, ResourceStatus.PAUSED),
    ResultStep.NGFW_TERMINAL_FAILED: failure(20),
}

# RAES provision reports one running observation, then bounded topology
# evidence, then its terminal state. Provision-running projects PROVISIONING
# because the pre-cutover path published that range status at start; destroy
# has no equivalent published start event, so its running observation is
# sidecar evidence and projects nothing.
_RAES_PROVISION_STEPS: dict[ResultStep, StepSpec] = {
    ResultStep.RAES_PROVISION_RUNNING: raes_progress(10, RAES_STATE_RUNNING, ResourceStatus.PROVISIONING),
    ResultStep.RAES_PROVISION_SNAPSHOT: raes_snapshot(20),
    ResultStep.RAES_TERMINAL_READY: raes_ready(30, ResourceStatus.READY),
    ResultStep.RAES_TERMINAL_FAILED: failure(30),
}

_RAES_DESTROY_STEPS: dict[ResultStep, StepSpec] = {
    ResultStep.RAES_DESTROY_RUNNING: raes_progress(10, RAES_STATE_RUNNING, None),
    ResultStep.RAES_TERMINAL_DESTROYED: raes_success(20, ResourceStatus.DESTROYED),
    ResultStep.RAES_TERMINAL_FAILED: failure(20),
}

# raes-range activate (#28). The claimed generation's range is already realized
# (public READY), so the running observation projects no status change; the
# terminal-ready step re-applies the range READY with the claimant's fresh,
# sanitized realized access (the applier keys the warm-vs-provision behavior on
# ``row.operation``).
_RAES_ACTIVATE_STEPS: dict[ResultStep, StepSpec] = {
    ResultStep.RAES_ACTIVATE_RUNNING: raes_progress(10, RAES_STATE_RUNNING, None),
    ResultStep.RAES_ACTIVATE_SNAPSHOT: raes_snapshot(20),
    ResultStep.RAES_TERMINAL_READY: raes_ready(30, ResourceStatus.READY),
    ResultStep.RAES_TERMINAL_FAILED: failure(30),
}

# ``raes-range`` pause/resume share the range lifecycle contract; the applier
# resolves the target differently, the result shape is the same. Provision and
# destroy do not: they report RAES operation observations, not instance sets.

_CONTRACT: dict[tuple[str, str], dict[ResultStep, StepSpec]] = {
    ("range", "pause"): _RANGE_PAUSE_STEPS,
    ("range", "resume"): _RANGE_RESUME_STEPS,
    ("raes-range", "pause"): _RANGE_PAUSE_STEPS,
    ("raes-range", "resume"): _RANGE_RESUME_STEPS,
    ("raes-range", "provision"): _RAES_PROVISION_STEPS,
    ("raes-range", "destroy"): _RAES_DESTROY_STEPS,
    ("raes-range", "activate"): _RAES_ACTIVATE_STEPS,
    ("ngfw", "provision"): _NGFW_PROVISION_STEPS,
    ("ngfw", "deprovision"): _NGFW_DEPROVISION_STEPS,
    ("ngfw", "start"): _NGFW_START_STEPS,
    ("ngfw", "stop"): _NGFW_STOP_STEPS,
}


def _steps(resource: str, operation: str) -> dict[ResultStep, StepSpec]:
    """Return the declared step table for a pair, or fail closed."""
    try:
        return _CONTRACT[(resource, operation)]
    except KeyError:
        raise OperationResultError(f"no result contract for resource '{resource}' operation '{operation}'") from None


def _spec(resource: str, operation: str, step: ResultStep | str) -> StepSpec:
    """Return the spec for a step declared on this pair, or fail closed."""
    table = _steps(resource, operation)
    try:
        declared = ResultStep(step)
    except ValueError:
        raise OperationResultError(f"unknown result step '{step}'") from None
    spec = table.get(declared)
    if spec is None:
        raise OperationResultError(f"result step '{declared}' is not declared for {resource}:{operation}")
    return spec


def steps_for(resource: str, operation: str) -> frozenset[ResultStep]:
    """Return every step key declared for a ``(resource, operation)``."""
    return frozenset(_steps(resource, operation))


def has_contract(resource: str, operation: str) -> bool:
    """Return True when this family has an authoritative result contract.

    Families still on the shadow path (those not yet cut over from direct
    provisioner SQL) have no contract here; the applier leaves them in shadow
    rather than rejecting them.
    """
    return (resource, operation) in _CONTRACT


def result_kind_for(resource: str, operation: str, *, step: ResultStep | str) -> str:
    """Return the result kind a step must be recorded under."""
    return _spec(resource, operation, step).result_kind


def is_terminal_step(resource: str, operation: str, *, step: ResultStep | str) -> bool:
    """Return True when the step terminates its operation generation."""
    return _spec(resource, operation, step).terminal


def range_status_for(resource: str, operation: str, *, step: ResultStep | str) -> str | None:
    """Return the range status a step projects, or None when it is evidence only.

    The applier uses this to decide whether a result moves lifecycle state at
    all. ``None`` means persist the evidence and stop: no status write, no audit
    row, no range event.
    """
    status = _spec(resource, operation, step).status
    return status.value if status is not None else None


def step_follows(
    resource: str,
    operation: str,
    *,
    previous: ResultStep | str | None,
    step: ResultStep | str,
) -> bool:
    """Return True when ``step`` may legally be applied after ``previous``.

    ``previous`` is the last step already applied for this operation generation,
    or None when nothing has been applied yet. Once a terminal step is applied
    only its own replay is legal: a late progress result must never regress
    domain state, and a late failure must never overwrite a terminal success.
    """
    spec = _spec(resource, operation, step)
    if previous is None:
        return True
    previous_spec = _spec(resource, operation, previous)
    if previous_spec.terminal:
        return ResultStep(step) == ResultStep(previous)
    return spec.rank >= previous_spec.rank


def latest_step(resource: str, operation: str, steps: Iterable[ResultStep | str]) -> ResultStep | None:
    """Return the furthest-advanced step among ``steps``, or None when empty.

    The applier passes the steps already applied for one operation generation and
    uses the result as ``previous`` for the ordering check, so out-of-order
    delivery is judged against the high-water mark rather than the last row
    written.
    """
    ranked = [(_spec(resource, operation, step).rank, ResultStep(step)) for step in steps]
    if not ranked:
        return None
    # Terminal steps outrank their same-rank peers so a terminal already applied
    # is never masked by a progress step recorded at the same rank.
    return max(ranked, key=lambda item: (item[0], _spec(resource, operation, item[1]).terminal))[1]


def build_result_identity(*, operation_id: str | UUID, step: ResultStep | str, digest: str) -> str:
    """Return the deterministic inbox identity for one result.

    The digest is part of the identity so the append boundary can absorb an
    identical replay with ``ON CONFLICT DO NOTHING`` while a *conflicting* replay
    lands as a second row for the same step — detectable by the applier, which
    may read the inbox, without granting the provisioner any inbox read
    (migration 0036 grants INSERT only).
    """
    return f"{operation_id}:{ResultStep(step)}:{digest}"


def parse_result_payload(
    resource: str,
    operation: str,
    *,
    step: ResultStep | str,
    payload: object,
) -> dict[str, Any]:
    """Validate a result payload against its step's closed shape.

    Returns the normalized payload. Fails closed on an undeclared step, an
    unexpected or missing field, a non-UUID correlation id, an unknown status, a
    status incoherent with the step, an unbounded collection, or an unauthored
    failure reason.
    """
    spec = _spec(resource, operation, step)
    if not isinstance(payload, dict):
        raise OperationResultError("result payload must be an object")
    return PARSERS[spec.shape](payload, spec)
