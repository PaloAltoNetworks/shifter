"""Project ACES operation status onto the existing range event path (#1274).

This is the engine-side orchestration for the ACES operation-status projection
bridge. It composes the #1273 operation sidecar (durable, idempotent record of
each observation) with the runtime-safe :mod:`shared.aces.status` adapter and
the existing transactional outbox. It deliberately reuses -- and does not
replace -- ``RangeEventOutbox``, ``drain_range_event_outbox``, the worker
retry/DLQ path, ``engine.handlers`` (authoritative ``engine.Range.status`` write),
``cms.handlers.range_events.apply_range_status`` (RangeInstance projection + CTF
bridge), Mission Control fanout, and ``reconcile_range_events`` (recovery).

Flow (persist-then-project, DB-authoritative):

1. Read the latest previously recorded operation-status observation for the
   operation (the staleness anchor), via the ``shared.aces.operations`` seam.
2. Run the pure adapter to get a decision + target ``ResourceStatus``.
3. In one transaction, persist the observation to the sidecar and -- only when
   the decision is ``APPLY`` and the target differs from the range's current
   status -- enqueue the standard ``range.status.updated`` outbox event.

The authoritative ``engine.Range.status`` write stays with the drained
``engine.handlers`` so there is a single writer and no double-write divergence.
Events carry ids/status/bounded error only; sanitized diagnostics live on the
sidecar ``diagnostic_refs``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from shared.aces.status import (
    AcesOperationStatusObservation,
    AcesStatusProjection,
    ProjectionDecision,
    project_operation_status,
)
from shared.enums import ResourceStatus
from shared.messages.events import EVENT_TYPE_STATUS_UPDATED

if TYPE_CHECKING:
    from engine.models import Range

logger = logging.getLogger(__name__)


def _build_status_payload(
    *,
    operation_id: str,
    request_id: UUID | str,
    operation_state: str,
    source_timestamp: datetime,
    updated_at: datetime,
    status_reason: str | None,
    diagnostic_ref: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the canonical ``operation_status`` sidecar payload (allowed keys only)."""
    payload: dict[str, Any] = {
        "operation_id": operation_id,
        "request_id": str(request_id),
        "status": operation_state,
        "source_timestamp": source_timestamp.isoformat(),
        "updated_at": updated_at.isoformat(),
    }
    if status_reason:
        payload["status_reason"] = status_reason
    if diagnostic_ref:
        payload["diagnostic_refs"] = diagnostic_ref
    return payload


def _build_status_event(
    range_obj: Range, request_id: UUID | str, new_status: str, error_message: str | None
) -> dict[str, Any]:
    """Build the standard ``range.status.updated`` event dict (ids/status only).

    Mirrors ``provisioner.events.build_status_event`` without importing the
    provisioner package, keeping the engine within its layer boundary.
    """
    return {
        "event_type": EVENT_TYPE_STATUS_UPDATED,
        "event_id": str(uuid4()),
        "timestamp": timezone.now().isoformat(),
        "request_id": str(request_id),
        "range_id": range_obj.id,
        "user_id": range_obj.user_id,
        "new_status": new_status,
        "error_message": error_message,
    }


def project_aces_operation_status(observation: AcesOperationStatusObservation) -> AcesStatusProjection:
    """Persist an ACES operation-status observation and project it to the range path.

    Args:
        observation: The ACES operation-status observation (correlation, contract,
            state, timestamps, and untrusted status reason / diagnostic refs).

    Returns:
        The :class:`AcesStatusProjection` decision. The observation is always
        persisted to the sidecar; a ``range.status.updated`` event is enqueued
        only when the decision is ``APPLY`` and the target differs from the
        range's current status.
    """
    from shared.aces.operations import (
        latest_operation_status_source_timestamp,
        persist_operation_status_record,
    )

    request_id = observation.request_id
    previous_source_timestamp = latest_operation_status_source_timestamp(request_id)

    projection = project_operation_status(
        operation_state=observation.operation_state,
        intent=observation.intent,
        source_timestamp=observation.source_timestamp,
        previous_source_timestamp=previous_source_timestamp,
        status_reason=observation.status_reason,
        diagnostic_refs=observation.diagnostic_refs,
    )

    payload = _build_status_payload(
        operation_id=observation.operation_id,
        request_id=request_id,
        operation_state=observation.operation_state,
        source_timestamp=observation.source_timestamp,
        updated_at=observation.updated_at or observation.source_timestamp,
        status_reason=projection.error_message,
        diagnostic_ref=projection.diagnostic_ref,
    )

    range_obj = _resolve_range(request_id) if projection.decision is ProjectionDecision.APPLY else None

    with transaction.atomic():
        persist_operation_status_record(
            request_id=request_id,
            operation_id=observation.operation_id,
            source_timestamp=observation.source_timestamp,
            payload=payload,
            diagnostic_refs=projection.diagnostic_ref,
        )
        if projection.decision is ProjectionDecision.APPLY:
            _maybe_enqueue(projection, range_obj=range_obj, request_id=request_id)

    return projection


def _resolve_range(request_id: UUID | str) -> Range | None:
    """Resolve the engine range for ``request_id`` or ``None`` when absent."""
    from engine.models import Range

    return Range.objects.filter(request__request_id=request_id).first()


def _maybe_enqueue(
    projection: AcesStatusProjection,
    *,
    range_obj: Range | None,
    request_id: UUID | str,
) -> None:
    """Enqueue a ``range.status.updated`` event when the projection is actionable."""
    from engine.models import RangeEventOutbox

    # Defensive: an APPLY decision always carries a target status.
    if projection.target_status is None:
        return
    new_status = projection.target_status.value

    if range_obj is None:
        logger.warning(
            "ACES status projection skipped: no range for request_id=%s new_status=%s",
            request_id,
            new_status,
        )
        return

    if range_obj.status == new_status:
        logger.debug(
            "ACES status projection no-op: range_id=%s already status=%s",
            range_obj.id,
            new_status,
        )
        return

    error_message = projection.error_message if projection.target_status is ResourceStatus.FAILED else None
    event = _build_status_event(range_obj, request_id, new_status, error_message)
    RangeEventOutbox.objects.create(
        event_id=event["event_id"],
        event_type=event["event_type"],
        payload=event,
        next_attempt_at=timezone.now(),
    )
    logger.info(
        "ACES status projection enqueued: range_id=%s new_status=%s event_id=%s",
        range_obj.id,
        new_status,
        event["event_id"],
    )
