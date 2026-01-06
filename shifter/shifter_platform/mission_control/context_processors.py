"""Context processors for mission_control app."""

import logging

from cms.services import get_active_range
from mission_control.utils import build_connection_urls
from shared.schemas import RangeContext

logger = logging.getLogger(__name__)


def active_range(request):
    """
    Add active range information to template context.

    Uses CMS service to get the user's active range as a RangeContext.

    Provides:
        - has_active_range: Boolean indicating if user has a ready range
        - active_range: The user's active RangeContext (or None)
    """
    if not request.user.is_authenticated:
        return {
            "has_active_range": False,
            "active_range": None,
            "connection_urls": [],
        }

    user_id = request.user.id

    try:
        # Get the user's active range from CMS (returns RangeContext or None)
        range_context = get_active_range(request.user)
        if range_context is not None and not isinstance(range_context, RangeContext):
            logger.error(
                "active_range context processor: get_active_range returned invalid type %s for user_id=%s",
                type(range_context).__name__,
                user_id,
            )
            return {
                "has_active_range": False,
                "active_range": None,
                "connection_urls": [],
            }

        if range_context is not None:
            is_ready = range_context.is_ready
            logger.info(
                "active_range context processor: found range for user_id=%s, status=%s, is_ready=%s",
                user_id,
                range_context.status,
                is_ready,
            )
            has_ready_range = is_ready
            connection_urls = build_connection_urls(range_context.instances)
        else:
            logger.info(
                "active_range context processor: no active range for user_id=%s",
                user_id,
            )
            has_ready_range = False
            connection_urls = []

        return {
            "has_active_range": has_ready_range,
            "active_range": range_context,
            "connection_urls": connection_urls,
        }

    except Exception:
        logger.exception(
            "Error in active_range context processor for user_id=%s",
            user_id,
        )
        return {
            "has_active_range": False,
            "active_range": None,
            "connection_urls": [],
        }
