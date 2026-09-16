"""Durable convergence of a provision-task interrupt (#277).

Driven by the existing launcher worker (no new worker): for each due interrupt,
advance one step toward the canonical destroy --

- launch still pending -> suppress dispatch, enqueue canonical destroy;
- task dispatched/running -> verify identity, stop it, observe terminal absence,
  then enqueue canonical destroy;
- identity mismatch -> fail closed (leave the range DESTROYING, never destroyed);
- unknown/awaiting -> reschedule with bounded backoff.

The provider stop call runs outside the intent row lock (like the launcher's own
dispatch), and the result is applied under a lease check so a reclaimed intent is
never double-advanced. Destroy is enqueued through the canonical
``enqueue_provisioner_launch`` path, which mints its own operation generation and
is idempotent, so re-entry after a crash converges rather than duplicating.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from engine.models import InterruptState, ProvisionerLaunchIntent
from shared.cloud.exceptions import CloudTaskError
from shared.cloud.types import TaskInterruptDisposition

logger = logging.getLogger(__name__)

# Non-terminal interrupt states the worker keeps advancing. DESTROY_ENQUEUED and
# IDENTITY_MISMATCH are terminal and are never re-claimed.
_ACTIVE_INTERRUPT_STATES = (
    InterruptState.REQUESTED,
    InterruptState.SUPPRESSED,
    InterruptState.STOPPING,
    InterruptState.TERMINAL_ABSENT,
    InterruptState.UNKNOWN,
)
_LEASE = timedelta(minutes=5)
_BACKOFF_SECONDS = 15
_MAX_BACKOFF_SECONDS = 300


def drain_due_interrupts(batch_size: int) -> int:
    """Advance each due interrupt one step toward the canonical destroy."""
    processed = 0
    for _ in range(batch_size):
        claimed = _claim_next_interrupt()
        if claimed is None:
            break
        _converge_interrupt(claimed)
        processed += 1
    return processed


def _claim_next_interrupt() -> ProvisionerLaunchIntent | None:
    """Lease the next due interrupt so a peer worker will not double-advance it."""
    with transaction.atomic():
        row = (
            ProvisionerLaunchIntent.objects.select_for_update(skip_locked=True)
            .filter(
                interrupt_state__in=_ACTIVE_INTERRUPT_STATES,
                interrupt_next_attempt_at__lte=timezone.now(),
            )
            .order_by("interrupt_next_attempt_at")
            .first()
        )
        if row is None:
            return None
        row.interrupt_next_attempt_at = timezone.now() + _LEASE
        row.save(update_fields=["interrupt_next_attempt_at"])
        return row


def _lease_matches(current: ProvisionerLaunchIntent, claimed: ProvisionerLaunchIntent) -> bool:
    """Fence a worker whose interrupt lease was reclaimed while it was converging."""
    return (
        current.interrupt_state in _ACTIVE_INTERRUPT_STATES
        and current.interrupt_next_attempt_at == claimed.interrupt_next_attempt_at
    )


def _reschedule(claimed: ProvisionerLaunchIntent, new_state: str, *, error: str = "") -> None:
    """Persist a non-terminal step and back off, or fail closed past the deadline.

    Enforces the bounded ``interrupt_deadline`` (#277): once it elapses without a
    confirmed terminal absence, stop churning and record the terminal EXHAUSTED
    disposition with an operator signal. The range is left DESTROYING -- never
    destroyed, since absence was never confirmed.
    """
    with transaction.atomic():
        current = ProvisionerLaunchIntent.objects.select_for_update().get(pk=claimed.pk)
        if not _lease_matches(current, claimed):
            return
        if current.interrupt_deadline is not None and timezone.now() >= current.interrupt_deadline:
            current.interrupt_state = InterruptState.EXHAUSTED
            current.interrupt_last_error = (error or "deadline_exceeded")[:128]
            current.save(update_fields=["interrupt_state", "interrupt_last_error"])
            logger.error(
                "interrupt: deadline exceeded, fail-closed (range stays DESTROYING) intent_id=%s last=%s",
                current.intent_id,
                current.interrupt_last_error,
            )
            return
        current.interrupt_attempts += 1
        backoff = min(_BACKOFF_SECONDS * 2 ** min(current.interrupt_attempts - 1, 10), _MAX_BACKOFF_SECONDS)
        current.interrupt_state = new_state
        current.interrupt_next_attempt_at = timezone.now() + timedelta(seconds=backoff)
        current.interrupt_last_error = error[:128]
        current.save(
            update_fields=[
                "interrupt_state",
                "interrupt_attempts",
                "interrupt_next_attempt_at",
                "interrupt_last_error",
            ]
        )


def _fail_closed(claimed: ProvisionerLaunchIntent) -> None:
    """Terminal fail-closed: the observed workload is not this reserved intent."""
    with transaction.atomic():
        current = ProvisionerLaunchIntent.objects.select_for_update().get(pk=claimed.pk)
        if not _lease_matches(current, claimed):
            return
        current.interrupt_state = InterruptState.IDENTITY_MISMATCH
        current.interrupt_last_error = "identity_mismatch"
        current.save(update_fields=["interrupt_state", "interrupt_last_error"])
    logger.error(
        "interrupt: workload identity mismatch, leaving range DESTROYING intent_id=%s",
        claimed.intent_id,
    )


def _mark_destroy_enqueued(claimed: ProvisionerLaunchIntent) -> None:
    """Terminal success: the canonical destroy has been enqueued for this range."""
    with transaction.atomic():
        current = ProvisionerLaunchIntent.objects.select_for_update().get(pk=claimed.pk)
        if not _lease_matches(current, claimed):
            return
        current.interrupt_state = InterruptState.DESTROY_ENQUEUED
        current.interrupt_last_error = ""
        current.save(update_fields=["interrupt_state", "interrupt_last_error"])


def _enqueue_destroy(claimed: ProvisionerLaunchIntent) -> bool:
    """Enqueue the canonical RAES destroy for the cancelled range. Idempotent."""
    from engine.launch_intents import enqueue_provisioner_launch

    payload = claimed.payload or {}
    request_id = payload.get("request_id")
    resource = payload.get("resource")
    if not request_id or resource != "raes-range":
        logger.error("interrupt: cannot enqueue destroy (missing request/non-raes) intent_id=%s", claimed.intent_id)
        return False
    enqueue_provisioner_launch([str(resource), "destroy", "--request-id", str(request_id)])
    return True


def _converge_to_destroy(claimed: ProvisionerLaunchIntent) -> None:
    """Enqueue destroy, then record the terminal interrupt state (idempotent)."""
    if _enqueue_destroy(claimed):
        _mark_destroy_enqueued(claimed)
    else:
        _reschedule(claimed, InterruptState.TERMINAL_ABSENT, error="destroy_enqueue_failed")


def _converge_interrupt(claimed: ProvisionerLaunchIntent) -> None:
    """Advance one interrupt by one step, observing real provider state.

    Launch-delivery status is NOT proof the provider task is absent: a PENDING
    retry after an ambiguous dispatch, or a DLQ'd ambiguous delivery, may still
    have created a task, and a RUNNING+REQUESTED row must be settled here rather
    than left ownerless (the launcher excludes every interrupted intent). So the
    only intent that may skip terminal-absence observation is one that never
    reserved a provider identity at all (no ``task_ref`` -- the engine task runner
    was unconfigured at enqueue, so no provider Job could ever have been named).
    Every other intent resolves its reserved deterministic identity and observes
    absence before the canonical destroy.
    """
    if not claimed.task_ref:
        _converge_to_destroy(claimed)
        return
    _stop_and_converge(claimed)


def _stop_and_converge(claimed: ProvisionerLaunchIntent) -> None:
    """Verify + stop the reserved provider task, observe absence, map the disposition."""
    from engine.ecs import interrupt_provisioner_task
    from engine.launch_intents import command_from_payload

    command = command_from_payload({**claimed.payload, "operation_id": str(claimed.operation_id)})
    try:
        disposition = interrupt_provisioner_task(claimed.task_ref, command, str(claimed.intent_id))
    except CloudTaskError as exc:
        _reschedule(claimed, InterruptState.UNKNOWN, error=type(exc).__name__)
        return

    if disposition == TaskInterruptDisposition.TERMINAL_ABSENT:
        _converge_to_destroy(claimed)
    elif disposition == TaskInterruptDisposition.STOPPING:
        _reschedule(claimed, InterruptState.STOPPING, error="")
    elif disposition == TaskInterruptDisposition.IDENTITY_MISMATCH:
        _fail_closed(claimed)
    else:
        # UNKNOWN, or None when the engine task runner is not configured.
        _reschedule(claimed, InterruptState.UNKNOWN, error="interrupt_unknown")
