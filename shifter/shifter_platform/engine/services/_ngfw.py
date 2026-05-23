"""NGFW lifecycle: create / destroy / start / stop."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from shared.enums import ResourceStatus
from shared.schemas import InstanceSpec, RequestSpec

from ._common import EngineError

logger = logging.getLogger(__name__)


def create_ngfw(request_spec: RequestSpec) -> UUID:
    """Provision NGFW infrastructure."""
    from engine.ecs import start_ngfw_provisioning
    from engine.interpreter import interpret

    ngfw_spec: InstanceSpec | None = None
    for item in request_spec.items:
        if isinstance(item, InstanceSpec) and item.role == "ngfw":
            ngfw_spec = item
            break

    if ngfw_spec is None:
        raise ValueError("RequestSpec must contain an NGFW InstanceSpec")
    if ngfw_spec.ngfw_app is None:
        raise ValueError("ngfw_app is required for NGFW provisioning")
    if not ngfw_spec.ngfw_app.is_hydrated:
        raise ValueError("ngfw_app must be hydrated with credential values")

    request = interpret(request_spec)
    logger.info("create_ngfw: interpreted request_id=%s", request_spec.request_id)

    ngfw_instance = request.instance_instantiations.filter(role="ngfw").first()
    if ngfw_instance:
        task_arn = start_ngfw_provisioning(request.request_id)
        if task_arn:
            logger.info(
                "create_ngfw: started ECS task=%s for request=%s",
                task_arn,
                request.request_id,
            )

    return request.request_id


def destroy_ngfw(request_id: UUID) -> bool:
    """Tear down NGFW infrastructure."""
    from engine.ecs import start_ngfw_teardown
    from engine.models import Instance, Range, Request

    logger.debug("destroy_ngfw: request_id=%s", request_id)

    try:
        request = Request.objects.get(request_id=request_id)
    except Request.DoesNotExist:
        logger.warning("destroy_ngfw: request not found request_id=%s", request_id)
        return False

    ngfw_instance = Instance.objects.filter(request=request, role="ngfw").first()
    if not ngfw_instance:
        logger.warning("destroy_ngfw: no NGFW instance found for request_id=%s", request_id)
        return False

    attached_ranges = Range.objects.filter(
        ngfw_instance=ngfw_instance,
        status__in=[
            Range.Status.READY,
            Range.Status.PENDING,
            Range.Status.PROVISIONING,
            Range.Status.PAUSED,
            Range.Status.RESUMING,
        ],
    )
    if attached_ranges.exists():
        count = attached_ranges.count()
        range_ids = list(attached_ranges.values_list("id", flat=True)[:5])
        raise EngineError(
            f"Cannot delete NGFW: {count} range(s) are still attached. Delete these ranges first: {range_ids}"
        )

    task_arn = start_ngfw_teardown(request_id)
    if task_arn:
        logger.info("destroy_ngfw: started ECS task=%s for request=%s", task_arn, request_id)
    return task_arn is not None


def _resolve_ngfw_instance_for_lifecycle(
    request_id: UUID, op_name: str, allowed_statuses: tuple[str, ...]
) -> Any | None:
    """Return the NGFW Instance row when it exists and its status permits ``op_name``."""
    from engine.models import Instance, Request

    try:
        request = Request.objects.get(request_id=request_id)
    except Request.DoesNotExist:
        logger.warning("%s_ngfw: request not found request_id=%s", op_name, request_id)
        return None

    ngfw_instance = Instance.objects.filter(request=request, role="ngfw").first()
    if not ngfw_instance:
        logger.warning("%s_ngfw: no NGFW instance found for request_id=%s", op_name, request_id)
        return None

    if ngfw_instance.status not in allowed_statuses:
        logger.warning(
            "%s_ngfw: invalid status=%s for request_id=%s (allowed=%s)",
            op_name,
            ngfw_instance.status,
            request_id,
            allowed_statuses,
        )
        return None

    return ngfw_instance


def _run_ngfw_lifecycle_op(request_id: UUID, op_name: str, allowed_statuses: tuple[str, ...]) -> bool:
    """Shared start/stop NGFW transition + ECS-dispatch helper."""
    from engine.ecs import start_ngfw_operation

    logger.debug("%s_ngfw: request_id=%s", op_name, request_id)

    ngfw_instance = _resolve_ngfw_instance_for_lifecycle(request_id, op_name, allowed_statuses)
    if ngfw_instance is None:
        return False

    task_arn = start_ngfw_operation(request_id, op_name)
    if task_arn:
        logger.info("%s_ngfw: started ECS task=%s for request=%s", op_name, task_arn, request_id)
    return task_arn is not None


def start_ngfw(request_id: UUID) -> bool:
    """Start a stopped NGFW instance."""
    return _run_ngfw_lifecycle_op(
        request_id,
        "start",
        (ResourceStatus.PAUSED.value, ResourceStatus.FAILED.value),
    )


def stop_ngfw(request_id: UUID) -> bool:
    """Stop a running NGFW instance."""
    return _run_ngfw_lifecycle_op(
        request_id,
        "stop",
        (ResourceStatus.READY.value,),
    )
