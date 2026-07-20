"""Range CRUD: create / destroy / cancel / status / IP lookup."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from shared.enums import CANCELLABLE_STATUSES, ResourceStatus
from shared.range_cells import build_scenario_artifact
from shared.remote_access import parse_openvpn_capability
from shared.schemas import RangeRef, RangeSpec, RequestSpec
from shared.schemas.persistence import wrap_persisted_spec

from ._common import EngineError, _persist_task_arn, _resolve_instance_host
from ._range_backend_binding import backend_binding_fields, verify_existing_binding
from ._range_by_request import cancel_range_by_request, destroy_range_by_request

if TYPE_CHECKING:
    from contextlib import AbstractContextManager as ContextManager

    from django.contrib.auth.models import User

    from engine.models import Range
    from shared.range_instantiation_policy import BackendAdmission

logger = logging.getLogger(__name__)


def _range_ref_from_range(range_obj: Range, request_spec: RequestSpec, range_spec: RangeSpec) -> RangeRef:
    """Build a RangeRef from an existing/persisted engine Range."""
    return RangeRef(
        request_id=request_spec.request_id,
        range_id=range_obj.id,
        user_id=range_spec.user_id,
        status=ResourceStatus(range_obj.status),
    )


def _atomic() -> ContextManager[None]:
    """Late-bound ``engine.services.transaction.atomic()`` so tests can patch the package-level name."""
    from engine import services as _es

    return _es.transaction.atomic()


def create_range(
    request_spec: RequestSpec,
    *,
    backend_admission: BackendAdmission | None = None,
    remote_access_capability: dict[str, object] | None = None,
) -> RangeRef:
    """Provision infrastructure for range.

    Interprets the RequestSpec into Engine models (Request, Instance),
    creates a Range record for backward compat, and triggers ECS provisioning.

    ``backend_admission`` is the trusted #1348 CMS admission result, carried
    beside (never inside) the RequestSpec. When present (GCP), the normalized
    (backend, purpose) is persisted as the write-once #1666 ownership binding in
    the same transaction as the Range, before dispatch, so destroy/reconcile
    route from it instead of the mutable process selector. ``None`` on non-GCP.
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

    normalized_remote_access = (
        parse_openvpn_capability(remote_access_capability).as_dict() if remote_access_capability is not None else None
    )
    existing_range = Range.objects.filter(request__request_id=request_spec.request_id).first()
    if existing_range is not None:
        logger.info("create_range: reusing existing range request_id=%s", request_spec.request_id)
        verify_existing_binding(existing_range, request_spec.request_id, backend_admission)
        if existing_range.remote_access_capability != normalized_remote_access:
            raise EngineError("Existing range remote-access capability does not match the create request")
        return _range_ref_from_range(existing_range, request_spec, range_spec)

    range_obj = _persist_range_atomically(
        request_spec,
        range_spec,
        user_model,
        Range,
        backend_admission,
        normalized_remote_access,
    )

    try:
        task_arn = start_range_provisioning(request_spec.request_id)
    except Exception:
        range_obj.status = Range.Status.FAILED
        range_obj.error_message = "Provisioning dispatch failed"
        range_obj.save(update_fields=["status", "error_message", "updated_at"])
        raise
    if task_arn:
        _persist_task_arn(range_obj, "provision", task_arn)
        logger.info("create_range: started ECS task=%s", task_arn)

    return _range_ref_from_range(range_obj, request_spec, range_spec)


def _persist_range_atomically(
    request_spec: RequestSpec,
    range_spec: RangeSpec,
    user_model: type[User],
    range_model: type[Range],
    backend_admission: BackendAdmission | None = None,
    remote_access_capability: dict[str, object] | None = None,
) -> Range:
    """Run the interpret + Range + Subnet inserts under a single transaction.

    The #1666 backend/purpose ownership binding (when present) is written on the
    Range in this same transaction, before any launch dispatch, so it is durable
    ownership from the instant the range exists.
    """
    from engine.interpreter import interpret
    from engine.models import Subnet

    binding_fields = backend_binding_fields(backend_admission)
    remote_access_fields = (
        {"remote_access_capability": remote_access_capability} if remote_access_capability is not None else {}
    )

    with _atomic():
        request = interpret(request_spec)
        logger.info("create_range: interpreted request_id=%s", request_spec.request_id)

        user = user_model.objects.get(id=range_spec.user_id)
        subnet_index = range_model.allocate_subnet_index()
        range_artifact = build_scenario_artifact(wrap_persisted_spec("range_spec", range_spec))

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
                range_config=range_artifact,
                **remote_access_fields,
                **binding_fields,
            )
        else:
            range_obj = range_model.objects.create(
                user=user,
                request=request,
                cms_user_id=range_spec.user_id,
                status=range_model.Status.PROVISIONING,
                subnet_index=subnet_index,
                range_config=range_artifact,
                **remote_access_fields,
                **binding_fields,
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
        logger.warning("destroy_range: range already destroyed range_id=%s", range_id)
        return False
    if range_obj.status == ResourceStatus.DESTROYING:
        logger.info("destroy_range: range already destroying range_id=%s", range_id)
        return True

    previous_status = range_obj.status
    range_obj.status = ResourceStatus.DESTROYING.value
    range_obj.save(update_fields=["status"])
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
    from engine.models import Range

    range_id = range_ref.range_id
    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("cancel_range: range not found range_id=%s", range_id)
        return

    if ResourceStatus(range_obj.status) not in CANCELLABLE_STATUSES:
        logger.warning(
            "cancel_range: range not cancellable range_id=%s status=%s",
            range_id,
            range_obj.status,
        )
        return

    range_obj.status = Range.Status.DESTROYING
    range_obj.save(update_fields=["status"])
    # Provisioner will poll for status and destroy when it sees DESTROYING
    # accept small risk of race condition. TODO: #465
    logger.info("cancel_range: cancelled range_id=%s", range_id)


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
