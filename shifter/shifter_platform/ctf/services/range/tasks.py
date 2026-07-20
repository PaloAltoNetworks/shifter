"""Event provisioning task orchestration.

Enqueues (and coalesces) the scheduler-run SPIN_UP_RANGES task that performs the
throttled provisioning off the request thread, and projects bounded provisioning
progress for the organizer UI. The work itself lives in
:mod:`ctf.services.range.batch`.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ctf.enums import ScheduledTaskStatus, ScheduledTaskType
from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFEvent, CTFParticipant, CTFScheduledTask
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


def request_event_provisioning(event_id: UUID, *, source: str = "manual") -> CTFScheduledTask:
    """Enqueue (or coalesce onto) a due-now SPIN_UP_RANGES task for an event.

    The organizer "provision all" action runs the throttled provisioning loop
    on the CTF scheduler instead of the request thread. Repeated clicks and a
    pre-existing scheduled spin-up coalesce onto a single runnable task:

    - a RUNNING spin-up task is reused as-is (work is already in flight);
    - a PENDING spin-up task is reused; if it is scheduled in the future it is
      pulled forward to now so the manual action takes effect immediately and
      the original task cannot fire again later;
    - otherwise a new PENDING task due now is created.

    The work itself only provisions participants without a range, so resuming or
    re-running is idempotent.

    Args:
        event_id: UUID of the event.
        source: Audit hint recorded in task metadata (e.g. "manual").

    Returns:
        The active CTFScheduledTask (created or coalesced).

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    spin_up = ScheduledTaskType.SPIN_UP_RANGES.value
    with transaction.atomic():
        # Serialize concurrent enqueues for the same event so duplicate clicks
        # cannot each create a runnable task.
        try:
            CTFEvent.objects.select_for_update().get(pk=event_id)
        except CTFEvent.DoesNotExist:
            raise CTFNotFoundError(
                f"Event {event_id} not found",
                details={"event_id": str(event_id)},
            ) from None

        now = timezone.now()

        running = CTFScheduledTask.objects.filter(
            event_id=event_id,
            task_type=spin_up,
            status=ScheduledTaskStatus.RUNNING.value,
        ).first()
        if running is not None:
            logger.info("Coalescing provision request onto running task %s", running.pk)
            return running

        pending = (
            CTFScheduledTask.objects.filter(
                event_id=event_id,
                task_type=spin_up,
                status=ScheduledTaskStatus.PENDING.value,
            )
            .order_by("scheduled_for")
            .first()
        )
        if pending is not None:
            if pending.scheduled_for > now:
                pending.scheduled_for = now
                pending.metadata = {**(pending.metadata or {}), "source": source}
                pending.save(update_fields=["scheduled_for", "metadata", "updated_at"])
                logger.info(
                    "Pulled scheduled spin-up task %s forward for event %s", pending.pk, safe_log_value(event_id)
                )
            else:
                logger.info("Coalescing provision request onto pending task %s", pending.pk)
            return pending

        task = CTFScheduledTask.objects.create(
            event_id=event_id,
            task_type=spin_up,
            scheduled_for=now,
            metadata={"source": source},
        )
    logger.info("Enqueued provision task %s for event %s", task.pk, safe_log_value(event_id))
    return task


def get_provision_progress(event_id: UUID) -> dict[str, Any]:
    """Project provisioning progress for an event.

    Returns bounded aggregate participant counts (computed from the cached
    ``range_status``) plus the active spin-up task's status, suitable for
    polling from the organizer UI. Carries no raw error text.

    Args:
        event_id: UUID of the event.

    Returns:
        ``{"counts": {...}, "task": {...} | None}``.
    """
    counts = {
        "total": 0,
        "ready": 0,
        "provisioning": 0,
        "error": 0,
        "not_assigned": 0,
        "other": 0,
    }
    statuses = CTFParticipant.objects.filter(event_id=event_id).values_list("range_status", flat=True)
    for status in statuses:
        counts["total"] += 1
        key = status or "not_assigned"
        if key in counts and key != "total":
            counts[key] += 1
        else:
            counts["other"] += 1

    active = (
        CTFScheduledTask.objects.filter(
            event_id=event_id,
            task_type=ScheduledTaskType.SPIN_UP_RANGES.value,
            status__in=[ScheduledTaskStatus.PENDING.value, ScheduledTaskStatus.RUNNING.value],
        )
        .order_by("-scheduled_for")
        .first()
    )
    task_block = None
    if active is not None:
        task_block = {
            "id": str(active.pk),
            "status": active.status,
            "scheduled_for": active.scheduled_for.isoformat(),
        }

    return {"counts": counts, "task": task_block}
