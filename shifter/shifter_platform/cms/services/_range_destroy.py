"""Range destroy/cancel entrypoints (by range_id and by request_id)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.utils import timezone

from cms.exceptions import CMSError
from cms.models import RangeInstance
from risk_register.models import AuditLog
from shared.constants import USER_CANNOT_BE_NONE
from shared.enums import ResourceStatus

from ._common import _validate_caller_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

# Shared error message for "Range not found" so we don't duplicate the literal (python:S1192).
_RANGE_NOT_FOUND_MSG = "Range not found"


def _engine_destroy_range_by_request_call(request_id: UUID) -> bool:
    """Late-bound call so test patches of cms.services.engine_destroy_range_by_request apply."""
    from cms import services as _cs

    result: bool = _cs.engine_destroy_range_by_request(request_id)
    return result


def _engine_cancel_range_by_request_call(request_id: UUID) -> bool:
    """Late-bound call so test patches of cms.services.engine_cancel_range_by_request apply."""
    from cms import services as _cs

    result: bool = _cs.engine_cancel_range_by_request(request_id)
    return result


_TransitionSpec = tuple[str, Callable[[UUID], bool], AuditLog.Action, str, str, bool]
_DESTROY_TRANSITION: _TransitionSpec = (
    ResourceStatus.DESTROYING.value,
    _engine_destroy_range_by_request_call,
    AuditLog.Action.DEPROVISION,
    "Range cannot be destroyed in current state",
    "destroy_range",
    True,
)
_CANCEL_TRANSITION: _TransitionSpec = (
    ResourceStatus.DESTROYING.value,
    _engine_cancel_range_by_request_call,
    AuditLog.Action.CANCEL,
    "Range cannot be cancelled in current state",
    "cancel_range",
    False,
)


def _audit_log_call(**kwargs: Any) -> None:  # NOSONAR
    """Late-bound call to ``cms.services.audit_log`` so test patches apply."""
    from cms import services as _cs

    _cs.audit_log(_cs.AuditEvent(**kwargs))


def _get_range_call(user: User, range_id: int) -> RangeInstance:
    """Look up range through the package so test patches apply."""
    from cms import services as _cs

    return _cs.get_range(user, range_id)


def _transition_then_dispatch(
    *,
    instance: RangeInstance,
    request_id: UUID,
    user: User,
    audit_entity_id: int,
    transition: _TransitionSpec,
) -> None:
    """Apply a CMS lifecycle transition, dispatch engine cleanup, and revert on rejection."""
    target_status, engine_call, audit_action, failure_message, label, soft_delete = transition
    previous_status = instance.status
    previous_deleted_at = instance.deleted_at
    status_changed = previous_status != target_status or (soft_delete and previous_deleted_at is None)

    if status_changed:
        instance.status = target_status
        update_fields = ["status"]
        if soft_delete:
            instance.deleted_at = timezone.now()
            update_fields.append("deleted_at")
        instance.save(update_fields=update_fields)

    try:
        accepted = engine_call(request_id)
    except Exception:
        _restore_range_instance_status(instance, previous_status, previous_deleted_at)
        raise

    if not accepted:
        _restore_range_instance_status(instance, previous_status, previous_deleted_at)
        logger.warning("%s: engine rejected cleanup request_id=%s", label, request_id)
        raise CMSError(failure_message)

    if status_changed:
        _audit_log_call(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=audit_entity_id,
            action=audit_action,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            previous_state={
                "status": previous_status,
                "scenario": instance.scenario_id,
            },
            new_state={"status": target_status},
            request_id=str(request_id),
        )


def _restore_range_instance_status(
    instance: RangeInstance,
    previous_status: str,
    previous_deleted_at: datetime | None,
) -> None:
    """Restore CMS status/deleted_at after engine cleanup dispatch rejects."""
    instance.status = previous_status
    instance.deleted_at = previous_deleted_at
    instance.save(update_fields=["status", "deleted_at"])


def destroy_range(user: User, range_instance_pk: int) -> None:
    """Tear down range.

    Fetches RangeInstance, verifies ownership, updates CMS status to DESTROYING,
    then delegates to engine.services.destroy_range with RangeContext.

    The PK is the identifier callers hold (``find_range_instance_id_by_request``
    and ``get_range_status_by_id`` are PK-keyed); lookups must use the PK, not
    the legacy nullable ``RangeInstance.range_id`` engine field (issue #1139).

    Args:
        user: User requesting destruction
        range_instance_pk: PK of the RangeInstance to destroy

    Returns:
        None

    Raises:
        TypeError: If user is None, invalid type, or range_instance_pk is invalid type
        ValueError: If user has no ID (unsaved) or range_instance_pk is invalid
        CMSError: If range not found or not owned by user
        EngineError: If engine fails to destroy range
    """
    _validate_caller_user(user, "destroy_range")

    if range_instance_pk is None:
        logger.error(
            "destroy_range called with None range_instance_pk for user_id=%s",
            user.id,
        )
        raise TypeError("range_instance_pk cannot be None")

    if not isinstance(range_instance_pk, int):
        logger.error(
            "destroy_range called with invalid range_instance_pk type: %s",
            type(range_instance_pk).__name__,
        )
        msg = f"range_instance_pk must be an int, got {type(range_instance_pk).__name__}"
        raise TypeError(msg)

    if range_instance_pk < 0:
        logger.error(
            "destroy_range called with negative range_instance_pk=%s for user_id=%s",
            range_instance_pk,
            user.id,
        )
        raise ValueError("range_instance_pk must be non-negative")

    logger.debug(
        "destroy_range called for user_id=%s, range_instance_pk=%s",
        user.id,
        range_instance_pk,
    )

    try:
        instance = RangeInstance.objects.get(pk=range_instance_pk)
    except RangeInstance.DoesNotExist:
        logger.warning(
            "destroy_range: range not found for user_id=%s, range_instance_pk=%s",
            user.id,
            range_instance_pk,
        )
        raise CMSError(f"Range {range_instance_pk} not found") from None

    if instance.user_id != user.id:
        logger.error(
            "destroy_range: access denied - range_instance_pk=%s owned by user_id=%s, requested by user_id=%s",
            range_instance_pk,
            instance.user_id,
            user.id,
        )
        raise CMSError(f"Range {range_instance_pk} not found")

    try:
        request_id = instance.request.request_id if instance.request else None
        if request_id is None:
            logger.error(
                "destroy_range: no request_id for range_instance_pk=%s, cannot destroy",
                range_instance_pk,
            )
            raise CMSError(f"Range {range_instance_pk} has no associated request")

        _transition_then_dispatch(
            instance=instance,
            request_id=request_id,
            user=user,
            audit_entity_id=range_instance_pk,
            transition=_DESTROY_TRANSITION,
        )

        logger.debug(
            "destroy_range completed for range_instance_pk=%s request_id=%s user_id=%s",
            range_instance_pk,
            request_id,
            user.id,
        )

    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception(
            "Error in destroy_range for user_id=%s, range_instance_pk=%s",
            user.id,
            range_instance_pk,
        )
        raise


def cancel_range(user: User, range_id: int) -> None:
    """Cancel provisioning range.

    Verifies ownership via get_range, marks the CMS row destroying, and delegates
    engine cancellation.
    """
    _validate_caller_user(user, "cancel_range")

    if range_id is None:
        logger.error(
            "cancel_range called with None range_id for user_id=%s",
            user.id,
        )
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error(
            "cancel_range called with invalid range_id type: %s",
            type(range_id).__name__,
        )
        msg = f"range_id must be an int, got {type(range_id).__name__}"
        raise TypeError(msg)

    if range_id < 0:
        logger.error(
            "cancel_range called with negative range_id=%s for user_id=%s",
            range_id,
            user.id,
        )
        raise ValueError("range_id must be non-negative")

    logger.debug(
        "cancel_range called for user_id=%s, range_id=%s",
        user.id,
        range_id,
    )

    instance = None

    try:
        instance = _get_range_call(user, range_id)
        if instance is None:
            logger.warning(
                "cancel_range: range not found for user_id=%s, range_id=%s",
                user.id,
                range_id,
            )
            raise CMSError(_RANGE_NOT_FOUND_MSG)
    except (TypeError, ValueError, CMSError):
        logger.error(
            "cancel_range: user and range mismatch for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise

    try:
        request_id = instance.request.request_id if instance.request else None
        if request_id is None:
            logger.error(
                "cancel_range: no request_id for range_id=%s, cannot cancel",
                range_id,
            )
            raise CMSError(f"Range {range_id} has no associated request")

        _transition_then_dispatch(
            instance=instance,
            request_id=request_id,
            user=user,
            audit_entity_id=range_id,
            transition=_CANCEL_TRANSITION,
        )
    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception(
            "Error in cancel_range for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise


def destroy_range_by_request_id(user: User, request_id: str) -> None:
    """Tear down range by request_id.

    Fetches RangeInstance by request_id, verifies ownership, updates CMS status
    to DESTROYING, then delegates to engine.services.destroy_range.

    Args:
        user: User requesting destruction
        request_id: UUID string of the request

    Returns:
        None

    Raises:
        TypeError: If user is None or invalid type
        CMSError: If range not found or not owned by user
    """
    if user is None:
        logger.error("destroy_range_by_request_id called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "destroy_range_by_request_id called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if not request_id:
        logger.error("destroy_range_by_request_id called with empty request_id")
        raise CMSError("request_id is required")

    logger.debug(
        "destroy_range_by_request_id called: user_id=%s request_id=%s",
        user.id,
        request_id,
    )

    instance = RangeInstance.objects.filter(
        request__request_id=request_id,
        user_id=user.id,
    ).first()

    if not instance:
        logger.warning(
            "destroy_range_by_request_id: not found: request_id=%s user_id=%s",
            request_id,
            user.id,
        )
        raise CMSError(_RANGE_NOT_FOUND_MSG)

    if instance.request is None:
        raise CMSError("Range has no associated request")

    try:
        _transition_then_dispatch(
            instance=instance,
            request_id=instance.request.request_id,
            user=user,
            audit_entity_id=instance.range_id or 0,
            transition=_DESTROY_TRANSITION,
        )

        logger.debug(
            "destroy_range_by_request_id completed: request_id=%s user_id=%s",
            request_id,
            user.id,
        )
    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception(
            "Error in destroy_range_by_request_id: user_id=%s request_id=%s",
            user.id,
            request_id,
        )
        raise


def cancel_range_by_request_id(user: User, request_id: str) -> None:
    """Cancel provisioning range by request_id.

    Fetches RangeInstance by request_id, verifies ownership, updates status,
    then delegates to engine.orchestration.cancel().

    Args:
        user: User requesting cancellation
        request_id: UUID string of the request

    Returns:
        None

    Raises:
        TypeError: If user is None or invalid type
        CMSError: If range not found or not owned by user
    """
    if user is None:
        logger.error("cancel_range_by_request_id called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "cancel_range_by_request_id called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if not request_id:
        logger.error("cancel_range_by_request_id called with empty request_id")
        raise CMSError("request_id is required")

    logger.debug(
        "cancel_range_by_request_id called: user_id=%s request_id=%s",
        user.id,
        request_id,
    )

    instance = RangeInstance.objects.filter(
        request__request_id=request_id,
        user_id=user.id,
    ).first()

    if not instance:
        logger.warning(
            "cancel_range_by_request_id: not found: request_id=%s user_id=%s",
            request_id,
            user.id,
        )
        raise CMSError(_RANGE_NOT_FOUND_MSG)

    if instance.request is None:
        raise CMSError("Range has no associated request")

    try:
        _transition_then_dispatch(
            instance=instance,
            request_id=instance.request.request_id,
            user=user,
            audit_entity_id=instance.id,
            transition=_CANCEL_TRANSITION,
        )

        logger.debug(
            "cancel_range_by_request_id completed: request_id=%s user_id=%s",
            request_id,
            user.id,
        )
    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception(
            "Error in cancel_range_by_request_id: user_id=%s request_id=%s",
            user.id,
            request_id,
        )
        raise
