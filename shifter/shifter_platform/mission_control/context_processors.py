"""Context processors for mission_control app."""

import logging

from cms.services import get_active_range, get_scenario
from mission_control.utils import build_connection_urls
from shared.schemas import InstanceContext, RangeContext

logger = logging.getLogger(__name__)


def _get_ngfw_instance_context(user) -> tuple[InstanceContext | None, str | None]:
    """Get NGFW InstanceContext for user's active range.

    Returns a tuple of (InstanceContext, management_ip) if the range
    has a ready NGFW attached, (None, None) otherwise.

    Args:
        user: Authenticated Django user

    Returns:
        Tuple of (InstanceContext, management_ip) or (None, None)
    """
    try:
        from engine.services import get_range_ngfw_context

        ngfw_info = get_range_ngfw_context(user)
        if ngfw_info:
            ctx = InstanceContext(
                uuid=ngfw_info["uuid"],
                name=ngfw_info["name"],
                role=ngfw_info["role"],
                os_type=ngfw_info["os_type"],
            )
            return ctx, ngfw_info.get("management_ip")
    except Exception:
        logger.exception(
            "Error getting NGFW context for user_id=%s",
            user.id,
        )
    return None, None


def active_range(request):
    """
    Add active range information to template context.

    Uses CMS service to get the user's active range as a RangeContext.
    Augments with NGFW instance if the range has one attached.

    Provides:
        - has_active_range: Boolean indicating if user has a ready range
        - active_range: The user's active RangeContext (or None)
        - connection_urls: WebSocket terminal URLs for each instance
        - scenario_name: Display name for the scenario
        - ngfw_management_ip: NGFW management IP if available (for GUI access)
    """
    if not request.user.is_authenticated:
        return {
            "has_active_range": False,
            "active_range": None,
            "connection_urls": [],
            "scenario_name": None,
            "ngfw_management_ip": None,
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
                "scenario_name": None,
                "ngfw_management_ip": None,
            }

        ngfw_management_ip = None

        if range_context is not None:
            is_ready = range_context.is_ready
            logger.info(
                "active_range context processor: found range for user_id=%s, status=%s, is_ready=%s",
                user_id,
                range_context.status,
                is_ready,
            )
            has_ready_range = is_ready

            # Add NGFW to terminal context if range has one and both are ready
            if is_ready:
                ngfw_ctx, ngfw_management_ip = _get_ngfw_instance_context(
                    request.user
                )
                if ngfw_ctx:
                    range_context.instances.append(ngfw_ctx)
                    logger.debug(
                        "active_range context processor: added NGFW tab for user_id=%s uuid=%s",
                        user_id,
                        ngfw_ctx.uuid,
                    )

            connection_urls = build_connection_urls(range_context.instances)

            # Look up scenario name for display
            scenario_name = None
            if range_context.scenario_id:
                try:
                    scenario = get_scenario(range_context.scenario_id)
                    scenario_name = scenario.get("name", range_context.scenario_id)
                except Exception:
                    logger.warning(
                        "Could not look up scenario name for scenario_id=%s",
                        range_context.scenario_id,
                    )
                    scenario_name = range_context.scenario_id
        else:
            logger.info(
                "active_range context processor: no active range for user_id=%s",
                user_id,
            )
            has_ready_range = False
            connection_urls = []
            scenario_name = None

        return {
            "has_active_range": has_ready_range,
            "active_range": range_context,
            "connection_urls": connection_urls,
            "scenario_name": scenario_name,
            "ngfw_management_ip": ngfw_management_ip,
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
            "scenario_name": None,
            "ngfw_management_ip": None,
        }
