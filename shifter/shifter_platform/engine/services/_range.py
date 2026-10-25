"""Range destroy / cancel / status / IP lookup compatibility services."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from shared.enums import CANCELLABLE_STATUSES, ResourceStatus
from shared.raes.runtime_target import is_raes_provisioning_plan
from shared.range_lifecycle_capability import LifecycleCapability, range_pause_resume_capability
from shared.schemas import RangeRef

from ._common import _persist_task_arn, _resolve_instance_host
from ._range_by_request import cancel_range_by_request, destroy_range_by_request

if TYPE_CHECKING:
    from contextlib import AbstractContextManager as ContextManager

    from engine.models import Range

logger = logging.getLogger(__name__)


def _atomic() -> ContextManager[None]:
    """Late-bound ``engine.services.transaction.atomic()`` so tests can patch the package-level name."""
    from engine import services as _es

    return _es.transaction.atomic()


def destroy_range(range_ref: RangeRef) -> bool:
    """Tear down range infrastructure.

    Sets status to DESTROYING and triggers async ECS teardown.
    Idempotent: returns True if range is already being destroyed.

    Supports both legacy (range_id) and new (request_id) patterns.
    """
    from engine.ecs import start_teardown
    from engine.models import Range

    if not isinstance(range_ref, RangeRef):
        raise TypeError(f"range_ref must be RangeRef, got {type(range_ref).__name__}")

    if range_ref.range_id is None:
        return _destroy_via_request_id(range_ref.request_id)

    logger.debug("destroy_range: range_id=%s", range_ref.range_id)
    try:
        range_obj = Range.objects.get(id=range_ref.range_id)
    except Range.DoesNotExist:
        logger.warning("destroy_range: range not found range_id=%s", range_ref.range_id)
        return False
    return _apply_destroy_to_range(range_obj, range_ref.range_id, range_ref.user_id, start_teardown)


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
        _revoke_receipt_for_range_request(range_obj)
        logger.warning("destroy_range: range already destroyed range_id=%s", range_id)
        return False
    if range_obj.status == ResourceStatus.DESTROYING:
        _revoke_receipt_for_range_request(range_obj)
        logger.info("destroy_range: range already destroying range_id=%s", range_id)
        return True

    previous_status = range_obj.status
    range_obj.status = ResourceStatus.DESTROYING.value
    range_obj.save(update_fields=["status"])
    _revoke_receipt_for_range_request(range_obj)
    logger.info("destroy_range: set status to DESTROYING range_id=%s", range_id)

    try:
        task_arn = start_teardown(range_id, user_id)
    except Exception:
        range_obj.status = previous_status
        range_obj.save(update_fields=["status", "updated_at"])
        raise
    if task_arn:
        _persist_task_arn(range_obj, "destroy", task_arn)
        logger.info("destroy_range: started ECS task=%s", task_arn)
    return True


def cancel_range(range_ref: RangeRef) -> None:
    """Cancel in-progress provisioning.

    Only works for ranges in PENDING or PROVISIONING status.
    Sets status directly to DESTROYING without triggering teardown.
    """
    if range_ref is None:
        logger.error("cancel_range called with None range_ref")
        raise TypeError("range_ref cannot be None")
    if not isinstance(range_ref, RangeRef):
        logger.error("cancel_range called with invalid type: %s", type(range_ref).__name__)
        raise TypeError(f"range_ref must be RangeRef, got {type(range_ref).__name__}")

    if range_ref.range_id is None:
        if range_ref.request_id:
            cancel_range_by_request(range_ref.request_id)
            return
        logger.error("cancel_range called with both range_id and request_id as None")
        raise ValueError("range_ref must have either range_id or request_id")

    if not isinstance(range_ref.range_id, int) or range_ref.range_id < 0:
        logger.error("cancel_range called with invalid range_id: %s", range_ref.range_id)
        raise ValueError("range_ref.range_id must be a non-negative integer")

    logger.debug(
        "cancel_range: range_id=%s user_id=%s status=%s",
        range_ref.range_id,
        range_ref.user_id,
        range_ref.status,
    )
    from engine.launch_intents import request_provision_interrupt
    from engine.models import Range

    range_id = range_ref.range_id
    with _atomic():
        try:
            range_obj = Range.objects.select_for_update().get(id=range_id)
        except Range.DoesNotExist:
            logger.warning("cancel_range: range not found range_id=%s", range_id)
            return

        if ResourceStatus(range_obj.status) not in CANCELLABLE_STATUSES:
            if range_obj.status in {Range.Status.DESTROYING, Range.Status.DESTROYED, Range.Status.FAILED}:
                from ._receipt import _revoke_receipt_verifier_for_range

                _revoke_receipt_verifier_for_range(range_obj)
            logger.warning(
                "cancel_range: range not cancellable range_id=%s status=%s",
                range_id,
                range_obj.status,
            )
            return

        range_obj.status = Range.Status.DESTROYING
        range_obj.save(update_fields=["status"])
        from ._receipt import _revoke_receipt_verifier_for_range

        _revoke_receipt_verifier_for_range(range_obj)
        # Record a durable interrupt against the current provision generation
        # (#277); the launcher worker stops the in-flight task and converges the
        # canonical destroy. No teardown is dispatched inline here.
        request_provision_interrupt(range_obj)
        logger.info("cancel_range: cancelled range_id=%s", range_id)


def _revoke_receipt_for_range_request(range_obj: Range) -> None:
    """Durably invalidate a receipt registration before teardown dispatch."""
    request = range_obj.request
    if request is None:
        return
    from ._receipt import revoke_receipt_verifier

    revoke_receipt_verifier(request.request_id)


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


def get_range_pause_resume_capability(range_id: int) -> LifecycleCapability:
    """Return whether the range's realized asset mix is losslessly pause/resume-safe.

    Reads the engine-owned realized instances and classifies them through the
    shared capability policy (ADR-039, issue #614). This is the single source the
    Mission Control projection and the CMS lifecycle gate consume so the SPA never
    infers capability from provider names or asset types. A range with no realized
    instances (not yet provisioned) is vacuously supported; pause/resume is offered
    only once the range is READY.
    """
    status = get_range_status(range_id)
    if (status or {}).get("native_raes"):
        return LifecycleCapability(
            supported=False,
            reason="Pause and resume are not available for native scenario ranges.",
            unsupported_assets=(),
        )
    instances = (status or {}).get("instances") or []
    assets = [
        (instance.get("cloud_provider"), instance.get("asset_type"))
        for instance in instances
        if isinstance(instance, dict)
    ]
    backend = (status or {}).get("range_backend")
    return range_pause_resume_capability(backend, assets)


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
        # The persisted adapter-selection binding (ADR-039): pause/resume capability
        # admits only assets belonging to this backend (issue #614).
        "range_backend": range_obj.range_backend,
        "native_raes": is_raes_provisioning_plan(range_obj.range_config),
        "created_at": (range_obj.created_at.isoformat() if range_obj.created_at else None),
        "ready_at": range_obj.ready_at.isoformat() if range_obj.ready_at else None,
    }
