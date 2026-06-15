"""Range query entrypoints: list_ranges / get_range / get_active_range / get_range_by_request_id.

The runtime-IP overlay (``_resolve_runtime_ips``) lives in ``_common`` so
it can be shared with destroy/pause/resume helpers if needed, and so it
honors test patches of ``cms.services.engine_get_instance_ips_by_uuid``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cms.exceptions import CMSError
from cms.models import RangeInstance
from shared.constants import USER_CANNOT_BE_NONE

from ._common import (
    _instance_contexts_from_range_spec,
    _resolve_runtime_ips,
    _validate_caller_user,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from shared.schemas.range import RangeContext

logger = logging.getLogger(__name__)


def list_ranges(user: User) -> list[RangeInstance]:
    """Get user's range instances.

    Args:
        user: User whose range instances to retrieve

    Returns:
        List of RangeInstance instances belonging to the user

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved)
    """
    _validate_caller_user(user, "list_ranges")

    logger.debug("list_ranges called for user_id=%s", user.id)

    try:
        result = RangeInstance.objects.filter(user_id=user.id)

        if result is None:
            logger.error(
                "list_ranges: model returned None for user_id=%s",
                user.id,
            )
            raise TypeError("Model returned None instead of iterable")

        ranges = list(result)

        for item in ranges:
            if not isinstance(item, RangeInstance):
                logger.error(
                    "list_ranges: model returned invalid item type %s for user_id=%s",
                    type(item).__name__,
                    user.id,
                )
                msg = f"Model returned list containing {type(item).__name__}, expected RangeInstance"
                raise TypeError(msg)

        logger.debug(
            "list_ranges returning %d ranges for user_id=%s",
            len(ranges),
            user.id,
        )
        return ranges

    except TypeError:
        raise
    except Exception:
        logger.exception("Error in list_ranges for user_id=%s", user.id)
        raise


def get_range(user: User, range_id: int) -> RangeInstance:
    """Get single range instance by range ID.

    Args:
        user: User requesting the range instance
        range_id: ID of the range to retrieve

    Returns:
        RangeInstance if found and owned by user

    Raises:
        TypeError: If user is None, invalid type, or range_id is invalid type
        ValueError: If user has no ID (unsaved) or range_id is invalid
        CMSError: If range not found or not owned by user
    """
    _validate_caller_user(user, "get_range")

    if range_id is None:
        logger.error(
            "get_range called with None range_id for user_id=%s",
            user.id,
        )
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error(
            "get_range called with invalid range_id type: %s",
            type(range_id).__name__,
        )
        msg = f"range_id must be an int, got {type(range_id).__name__}"
        raise TypeError(msg)

    if range_id < 0:
        logger.error(
            "get_range called with negative range_id=%s for user_id=%s",
            range_id,
            user.id,
        )
        raise ValueError("range_id must be non-negative")

    logger.debug(
        "get_range called for user_id=%s, range_id=%s",
        user.id,
        range_id,
    )

    try:
        range_obj = RangeInstance.objects.get(range_id=range_id)

        if range_obj is None:
            logger.error(
                "get_range: model returned None for range_id=%s",
                range_id,
            )
            msg = "Model returned None instead of RangeInstance"
            raise TypeError(msg)

        if not isinstance(range_obj, RangeInstance):
            logger.error(
                "get_range: model returned invalid type %s for range_id=%s",
                type(range_obj).__name__,
                range_id,
            )
            msg = f"Model returned {type(range_obj).__name__}, expected RangeInstance"
            raise TypeError(msg)

        if range_obj.user_id != user.id:
            logger.error(
                "get_range: access denied - range_id=%s owned by user_id=%s, requested by user_id=%s",
                range_id,
                range_obj.user_id,
                user.id,
            )
            raise CMSError(f"Range {range_id} not found")

        logger.debug(
            "get_range returning range_id=%s for user_id=%s",
            range_id,
            user.id,
        )
        return range_obj

    except RangeInstance.DoesNotExist:
        logger.error("get_range: range_id=%s not found", range_id)
        raise CMSError(f"Range {range_id} not found") from None
    except (TypeError, CMSError):
        raise
    except Exception:
        logger.exception(
            "Error in get_range for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise


def get_active_range(user: User) -> RangeContext | None:
    """Get user's active (non-deleted) range as a RangeContext projection.

    Returns the most recently created range that:
    - Belongs to the user
    - Is not soft-deleted (deleted_at is None)

    Note: Terminal statuses (DESTROYED, FAILED) automatically set deleted_at
    via RangeInstance.save(), so filtering by deleted_at is sufficient.

    Used by Mission Control to check if user has an active range.
    Returns a RangeContext rather than raw model to:
    - Provide only the essential identifiers (range_id, user_id, status)
    - Validate data before returning to caller
    - Hide implementation details from presentation layer

    Args:
        user: User whose active range to retrieve

    Returns:
        RangeContext if user has an active range, None otherwise

    Raises:
        TypeError: If user is None or invalid type
        ValidationError: If RangeContext creation fails validation
        Exception: Database errors are logged and propagated
    """
    from shared.enums import ResourceStatus
    from shared.schemas import InstanceContext, RangeContext

    if user is None:
        logger.error("get_active_range called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "get_active_range called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    logger.debug("get_active_range called for user_id=%s", user.id)

    try:
        instance = (
            RangeInstance.objects.filter(user_id=user.id)
            .exclude(status=ResourceStatus.DESTROYING.value)
            .order_by("-created_at")
            .first()
        )
    except TypeError:
        raise
    except Exception:
        logger.exception("Error in get_active_range for user_id=%s", user.id)
        raise

    if instance:
        logger.debug(
            "get_active_range found range_id=%s status=%s for user_id=%s",
            instance.range_id,
            instance.status,
            user.id,
        )

        ip_by_uuid = _resolve_runtime_ips(instance.range_id)
        instance_contexts = _instance_contexts_from_range_spec(instance.range_spec, InstanceContext, ip_by_uuid)

        agent_name = instance.agent.name if instance.agent else None

        request_id = instance.request.request_id if instance.request else None
        if request_id is None:
            logger.warning("get_active_range: range_id=%s has no request FK", instance.range_id)
            from uuid import uuid4

            request_id = uuid4()

        return RangeContext(
            request_id=request_id,
            range_id=instance.range_id,
            scenario_id=instance.scenario_id,
            user_id=instance.user_id,
            status=ResourceStatus(instance.status),
            instances=instance_contexts,
            agent_name=agent_name,
        )
    else:
        logger.debug(
            "get_active_range found no active range for user_id=%s",
            user.id,
        )
        return None


def get_range_by_request_id(user: User, request_id: str) -> RangeContext:
    """Get range by request_id (UUID string).

    Used by WebSocket consumers and views to look up range by request_id.

    Args:
        user: User requesting the range (ownership check)
        request_id: UUID string of the request

    Returns:
        RangeContext: Template-safe projection of the range

    Raises:
        TypeError: If user is None or invalid type
        CMSError: If range not found or not owned by user
    """
    from shared.enums import ResourceStatus
    from shared.schemas import InstanceContext, RangeContext

    _validate_caller_user(user, "get_range_by_request_id")
    if not request_id:
        logger.error("get_range_by_request_id called with empty request_id")
        raise CMSError("request_id is required")

    logger.debug(
        "get_range_by_request_id called: user_id=%s request_id=%s",
        user.id,
        request_id,
    )

    instance = RangeInstance.objects.filter(
        request__request_id=request_id,
        user_id=user.id,
    ).first()

    if not instance:
        logger.warning(
            "get_range_by_request_id: not found or not owned: request_id=%s user_id=%s",
            request_id,
            user.id,
        )
        raise CMSError("Range not found")

    if instance.request is None:
        raise CMSError("Range has no associated request")

    ip_by_uuid = _resolve_runtime_ips(instance.range_id)
    instance_contexts = _instance_contexts_from_range_spec(instance.range_spec, InstanceContext, ip_by_uuid)

    agent_name = instance.agent.name if instance.agent else None

    return RangeContext(
        request_id=instance.request.request_id,
        range_id=instance.range_id,
        scenario_id=instance.scenario_id,
        user_id=instance.user_id,
        status=ResourceStatus(instance.status),
        instances=instance_contexts,
        agent_name=agent_name,
    )
