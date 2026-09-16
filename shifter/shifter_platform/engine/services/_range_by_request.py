"""Range lifecycle addressed by provisioning request id.

Split out of ``_range`` (Sonar S104). These entry points resolve a Range via
its Request correlation id -- the pattern CMS and the CTF recovery bridge use
-- and share the teardown/cancel semantics of the range_id-addressed paths.
"""

from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING

from shared.enums import ResourceStatus
from shared.log_sanitize import safe_log_value

from ._common import EngineError, _persist_task_arn

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from django.contrib.auth.models import User

    from engine.models import Range

logger = logging.getLogger(__name__)


class RangeOwnershipTransferBlocked(EngineError):
    """An active participant credential prevents safe in-place ownership transfer."""


class RangeProjectionIntegrityError(EngineError):
    """More than one Engine range correlates to a single provisioning request.

    A request/range correlation is one-to-one, so a duplicate projection is an
    integrity failure the compare-and-set rebind refuses to guess through rather
    than update an arbitrary or every matching row.
    """


class RangeWorkspaceRebindOutcome(enum.Enum):
    """Result of an expected-source compare-and-set workspace rebind.

    The Engine half never resolves or authorizes a workspace (ADR-046-R1); it
    only moves its own scalar projection when the persisted binding matches the
    source the CMS owner expects, so a concurrent move or pre-existing drift is
    reported rather than silently overwritten (last-writer-wins tenant drift).
    """

    UPDATED = "updated"
    """The Engine range carried ``expected_workspace_id`` and now carries the new one."""

    UNCHANGED = "unchanged"
    """The Engine range already carried ``new_workspace_id`` (authorized idempotent no-op)."""

    NOT_FOUND = "not_found"
    """No Engine range correlates to the request."""

    SOURCE_MISMATCH = "source_mismatch"
    """The Engine range carried neither the expected source nor the target (drift/concurrency)."""


def range_owner_reassignment_available_by_request(request_id: UUID) -> bool:
    """Return whether ownership can move without leaving a client credential live."""
    from engine.models import Range

    return Range.objects.filter(request__request_id=request_id, vpn_access_binding__isnull=True).exists()


def destroy_range_by_request(request_id: UUID) -> bool:
    """Tear down range infrastructure by request_id.

    Selects the teardown entrypoint from the persisted, validated
    ``range_config.kind``: an RAES-native range (kind ``raes_provisioning_plan``)
    dispatches ``start_raes_range_teardown`` (the ``raes-range destroy`` command),
    while every legacy range keeps ``start_range_teardown``. The choice derives
    from the persisted plan, never from the current catalog selector or capability
    flag, so an existing RAES range stays destroyable after a rollback empties the
    route or disables the native flag (ADR-031-R6).
    """
    from engine.ecs import start_raes_range_teardown, start_range_teardown
    from engine.models import Range
    from shared.raes.runtime_target import is_raes_provisioning_plan

    logger.debug("destroy_range_by_request: request_id=%s", request_id)
    range_obj = Range.objects.filter(request__request_id=request_id).first()
    if not range_obj:
        logger.warning("destroy_range_by_request: no range for request_id=%s", request_id)
        return False
    teardown = start_raes_range_teardown if is_raes_provisioning_plan(range_obj.range_config) else start_range_teardown
    return _apply_destroy_by_request(range_obj, request_id, teardown)


