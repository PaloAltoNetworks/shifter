"""Range resume entrypoints (by range_id and by request_id)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cms.exceptions import CMSError
from cms.models import RangeInstance
from risk_register.models import AuditLog
from shared.constants import USER_CANNOT_BE_NONE
from shared.enums import ResourceStatus

from ._common import _validate_caller_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def _engine_resume_range_call(request_id: Any) -> Any:
    """Late-bound call so test patches of cms.services.engine_resume_range apply."""
    from cms import services as _cs

    return _cs.engine_resume_range(request_id)


def _audit_log_call(**kwargs: Any) -> None:
    """Late-bound call to ``cms.services.audit_log`` so test patches apply."""
    from cms import services as _cs

    _cs.audit_log(**kwargs)


def resume_range(user: User, range_id: int) -> None:
    """Resume a paused range.

    Fetches RangeInstance, verifies ownership, updates CMS status to RESUMING,
    then delegates to engine.services.resume_range.

    Args:
        user: User requesting resume
        range_id: ID of the range to resume

    Returns:
        None

    Raises:
        TypeError: If user is None, invalid type, or range_id is invalid type
        ValueError: If user has no ID (unsaved) or range_id is invalid
        CMSError: If range not found, not owned by user, or not in resumable state
    """
    _validate_caller_user(user, "resume_range")

    if range_id is None:
        logger.error(
            "resume_range called with None range_id for user_id=%s",
            user.id,
        )
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error(
            "resume_range called with invalid range_id type: %s",
            type(range_id).__name__,
        )
        msg = f"range_id must be an int, got {type(range_id).__name__}"
        raise TypeError(msg)

    if range_id < 0:
        logger.error(
            "resume_range called with negative range_id=%s for user_id=%s",
            range_id,
            user.id,
        )
        raise ValueError("range_id must be non-negative")

    logger.debug(
        "resume_range called for user_id=%s, range_id=%s",
        user.id,
        range_id,
    )

    try:
        instance = RangeInstance.objects.get(range_id=range_id)
    except RangeInstance.DoesNotExist:
        logger.warning(
            "resume_range: range not found for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise CMSError(f"Range {range_id} not found") from None

    if instance.user_id != user.id:
        logger.error(
            "resume_range: access denied - range_id=%s owned by user_id=%s, requested by user_id=%s",
            range_id,
            instance.user_id,
            user.id,
        )
        raise CMSError(f"Range {range_id} not found")

    try:
        request_id = instance.request.request_id if instance.request else None
        if request_id is None:
            logger.error(
                "resume_range: no request_id for range_id=%s, cannot resume",
                range_id,
            )
            raise CMSError("Range has no associated request")

        instance.status = ResourceStatus.RESUMING.value
        instance.save(update_fields=["status"])

        if not _engine_resume_range_call(request_id):
            instance.status = ResourceStatus.PAUSED.value
            instance.save(update_fields=["status"])
            logger.warning(
                "resume_range: engine returned False for range_id=%s",
                range_id,
            )
            raise CMSError("Range cannot be resumed in current state")

        _audit_log_call(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=range_id,
            action=AuditLog.Action.RESUME,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state={"status": ResourceStatus.RESUMING.value},
            request_id=str(request_id),
        )

        logger.info(
            "resume_range completed: range_id=%s user_id=%s",
            range_id,
            user.id,
        )
    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception(
            "Error in resume_range: user_id=%s range_id=%s",
            user.id,
            range_id,
        )
        raise


def resume_range_by_request_id(user: User, request_id: str) -> None:
    """Resume a paused range by request_id.

    Fetches RangeInstance by request_id, verifies ownership, then delegates
    to engine.services.resume_range.

    Args:
        user: User requesting resume
        request_id: UUID string of the request

    Returns:
        None

    Raises:
        TypeError: If user is None or invalid type
        CMSError: If range not found, not owned by user, or not in resumable state
    """
    if user is None:
        logger.error("resume_range_by_request_id called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "resume_range_by_request_id called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if not request_id:
        logger.error("resume_range_by_request_id called with empty request_id")
        raise CMSError("request_id is required")

    logger.debug(
        "resume_range_by_request_id called: user_id=%s request_id=%s",
        user.id,
        request_id,
    )

    instance = RangeInstance.objects.filter(
        request__request_id=request_id,
        user_id=user.id,
    ).first()

    if not instance:
        logger.warning(
            "resume_range_by_request_id: not found: request_id=%s user_id=%s",
            request_id,
            user.id,
        )
        raise CMSError("Range not found")

    if instance.request is None:
        raise CMSError("Range has no associated request")

    try:
        instance.status = ResourceStatus.RESUMING.value
        instance.save(update_fields=["status"])

        if not _engine_resume_range_call(instance.request.request_id):
            instance.status = ResourceStatus.PAUSED.value
            instance.save(update_fields=["status"])
            logger.warning(
                "resume_range_by_request_id: engine returned False for request_id=%s",
                request_id,
            )
            raise CMSError("Range cannot be resumed in current state")

        _audit_log_call(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=instance.range_id or 0,
            action=AuditLog.Action.RESUME,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state={"status": ResourceStatus.RESUMING.value},
            request_id=str(instance.request.request_id),
        )

        logger.info(
            "resume_range_by_request_id completed: request_id=%s user_id=%s",
            request_id,
            user.id,
        )
    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception(
            "Error in resume_range_by_request_id: user_id=%s request_id=%s",
            user.id,
            request_id,
        )
        raise
