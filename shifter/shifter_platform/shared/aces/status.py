"""Runtime-safe ACES operation-status -> Shifter ``ResourceStatus`` adapter (#1274).

This module is the single place that knows the ACES operation-status vocabulary
and how it maps onto Shifter's range lifecycle. It is deliberately:

- **Runtime-safe** -- it must not import the ACES SDL (``aces_contracts`` /
  ``aces_backend_protocols``). Only ``shared/aces/manifest.py`` and
  ``shared/aces/runtime_target.py`` import the SDL (a runtime dependency since
  #1262). The known operation-state values are mirrored here as plain strings
  and a drift guard test (``tests/shared/aces/test_status_adapter.py``)
  asserts they still match the SDL enum.
- **Pure** -- no database access, no engine/cms/provisioner imports. It maps a
  validated observation to a target status and a decision; the engine-side
  orchestration (``engine.services.project_aces_operation_status``) owns
  persistence and outbox enqueue.

The ACES ``OperationStatus`` carries a *coarse operation* lifecycle
(accepted/running/succeeded/failed/cancelled) plus ``domain=provisioning``. It
does not carry the range lifecycle *direction*, so the caller supplies the
submitted Shifter operation intent (provision/destroy/pause/resume) explicitly;
the adapter never infers direction from provider task state or string shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

from shared.enums import ResourceStatus
from shared.schemas.aces_operation import DIAGNOSTIC_REF_KEYS

# Runtime-safe mirror of ``aces_contracts.runtime_state.OperationState``. The SDL
# is not importable on the Django runtime path (see module docstring); the drift
# guard test keeps this set in lockstep with the SDL enum.
ACES_STATE_ACCEPTED = "accepted"
ACES_STATE_RUNNING = "running"
ACES_STATE_SUCCEEDED = "succeeded"
ACES_STATE_FAILED = "failed"
ACES_STATE_CANCELLED = "cancelled"

ACES_OPERATION_STATES: frozenset[str] = frozenset(
    {
        ACES_STATE_ACCEPTED,
        ACES_STATE_RUNNING,
        ACES_STATE_SUCCEEDED,
        ACES_STATE_FAILED,
        ACES_STATE_CANCELLED,
    }
)


class RangeOperation(StrEnum):
    """Shifter range lifecycle operation intent (mirrors the provisioner CLI verbs)."""

    PROVISION = "provision"
    DESTROY = "destroy"
    PAUSE = "pause"
    RESUME = "resume"


class ProjectionDecision(StrEnum):
    """Outcome of projecting one ACES operation-status observation."""

    #: Map to ``target_status`` and enqueue a ``range.status.updated`` event.
    APPLY = "apply"
    #: Same observation already seen (equal source timestamp); no range change.
    DUPLICATE = "duplicate"
    #: Older than the latest accepted observation; no range change.
    STALE = "stale"
    #: Unknown ACES state or unknown intent; never touch range status.
    UNMAPPABLE = "unmappable"


@dataclass(frozen=True)
class AcesStatusProjection:
    """Result of projecting one ACES operation-status observation.

    ``error_message`` and ``diagnostic_ref`` are bounded, single-line,
    user-safe values produced by this adapter. Callers MUST use these for
    durable event/sidecar surfaces rather than the raw caller-supplied
    ``status_reason`` / ``diagnostic_refs``: the adapter is the trust boundary
    and does not assume its inputs were already sanitized.
    """

    decision: ProjectionDecision
    target_status: ResourceStatus | None
    reason: str
    diagnostic_ref: dict[str, Any] | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class AcesOperationStatusObservation:
    """One ACES operation-status observation for a Shifter-backed range operation.

    Bundles the correlation, contract, and observation fields so callers pass a
    single value to :func:`engine.services.project_aces_operation_status`.
    ``status_reason`` / ``diagnostic_refs`` are caller-supplied and treated as
    untrusted; the adapter bounds them before they reach any durable surface.
    """

    request_id: UUID | str
    operation_id: str
    intent: RangeOperation | str
    operation_state: str
    source_timestamp: datetime
    updated_at: datetime | None = None
    status_reason: str | None = None
    diagnostic_refs: dict[str, Any] | None = None


# Explicit (intent x ACES state) -> Shifter ResourceStatus table. This is the
# only mapping authority; adding an ACES status vocabulary or intent means adding
# a row here plus a test vector, never editing CMS/CTF/Mission Control/reconciler.
#
# ``cancelled`` maps to FAILED for every intent: a cancelled control-plane
# operation means the intended transition did not complete, so surfacing FAILED
# is the safe, operator-visible, reconciler-recoverable outcome. Only ACES-backed
# ranges pass through this adapter, so this does not affect non-ACES range UX.
_STATE_MAP: dict[RangeOperation, dict[str, ResourceStatus]] = {
    RangeOperation.PROVISION: {
        ACES_STATE_ACCEPTED: ResourceStatus.PENDING,
        ACES_STATE_RUNNING: ResourceStatus.PROVISIONING,
        ACES_STATE_SUCCEEDED: ResourceStatus.READY,
        ACES_STATE_FAILED: ResourceStatus.FAILED,
        ACES_STATE_CANCELLED: ResourceStatus.FAILED,
    },
    RangeOperation.DESTROY: {
        ACES_STATE_ACCEPTED: ResourceStatus.DESTROYING,
        ACES_STATE_RUNNING: ResourceStatus.DESTROYING,
        ACES_STATE_SUCCEEDED: ResourceStatus.DESTROYED,
        ACES_STATE_FAILED: ResourceStatus.FAILED,
        ACES_STATE_CANCELLED: ResourceStatus.FAILED,
    },
    RangeOperation.PAUSE: {
        ACES_STATE_ACCEPTED: ResourceStatus.PAUSING,
        ACES_STATE_RUNNING: ResourceStatus.PAUSING,
        ACES_STATE_SUCCEEDED: ResourceStatus.PAUSED,
        ACES_STATE_FAILED: ResourceStatus.FAILED,
        ACES_STATE_CANCELLED: ResourceStatus.FAILED,
    },
    RangeOperation.RESUME: {
        ACES_STATE_ACCEPTED: ResourceStatus.RESUMING,
        ACES_STATE_RUNNING: ResourceStatus.RESUMING,
        ACES_STATE_SUCCEEDED: ResourceStatus.READY,
        ACES_STATE_FAILED: ResourceStatus.FAILED,
        ACES_STATE_CANCELLED: ResourceStatus.FAILED,
    },
}


def _coerce_intent(intent: RangeOperation | str) -> RangeOperation | None:
    """Return the ``RangeOperation`` for ``intent`` or ``None`` when unknown."""
    if isinstance(intent, RangeOperation):
        return intent
    try:
        return RangeOperation(intent)
    except ValueError:
        return None


#: Maximum length of any diagnostic text the adapter emits to a durable surface.
#: The adapter is the trust boundary; it bounds caller-supplied text rather than
#: assuming it was already sized/sanitized, so an unbounded provider string can
#: never reach an event payload, sidecar row, or log line.
MAX_DIAGNOSTIC_TEXT_LEN = 256


def _bound_text(value: object) -> str:
    """Coerce ``value`` to a bounded, single-line, user-safe diagnostic string.

    Collapses all whitespace (including newlines) and truncates to
    ``MAX_DIAGNOSTIC_TEXT_LEN``. This enforces the "bounded user-safe phrase"
    contract at the boundary; it does not attempt to remove secrets from the
    text -- callers must not put secrets in ``status_reason`` / diagnostic refs,
    and the sidecar already restricts the *keys* to non-secret references.
    """
    text = " ".join(str(value).split())
    if len(text) > MAX_DIAGNOSTIC_TEXT_LEN:
        text = text[:MAX_DIAGNOSTIC_TEXT_LEN]
    return text


def _build_diagnostic_ref(status_reason: str | None, diagnostic_refs: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a sanitized, bounded diagnostic reference limited to ``DIAGNOSTIC_REF_KEYS``.

    Never carries raw provider dumps, tokens, snapshots, or execution output --
    only the bounded, allow-listed reference keys the sidecar accepts, with each
    value coerced to a bounded single-line string.
    """
    ref: dict[str, Any] = {}
    if diagnostic_refs:
        for key, value in diagnostic_refs.items():
            if key in DIAGNOSTIC_REF_KEYS and value is not None:
                ref[key] = _bound_text(value)
    if status_reason and "status_reason" in DIAGNOSTIC_REF_KEYS:
        ref.setdefault("status_reason", _bound_text(status_reason))
    return ref or None


