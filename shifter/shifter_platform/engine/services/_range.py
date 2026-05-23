"""Range CRUD: create / destroy / cancel / status / IP lookup."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from shared.enums import CANCELLABLE_STATUSES, ResourceStatus
from shared.schemas import RangeContext, RangeSpec, RequestSpec

from ._common import EngineError, _resolve_instance_host

if TYPE_CHECKING:
    from engine.models import Range

logger = logging.getLogger(__name__)


def _atomic() -> Any:
    """Late-bound ``engine.services.transaction.atomic()`` so tests can patch the package-level name."""
    from engine import services as _es

    return _es.transaction.atomic()


def create_range(request_spec: RequestSpec) -> UUID:
    """Provision infrastructure for range.

    Interprets the RequestSpec into Engine models (Request, Instance),
    creates a Range record for backward compat, and triggers ECS provisioning.
    """
    from django.contrib.auth import get_user_model

    from engine.ecs import start_range_provisioning
    from engine.models import Range

    user_model = get_user_model()

    if not isinstance(request_spec, RequestSpec):
        raise TypeError(f"request_spec must be RequestSpec, got {type(request_spec).__name__}")

    range_spec: RangeSpec | None = None
    for item in request_spec.items:
        if isinstance(item, RangeSpec):
            range_spec = item
            break
    if range_spec is None:
        raise ValueError("RequestSpec must contain a RangeSpec item")

    logger.debug(
        "create_range: scenario=%s user_id=%s subnets=%d instances=%d",
        range_spec.scenario_id,
        range_spec.user_id,
        len(range_spec.subnets),
        len(range_spec.all_instances),
    )

    range_obj = _persist_range_atomically(request_spec, range_spec, user_model, Range)

    task_arn = start_range_provisioning(request_spec.request_id)
    if task_arn:
        range_obj.step_function_execution_arn = task_arn
        range_obj.save(update_fields=["step_function_execution_arn"])
        logger.info("create_range: started ECS task=%s", task_arn)

    return request_spec.request_id


def _persist_range_atomically(
    request_spec: RequestSpec,
    range_spec: RangeSpec,
    user_model: Any,
    range_model: Any,
) -> Range:
    """Run the interpret + Range + Subnet inserts under a single transaction."""
    from engine.interpreter import interpret
    from engine.models import Subnet

    with _atomic():
        request = interpret(request_spec)
        logger.info("create_range: interpreted request_id=%s", request_spec.request_id)

        user = user_model.objects.get(id=range_spec.user_id)
        subnet_index = range_model.allocate_subnet_index()

        range_uuid = range_spec.uuid
        if range_uuid:
            import uuid as uuid_module

            range_obj = range_model.objects.create(
                uuid=uuid_module.UUID(range_uuid),
                user=user,
                request=request,
                cms_user_id=range_spec.user_id,
                status=range_model.Status.PROVISIONING,
                subnet_index=subnet_index,
                range_config=range_spec.model_dump(),
            )
        else:
            range_obj = range_model.objects.create(
                user=user,
                request=request,
                cms_user_id=range_spec.user_id,
                status=range_model.Status.PROVISIONING,
                subnet_index=subnet_index,
                range_config=range_spec.model_dump(),
            )

        logger.info(
            "create_range: created range_id=%s uuid=%s subnet_index=%s request_id=%s",
            range_obj.id,
            range_obj.uuid,
            subnet_index,
            request_spec.request_id,
        )

        subnet_count = Subnet.objects.filter(request=request).update(range=range_obj)
        if subnet_count == 0:
            raise EngineError(
                f"No subnets linked to range {range_obj.id} for request {request_spec.request_id}. "
                "This indicates the scenario template is missing subnet definitions."
            )

        logger.info(
            "create_range: linked %d subnets to range_id=%s",
            subnet_count,
            range_obj.id,
        )

    return range_obj


def destroy_range(request: RangeContext) -> bool:
    """Tear down range infrastructure.

    Sets status to DESTROYING and triggers async ECS teardown.
    Idempotent: returns True if range is already being destroyed.

    Supports both legacy (range_id) and new (request_id) patterns.
    """
    from engine.ecs import start_teardown
    from engine.models import Range

    if request.range_id is None:
        return _destroy_via_request_id(request.request_id)

    logger.debug("destroy_range: range_id=%s", request.range_id)
    try:
        range_obj = Range.objects.get(id=request.range_id)
    except Range.DoesNotExist:
        logger.warning("destroy_range: range not found range_id=%s", request.range_id)
        return False
    return _apply_destroy_to_range(range_obj, request.range_id, request.user_id, start_teardown)


def _destroy_via_request_id(request_id: UUID | None) -> bool:
    """Fan out the ``destroy_range`` no-range_id branch to ``destroy_range_by_request``."""
    if not request_id:
        logger.warning("destroy_range: both range_id and request_id are None")
        return False
    return destroy_range_by_request(request_id)


def _apply_destroy_to_range(
    range_obj: Range,
    range_id: int,
    user_id: int,
    start_teardown: Callable[[int, int], str | None],
) -> bool:
    """Status-branch helper for ``destroy_range`` so the caller stays under the return-count cap."""
    if range_obj.status == ResourceStatus.DESTROYED:
        logger.warning("destroy_range: range already destroyed range_id=%s", range_id)
        return False
    if range_obj.status == ResourceStatus.DESTROYING:
        logger.info("destroy_range: range already destroying range_id=%s", range_id)
        return True

    range_obj.status = ResourceStatus.DESTROYING.value
    range_obj.save(update_fields=["status"])
    logger.info("destroy_range: set status to DESTROYING range_id=%s", range_id)

    task_arn = start_teardown(range_id, user_id)
    if task_arn:
        range_obj.step_function_execution_arn = task_arn
        range_obj.save(update_fields=["step_function_execution_arn"])
        logger.info("destroy_range: started ECS task=%s", task_arn)
    return True


def cancel_range(range_ctx: RangeContext) -> None:
    """Cancel in-progress provisioning.

    Only works for ranges in PENDING or PROVISIONING status.
    Sets status directly to DESTROYING without triggering teardown.
    """
    if range_ctx is None:
        logger.error("cancel_range called with None range_ctx")
        raise TypeError("range_ctx cannot be None")
    if not isinstance(range_ctx, RangeContext):
        logger.error("cancel_range called with invalid type: %s", type(range_ctx).__name__)
        raise TypeError(f"range_ctx must be RangeContext, got {type(range_ctx).__name__}")

    if range_ctx.range_id is None:
        if range_ctx.request_id:
            cancel_range_by_request(range_ctx.request_id)
            return
        logger.error("cancel_range called with both range_id and request_id as None")
        raise ValueError("range_ctx must have either range_id or request_id")

    if not isinstance(range_ctx.range_id, int) or range_ctx.range_id < 0:
        logger.error("cancel_range called with invalid range_id: %s", range_ctx.range_id)
        raise ValueError("range_ctx.range_id must be a non-negative integer")

    logger.debug(
        "cancel_range: range_id=%s user_id=%s status=%s",
        range_ctx.range_id,
        range_ctx.user_id,
        range_ctx.status,
    )
    from engine.models import Range

    range_id = range_ctx.range_id
    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("cancel_range: range not found range_id=%s", range_id)
        return

    if range_ctx.status not in CANCELLABLE_STATUSES:
        logger.warning(
            "cancel_range: range not cancellable range_id=%s status=%s",
            range_id,
            range_ctx.status,
        )
        return

    range_ctx.status = ResourceStatus.DESTROYING
    range_obj.status = Range.Status.DESTROYING
    range_obj.save(update_fields=["status"])
    # Provisioner will poll for status and destroy when it sees DESTROYING
    # accept small risk of race condition. TODO: #465
    logger.info("cancel_range: cancelled range_id=%s", range_id)


def destroy_range_by_request(request_id: UUID) -> bool:
    """Tear down range infrastructure by request_id.

    Follows same pattern as destroy_ngfw(). Looks up Range via Request FK
    and triggers ECS teardown.
    """
    from engine.ecs import start_range_teardown
    from engine.models import Range

    logger.debug("destroy_range_by_request: request_id=%s", request_id)
    range_obj = Range.objects.filter(request__request_id=request_id).first()
    if not range_obj:
        logger.warning("destroy_range_by_request: no range for request_id=%s", request_id)
        return False
    return _apply_destroy_by_request(range_obj, request_id, start_range_teardown)


def _apply_destroy_by_request(
    range_obj: Range,
    request_id: UUID,
    start_range_teardown: Callable[[UUID], str | None],
) -> bool:
    """Status-branch helper for ``destroy_range_by_request`` (same shape as ``_apply_destroy_to_range``)."""
    if range_obj.status == ResourceStatus.DESTROYED.value:
        logger.warning("destroy_range_by_request: already destroyed request_id=%s", request_id)
        return False
    if range_obj.status == ResourceStatus.DESTROYING.value:
        logger.info("destroy_range_by_request: already destroying request_id=%s", request_id)
        return True

    range_obj.status = ResourceStatus.DESTROYING.value
    range_obj.save(update_fields=["status"])
    logger.info(
        "destroy_range_by_request: set DESTROYING request_id=%s range_id=%s",
        request_id,
        range_obj.id,
    )

    task_arn = start_range_teardown(request_id)
    if task_arn:
        range_obj.step_function_execution_arn = task_arn
        range_obj.save(update_fields=["step_function_execution_arn"])
        logger.info("destroy_range_by_request: started ECS task=%s", task_arn)
    return True


def cancel_range_by_request(request_id: UUID) -> bool:
    """Cancel in-progress range provisioning by request_id.

    Only works for ranges in PENDING or PROVISIONING status.
    """
    from engine.models import Range

    logger.debug("cancel_range_by_request: request_id=%s", request_id)
    range_obj = Range.objects.filter(request__request_id=request_id).first()
    if not range_obj:
        logger.warning("cancel_range_by_request: no range for request_id=%s", request_id)
        return False

    if range_obj.status not in (Range.Status.PENDING, Range.Status.PROVISIONING):
        logger.warning(
            "cancel_range_by_request: not cancellable status=%s request_id=%s",
            range_obj.status,
            request_id,
        )
        return False

    range_obj.status = Range.Status.DESTROYING
    range_obj.save(update_fields=["status"])
    logger.info(
        "cancel_range_by_request: cancelled request_id=%s range_id=%s",
        request_id,
        range_obj.id,
    )
    return True


def get_instance_ips_by_uuid(range_id: int) -> dict[str, str]:
    """Return a {uuid: internal_ip} map for the range's provisioned instances."""
    status = get_range_status(range_id)
    if not status:
        return {}

    result: dict[str, str] = {}
    for instance in status.get("instances") or []:
        if not isinstance(instance, dict):
            continue
        uuid_value = instance.get("uuid")
        if not isinstance(uuid_value, str) or not uuid_value.strip():
            continue
        ip_value = _resolve_instance_host(instance)
        if not ip_value:
            continue
        result[uuid_value.strip()] = ip_value
    return result


def get_range_status(range_id: int) -> dict[str, Any] | None:
    """Get current state and instance details.

    Returns dict with range status info, or None if not found.
    Keys: status, error_message, instances, created_at, ready_at
    """
    from engine.models import Range

    logger.debug("get_range_status: range_id=%s", range_id)
    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("get_range_status: range not found range_id=%s", range_id)
        return None

    return {
        "status": range_obj.status,
        "error_message": range_obj.error_message,
        "instances": range_obj.provisioned_instances or [],
        "created_at": (range_obj.created_at.isoformat() if range_obj.created_at else None),
        "ready_at": range_obj.ready_at.isoformat() if range_obj.ready_at else None,
    }
