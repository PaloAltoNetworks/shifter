"""Range pause / resume lifecycle operations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import UUID

from shared.enums import ResourceStatus

if TYPE_CHECKING:
    from contextlib import AbstractContextManager as ContextManager

    from engine.models import Range

logger = logging.getLogger(__name__)


def _atomic() -> ContextManager[None]:
    """Late-bound ``engine.services.transaction.atomic()`` so tests can patch the package-level name."""
    from engine import services as _es

    return _es.transaction.atomic()


def _run_range_lifecycle_op(
    request_id: UUID,
    op_name: str,
    *,
    idempotent_statuses: tuple[str, ...],
    required_status: str,
    target_status: str,
    revert_status: str,
) -> bool:
    """Shared pause/resume transition + ECS-dispatch helper.

    Returns True if the operation was initiated (or already complete);
    False if the range was missing, in the wrong state, or the ECS task
    could not be started. Status transitions and revert-on-failure mirror
    the original per-operation implementations so behaviour is unchanged.
    """
    from engine.ecs import start_range_operation
    from engine.models import Range
    from shared.cloud.exceptions import CloudTaskError

    logger.debug("%s_range: request_id=%s", op_name, request_id)

    with _atomic():
        range_obj = Range.objects.select_for_update().filter(request__request_id=request_id).first()
        if not range_obj:
            logger.warning("%s_range: no range for request_id=%s", op_name, request_id)
            return False

        decision = _classify_lifecycle_decision(
            range_obj.status,
            request_id=request_id,
            op_name=op_name,
            idempotent_statuses=idempotent_statuses,
            required_status=required_status,
        )
        if decision is not None:
            return decision

        range_obj.status = target_status
        range_obj.save(update_fields=["status", "updated_at"])

    # Invoke ECS task outside the atomic block (don't hold DB lock during network call)
    return _dispatch_lifecycle_ecs(range_obj, request_id, op_name, revert_status, start_range_operation, CloudTaskError)


def _classify_lifecycle_decision(
    status: str,
    *,
    request_id: UUID,
    op_name: str,
    idempotent_statuses: tuple[str, ...],
    required_status: str,
) -> bool | None:
    """Return True / False to short-circuit, or None to proceed with the transition."""
    if status in idempotent_statuses:
        logger.info("%s_range: already %s/%sing request_id=%s", op_name, op_name, op_name, request_id)
        return True
    if status != required_status:
        logger.warning(
            "%s_range: cannot %s range in status=%s request_id=%s",
            op_name,
            op_name,
            status,
            request_id,
        )
        return False
    return None


def _dispatch_lifecycle_ecs(
    range_obj: Range,
    request_id: UUID,
    op_name: str,
    revert_status: str,
    start_range_operation: Callable[[UUID, str], str | None],
    cloud_task_error_cls: type[BaseException],
) -> bool:
    """Invoke the ECS task and revert state on failure."""
    try:
        task_arn = start_range_operation(request_id, op_name)
    except cloud_task_error_cls:
        logger.exception("%s_range: ECS CloudTaskError request_id=%s", op_name, request_id)
        range_obj.status = revert_status
        range_obj.save(update_fields=["status", "updated_at"])
        return False

    if task_arn:
        logger.info("%s_range: started ECS task=%s request_id=%s", op_name, task_arn, request_id)
        return True

    logger.warning("%s_range: ECS returned None, reverting status request_id=%s", op_name, request_id)
    range_obj.status = revert_status
    range_obj.save(update_fields=["status", "updated_at"])
    return False


def pause_range(request_id: UUID) -> bool:
    """Pause all instances in a range. Idempotent."""
    return _run_range_lifecycle_op(
        request_id,
        "pause",
        idempotent_statuses=(ResourceStatus.PAUSED.value, ResourceStatus.PAUSING.value),
        required_status=ResourceStatus.READY.value,
        target_status=ResourceStatus.PAUSING.value,
        revert_status=ResourceStatus.READY.value,
    )


def resume_range(request_id: UUID) -> bool:
    """Resume all instances in a range. Idempotent."""
    return _run_range_lifecycle_op(
        request_id,
        "resume",
        idempotent_statuses=(ResourceStatus.READY.value, ResourceStatus.RESUMING.value),
        required_status=ResourceStatus.PAUSED.value,
        target_status=ResourceStatus.RESUMING.value,
        revert_status=ResourceStatus.PAUSED.value,
    )