def _unmappable_reason(
    resolved_intent: RangeOperation | None,
    raw_intent: RangeOperation | str,
    operation_state: str,
) -> str | None:
    """Return the reason an observation is unmappable, or ``None`` when it maps."""
    if resolved_intent is None:
        return f"unknown range operation intent: {raw_intent!r}"
    if operation_state not in ACES_OPERATION_STATES:
        return f"unknown ACES operation state: {operation_state!r}"
    return None


def _staleness(
    source_timestamp: datetime, previous_source_timestamp: datetime | None
) -> tuple[ProjectionDecision, None, str] | None:
    """Classify a non-fresh observation, or ``None`` when it is fresh."""
    if previous_source_timestamp is not None and source_timestamp <= previous_source_timestamp:
        if source_timestamp < previous_source_timestamp:
            return ProjectionDecision.STALE, None, "observation older than latest accepted operation status"
        return ProjectionDecision.DUPLICATE, None, "observation duplicates latest accepted operation status"
    return None


def _classify(
    resolved_intent: RangeOperation | None,
    raw_intent: RangeOperation | str,
    operation_state: str,
    source_timestamp: datetime,
    previous_source_timestamp: datetime | None,
) -> tuple[ProjectionDecision, ResourceStatus | None, str]:
    """Return the ``(decision, target_status, reason)`` for one observation."""
    unmappable = _unmappable_reason(resolved_intent, raw_intent, operation_state)
    if unmappable is not None:
        return ProjectionDecision.UNMAPPABLE, None, unmappable
    staleness = _staleness(source_timestamp, previous_source_timestamp)
    if staleness is not None:
        return staleness
    # resolved_intent is non-None here (an unmappable intent returned above).
    mapped_intent = cast(RangeOperation, resolved_intent)
    target_status = _STATE_MAP[mapped_intent][operation_state]
    return (
        ProjectionDecision.APPLY,
        target_status,
        f"{mapped_intent.value}:{operation_state} -> {target_status.value}",
    )


