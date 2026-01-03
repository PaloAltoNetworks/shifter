"""Context processors for mission_control app."""

import logging

from cms.services import get_active_range
from shared.enums import RangeStatus

logger = logging.getLogger(__name__)


def active_range(request):
    """
    Add active range information to template context.

    Uses CMS service to get the user's active range as a RangeRef.

    Provides:
        - has_active_range: Boolean indicating if user has a ready range
        - active_range: The user's active RangeRef (or None)
    """
    if not request.user.is_authenticated:
        return {
            "has_active_range": False,
            "active_range": None,
        }

    user_id = request.user.id

    try:
        # Get the user's active range from CMS (returns RangeRef or None)
        range_ref = get_active_range(request.user)

        if range_ref is not None:
            is_ready = range_ref.status == RangeStatus.READY
            logger.info(
                "active_range context processor: found range for user_id=%s, "
                "status=%s, is_ready=%s",
                user_id,
                range_ref.status,
                is_ready,
            )
            has_ready_range = is_ready
        else:
            logger.info(
                "active_range context processor: no active range for user_id=%s",
                user_id,
            )
            has_ready_range = False

        return {
            "has_active_range": has_ready_range,
            "active_range": range_ref,
        }

    except Exception:
        logger.exception(
            "Error in active_range context processor for user_id=%s",
            user_id,
        )
        return {
            "has_active_range": False,
            "active_range": None,
        }