def _apply_destroy_by_request(
    range_obj: Range,
    request_id: UUID,
    start_range_teardown: Callable[[UUID], str | None],
) -> bool:
    """Status-branch helper for ``destroy_range_by_request`` (same shape as ``_apply_destroy_to_range``)."""
    if range_obj.status == ResourceStatus.DESTROYED.value:
        from ._receipt import revoke_receipt_verifier

        revoke_receipt_verifier(request_id)
        logger.warning("destroy_range_by_request: already destroyed request_id=%s", request_id)
        return False
    if range_obj.status == ResourceStatus.DESTROYING.value:
        from ._receipt import revoke_receipt_verifier

        revoke_receipt_verifier(request_id)
        logger.info("destroy_range_by_request: already destroying request_id=%s", request_id)
        return True

    previous_status = range_obj.status
    range_obj.status = ResourceStatus.DESTROYING.value
    range_obj.save(update_fields=["status"])
    # A destroying materialization must stop authorizing receipt callbacks before
    # provider teardown starts. Revocation is intentionally not rolled back if
    # the external teardown launch fails: a later retry may re-register a new
    # assignment, but stale proof must never become valid again.
    from ._receipt import revoke_receipt_verifier

    revoke_receipt_verifier(request_id)
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

    Only works for ranges in PENDING or PROVISIONING status. Records a durable
    interrupt against the current provision generation (#277) so the launcher
    worker can stop the in-flight task and converge cleanup; the API returns once
    the cancellation is durably accepted, not once resources are absent.
    """
    from django.db import transaction

    from engine.launch_intents import request_provision_interrupt
    from engine.models import Range

    logger.debug("cancel_range_by_request: request_id=%s", request_id)
    with transaction.atomic():
        range_obj = Range.objects.select_for_update().filter(request__request_id=request_id).first()
        if not range_obj:
            logger.warning("cancel_range_by_request: no range for request_id=%s", request_id)
            return False
        settled = _cancellation_already_settled(range_obj, request_id)
        if settled is not None:
            if settled:
                from ._receipt import _revoke_receipt_verifier_for_range

                _revoke_receipt_verifier_for_range(range_obj)
            return settled
        range_obj.status = Range.Status.DESTROYING
        range_obj.save(update_fields=["status"])
        from ._receipt import _revoke_receipt_verifier_for_range

        _revoke_receipt_verifier_for_range(range_obj)
        request_provision_interrupt(range_obj)
        logger.info(
            "cancel_range_by_request: cancelled request_id=%s range_id=%s",
            request_id,
            range_obj.id,
        )
        return True


def _cancellation_already_settled(range_obj: Range, request_id: UUID) -> bool | None:
    """Return the cancellation outcome when the range's status already decides it.

    ``True`` when a teardown is already under way, ``False`` when the status is
    not cancellable, and ``None`` when the caller should proceed with the
    cancellation. Caller holds the row lock.
    """
    from engine.models import Range

    if range_obj.status == Range.Status.DESTROYING:
        logger.info(
            "cancel_range_by_request: already destroying request_id=%s range_id=%s",
            request_id,
            range_obj.id,
        )
        return True
    if range_obj.status in (Range.Status.PENDING, Range.Status.PROVISIONING):
        return None
    logger.warning(
        "cancel_range_by_request: not cancellable status=%s request_id=%s",
        range_obj.status,
        request_id,
    )
    return False


def rebind_range_workspace_by_request(
    request_id: UUID,
    *,
    expected_workspace_id: int,
    new_workspace_id: int,
) -> RangeWorkspaceRebindOutcome:
    """Compare-and-set the Engine range's workspace scope for ``request_id`` (#1325, #1944).

    The Engine half of a range workspace move. CMS owns the decision -- it
    authorizes the move (ADR-046-R1) and updates its own two projections -- and
    calls this so the Engine range's scope moves with them instead of being left
    pointing at the previous tenant. The write is an expected-source
    compare-and-set rather than an unconditional bulk update: it moves the range
    only when the persisted binding is ``expected_workspace_id``, so a concurrent
    move or pre-existing projection drift is reported (``SOURCE_MISMATCH``)
    instead of silently overwritten. A range already at ``new_workspace_id`` is
    an authorized idempotent no-op (``UNCHANGED``).

    Must be called inside the caller's transaction: it takes a row lock via
    ``select_for_update`` so the compare and the set are atomic against
    concurrent rebinds.

    Returns:
        The :class:`RangeWorkspaceRebindOutcome` describing what happened.

    Raises:
        RangeProjectionIntegrityError: If more than one Engine range correlates
            to ``request_id`` (a one-to-one invariant violation).
    """
    from engine.models import Range

    # Sanitize the request-derived correlation id before it reaches any log sink
    # (CodeQL py/log-injection); the internal workspace ints are not user text.
    logged_request_id = safe_log_value(request_id)

    ranges = list(Range.objects.select_for_update().filter(request__request_id=request_id))
    if not ranges:
        logger.warning("rebind_range_workspace_by_request: no range for request_id=%s", logged_request_id)
        return RangeWorkspaceRebindOutcome.NOT_FOUND
    if len(ranges) > 1:
        logger.error(
            "rebind_range_workspace_by_request: expected one engine range for request_id=%s, found %s",
            logged_request_id,
            len(ranges),
        )
        raise RangeProjectionIntegrityError(
            f"expected one engine range for request_id={request_id}, found {len(ranges)}"
        )

    # Single outcome variable + one terminal return keeps the branch count within
    # the cognitive-return limit (Sonar S1142) while preserving each CAS result.
    range_obj = ranges[0]
    if range_obj.workspace_id == new_workspace_id:
        logger.info(
            "rebind_range_workspace_by_request: request_id=%s already at workspace_id=%s (no-op)",
            logged_request_id,
            new_workspace_id,
        )
        outcome = RangeWorkspaceRebindOutcome.UNCHANGED
    elif range_obj.workspace_id != expected_workspace_id:
        logger.warning(
            "rebind_range_workspace_by_request: source mismatch request_id=%s expected=%s actual=%s",
            logged_request_id,
            expected_workspace_id,
            range_obj.workspace_id,
        )
        outcome = RangeWorkspaceRebindOutcome.SOURCE_MISMATCH
    else:
        range_obj.workspace_id = new_workspace_id
        range_obj.save(update_fields=["workspace_id"])
        logger.info(
            "rebind_range_workspace_by_request: request_id=%s rebound workspace_id %s -> %s",
            logged_request_id,
            expected_workspace_id,
            new_workspace_id,
        )
        outcome = RangeWorkspaceRebindOutcome.UPDATED
    return outcome


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
    from django.db import transaction

    from engine.models import Range

    with transaction.atomic():
        range_obj = (
            Range.objects.select_for_update().filter(request__request_id=request_id).select_related("request").first()
        )
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

        # Receipt authorization is server-held, so it can be revoked atomically
        # before the assignment owner changes.  The new owner must receive a new
        # registration revision and assignment epoch.
        from ._receipt import _revoke_receipt_verifier_for_range

        _revoke_receipt_verifier_for_range(range_obj)

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
