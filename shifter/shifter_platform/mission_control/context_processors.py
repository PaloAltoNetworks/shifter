"""Context processors for mission_control app."""

import logging

from cms.services import get_active_range, get_scenario
from mission_control.utils import build_connection_urls
from shared.auth import is_ctf_participant_only
from shared.schemas import RangeContext

logger = logging.getLogger(__name__)


def _terminal_instances_payload(instances):
    """Project InstanceContext rows into the json_script-safe dict shape consumed by terminal.js."""
    return [
        {
            "uuid": inst.uuid,
            "role": inst.role,
            "osType": inst.os_type,
            "name": inst.name or inst.role,
            "privateIp": inst.private_ip,
        }
        for inst in instances
    ]


def active_range(request):
    """
    Add active range information to template context.

    Uses CMS service to get the user's active range as a RangeContext.

    Provides:
        - has_active_range: Boolean indicating if user has a ready range
        - active_range: The user's active RangeContext (or None)
        - terminal_instances: json_script-safe per-instance payload for terminal.js
    """
    if not request.user.is_authenticated:
        return {
            "has_active_range": False,
            "active_range": None,
            "connection_urls": [],
            "scenario_name": None,
            "terminal_instances": [],
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
                "terminal_instances": [],
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

            # CTF participants only see Kali (attacker) instances
            if is_ctf_participant_only(request.user):
                range_context.instances = [inst for inst in range_context.instances if inst.os_type == "kali"]

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

        terminal_instances = _terminal_instances_payload(range_context.instances) if range_context is not None else []

        return {
            "has_active_range": has_ready_range,
            "active_range": range_context,
            "connection_urls": connection_urls,
            "scenario_name": scenario_name,
            "terminal_instances": terminal_instances,
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
            "terminal_instances": [],
        }
