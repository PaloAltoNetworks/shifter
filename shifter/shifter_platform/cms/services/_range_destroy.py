"""Range destroy/cancel entrypoints (by range_id and by request_id)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

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


def _engine_destroy_range_by_request_call(request_id: Any) -> Any:  # NOSONAR (late-bind proxy)
    """Late-bound call so test patches of cms.services.engine_destroy_range_by_request apply."""
    from cms import services as _cs

    return _cs.engine_destroy_range_by_request(request_id)


def _engine_cancel_range_by_request_call(request_id: Any) -> Any:  # NOSONAR (late-bind proxy)
    """Late-bound call so test patches of cms.services.engine_cancel_range_by_request apply."""
    from cms import services as _cs

    return _cs.engine_cancel_range_by_request(request_id)


def _audit_log_call(**kwargs: Any) -> None:  # NOSONAR (late-bind proxy)
    """Late-bound call to ``cms.services.audit_log`` so test patches apply."""
    from cms import services as _cs

    _cs.audit_log(**kwargs)


def _get_range_call(user: User, range_id: int) -> RangeInstance:
    """Look up range through the package so test patches apply."""
    from cms import services as _cs

    return _cs.get_range(user, range_id)


def destroy_range(user: User, range_id: int) -> None:
    """Tear down range.

    Fetches RangeInstance, verifies ownership, updates CMS status to DESTROYING,
    then delegates to engine.services.destroy_range with RangeContext.

    Args:
        user: User requesting destruction
        range_id: ID of the range to destroy

    Returns:
        None

    Raises:
        TypeError: If user is None, invalid type, or range_id is invalid type
        ValueError: If user has no ID (unsaved) or range_id is invalid
        CMSError: If range not found or not owned by user
        EngineError: If engine fails to destroy range
    """
    _validate_caller_user(user, "destroy_range")

    if range_id is None:
        logger.error(
            "destroy_range called with None range_id for user_id=%s",
            user.id,
        )
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error(
            "destroy_range called with invalid range_id type: %s",
            type(range_id).__name__,
        )
        msg = f"range_id must be an int, got {type(range_id).__name__}"
        raise TypeError(msg)

    if range_id < 0:
        logger.error(
            "destroy_range called with negative range_id=%s for user_id=%s",
            range_id,
            user.id,
        )
        raise ValueError("range_id must be non-negative")

    logger.debug(
        "destroy_range called for user_id=%s, range_id=%s",
        user.id,
        range_id,
    )

    try:
        instance = RangeInstance.objects.get(range_id=range_id)
    except RangeInstance.DoesNotExist:
        logger.warning(
            "destroy_range: range not found for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise CMSError(f"Range {range_id} not found") from None

    if instance.user_id != user.id:
        logger.error(
            "destroy_range: access denied - range_id=%s owned by user_id=%s, requested by user_id=%s",
            range_id,
            instance.user_id,
            user.id,
        )
        raise CMSError(f"Range {range_id} not found")

    try:
        instance.status = ResourceStatus.DESTROYING.value
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["status", "deleted_at"])

        request_id = instance.request.request_id if instance.request else None
        if request_id is None:
            logger.error(
                "destroy_range: no request_id for range_id=%s, cannot destroy",
                range_id,
            )
            raise CMSError(f"Range {range_id} has no associated request")

        _engine_destroy_range_by_request_call(request_id)

        _audit_log_call(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=range_id,
            action=AuditLog.Action.DEPROVISION,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            previous_state={
                "status": ResourceStatus.DESTROYING.value,
                "scenario": instance.scenario_id,
            },
            request_id=str(request_id),
        )

        logger.debug(
            "destroy_range completed for range_id=%s request_id=%s user_id=%s",
            range_id,
            request_id,
            user.id,
        )

    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception(
            "Error in destroy_range for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise


def cancel_range(user: User, range_id: int) -> None:
    """Cancel provisioning range.

    Verifies ownership via get_range, then delegates to
    engine.orchestration.cancel().

    Args:
        user: User requesting cancellation
        range_id: ID of the range to cancel

    Returns:
        None

    Raises:
        TypeError: If user is None, invalid type, or range_id is invalid type
        ValueError: If user has no ID (unsaved) or range_id is invalid
        CMSError: If range not found or not owned by user
        OrchestrationError: If range not in cancellable status
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
        instance.status = ResourceStatus.DESTROYED.value
        instance.save(update_fields=["status"])
        if instance.status != ResourceStatus.DESTROYED.value:
            raise CMSError("Range status not updated to DESTROYED")

        request_id = instance.request.request_id if instance.request else None
        if request_id is None:
            logger.error(
                "cancel_range: no request_id for range_id=%s, cannot cancel",
                range_id,
            )
            raise CMSError(f"Range {range_id} has no associated request")

        _engine_cancel_range_by_request_call(request_id)

        _audit_log_call(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=range_id,
            action=AuditLog.Action.CANCEL,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            previous_state={
                "status": ResourceStatus.DESTROYED.value,
                "scenario": instance.scenario_id,
            },
            request_id=str(request_id),
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
        instance.status = ResourceStatus.DESTROYING.value
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["status", "deleted_at"])

        _engine_destroy_range_by_request_call(instance.request.request_id)

        _audit_log_call(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=instance.range_id or 0,
            action=AuditLog.Action.DEPROVISION,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            previous_state={
                "status": ResourceStatus.DESTROYING.value,
                "scenario": instance.scenario_id,
            },
            request_id=str(request_id),
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
        instance.status = ResourceStatus.DESTROYED.value
        instance.save(update_fields=["status"])

        _engine_cancel_range_by_request_call(instance.request.request_id)

        _audit_log_call(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=instance.id,
            action=AuditLog.Action.CANCEL,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            previous_state={
                "status": ResourceStatus.DESTROYED.value,
                "scenario": instance.scenario_id,
            },
            request_id=str(instance.request.request_id),
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