def project_operation_status(
    *,
    operation_state: str,
    intent: RangeOperation | str,
    source_timestamp: datetime,
    previous_source_timestamp: datetime | None = None,
    status_reason: str | None = None,
    diagnostic_refs: dict[str, Any] | None = None,
) -> AcesStatusProjection:
    """Project one validated ACES operation-status observation to a range status.

    Args:
        operation_state: ACES ``OperationState`` value (must be a known state).
        intent: Submitted Shifter range operation (provision/destroy/pause/resume).
        source_timestamp: Observation time of this status.
        previous_source_timestamp: Source timestamp of the latest previously
            accepted operation-status observation for the same operation, if any.
        status_reason: Optional caller-supplied status reason (bounded here).
        diagnostic_refs: Optional caller-supplied diagnostic references (bounded here).

    Returns:
        An :class:`AcesStatusProjection`. ``APPLY`` carries the target
        ``ResourceStatus``; ``DUPLICATE``/``STALE``/``UNMAPPABLE`` carry
        ``target_status=None`` and must never change range state.
    """
    resolved_intent = _coerce_intent(intent)
    decision, target_status, reason = _classify(
        resolved_intent, intent, operation_state, source_timestamp, previous_source_timestamp
    )
    return AcesStatusProjection(
        decision=decision,
        target_status=target_status,
        reason=reason,
        diagnostic_ref=_build_diagnostic_ref(status_reason, diagnostic_refs),
        error_message=_bound_text(status_reason) if status_reason else None,
    )
