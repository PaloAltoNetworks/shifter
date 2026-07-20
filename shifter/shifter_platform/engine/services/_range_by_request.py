"""Range lifecycle addressed by provisioning request id.

Split out of ``_range`` (Sonar S104). These entry points resolve a Range via
its Request correlation id -- the pattern CMS and the CTF recovery bridge use
-- and share the teardown/cancel semantics of the range_id-addressed paths.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from shared.enums import ResourceStatus

from ._common import EngineError, _persist_task_arn

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from django.contrib.auth.models import User

    from engine.models import Range

logger = logging.getLogger(__name__)


class RangeOwnershipTransferBlocked(EngineError):
    """An active participant credential prevents safe in-place ownership transfer."""


def range_owner_reassignment_available_by_request(request_id: UUID) -> bool:
    """Return whether ownership can move without leaving a client credential live."""
    from engine.models import Range

    return Range.objects.filter(request__request_id=request_id, vpn_access_binding__isnull=True).exists()


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

    previous_status = range_obj.status
    range_obj.status = ResourceStatus.DESTROYING.value
    range_obj.save(update_fields=["status"])
    logger.info(
        "destroy_range_by_request: set DESTROYING request_id=%s range_id=%s",
        request_id,
        range_obj.id,
    )

    try:
        task_arn = start_range_teardown(request_id)
    except Exception:
        range_obj.status = previous_status
        range_obj.save(update_fields=["status", "updated_at"])
        raise
    if task_arn:
        _persist_task_arn(range_obj, "destroy", task_arn)
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
        accepted = False
    elif range_obj.status == Range.Status.DESTROYING:
        logger.info(
            "cancel_range_by_request: already destroying request_id=%s range_id=%s",
            request_id,
            range_obj.id,
        )
        accepted = True
    elif range_obj.status not in (Range.Status.PENDING, Range.Status.PROVISIONING):
        logger.warning(
            "cancel_range_by_request: not cancellable status=%s request_id=%s",
            range_obj.status,
            request_id,
        )
        accepted = False
    else:
        range_obj.status = Range.Status.DESTROYING
        range_obj.save(update_fields=["status"])
        logger.info(
            "cancel_range_by_request: cancelled request_id=%s range_id=%s",
            request_id,
            range_obj.id,
        )
        accepted = True

    return accepted


def reassign_range_owner_by_request(request_id: UUID, new_user: User) -> bool:
    """Reassign the ``Range``/``Request`` owner for ``request_id`` to ``new_user``.

    Used by CMS's cross-owner range-recovery path (``cms.services.reassign_range_owner``,
    called from ``ctf.services.range.recovery`` via ``ctf.bridges``) to transfer
    terminal/Guacamole access -- which resolves strictly by ``Range.user``
    (``Range.resolve_active_for_instance`` / ``Range.get_active_for_user``) -- to a
    new participant. Idempotent: returns True without writing when the range is
    already owned by ``new_user``.

    Returns:
        True if a range was found (and reassigned or already owned by
        ``new_user``), False if no range exists for ``request_id``.
    """
    from engine.models import Range

    range_obj = Range.objects.filter(request__request_id=request_id).select_related("request").first()
    if not range_obj:
        logger.warning("reassign_range_owner_by_request: no range for request_id=%s", request_id)
        return False

    if range_obj.user_id == new_user.id:
        logger.info(
            "reassign_range_owner_by_request: already owned by user_id=%s request_id=%s",
            new_user.id,
            request_id,
        )
        return True

    if range_obj.vpn_access_binding is not None:
        # The downloaded client credential is already outside platform custody.
        # Refuse the ownership change rather than leave it valid for a former
        # participant. Callers must destroy the generation (which removes the
        # gateway and all secrets) and provision a replacement for the new owner.
        raise RangeOwnershipTransferBlocked("Range ownership cannot change while participant VPN access is active")

    range_obj.user = new_user
    range_obj.cms_user_id = new_user.id
    range_obj.save(update_fields=["user", "cms_user_id"])

    if range_obj.request is not None:
        range_obj.request.user = new_user
        range_obj.request.save(update_fields=["user"])

    logger.info(
        "reassign_range_owner_by_request: reassigned range_id=%s request_id=%s to user_id=%s",
        range_obj.id,
        request_id,
        new_user.id,
    )
    return True
