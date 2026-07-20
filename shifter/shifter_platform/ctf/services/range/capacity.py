"""Event capacity declaration to the provisioning engine (CTF-908, #621).

Built from authoritative event state (roster, spare pool target, range
config) plus organizer-authored hints, and declared through the CMS/engine
bridge BEFORE spinup begins — never inferred from spinup traffic. The
declaration is best-effort: provisioning proceeds even if recording fails.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ctf.models import CTFEvent
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


def build_event_capacity_signal(event: CTFEvent) -> dict[str, Any]:
    """Assemble the declaration payload for one event.

    ``expected_concurrent_ranges`` is the roster plus the spare-pool target —
    the peak number of ranges in flight if every participant plays and every
    spare is provisioned. ``resource_hints`` carries the per-range shape
    (agent mix, NGFW) and the organizer-authored shared-resource hints
    (LLM provider class, per-participant rate expectations, ...).
    """
    cohort_size = event.participants.count()
    range_config = event.range_config or {}
    resource_hints: dict[str, Any] = {
        "scenario_id": event.scenario_id,
        "agents_by_os": range_config.get("agents_by_os", {}),
        "ngfw_enabled": bool(range_config.get("ngfw_enabled", False)),
        "team_mode": event.team_mode,
    }
    organizer_hints = event.capacity_hints or {}
    if organizer_hints:
        resource_hints["organizer"] = organizer_hints
    return {
        "event_ref": event.pk,
        "event_name": event.name,
        "expected_concurrent_ranges": cohort_size + (event.spare_range_count or 0),
        "cohort_size": cohort_size,
        "window_start": event.get_spinup_time(),
        "window_end": event.get_cleanup_time(),
        "resource_hints": resource_hints,
    }


def declare_event_capacity(event_id: UUID, *, source: str) -> bool:
    """Declare the event's capacity to the engine; never raises.

    Returns True when the declaration was recorded. Failures are logged and
    swallowed: the declaration informs capacity planning (PLAT-201) but must
    never block or fail range provisioning itself.
    """
    from ctf.bridges import cms_declare_event_capacity

    try:
        event = CTFEvent.objects.get(pk=event_id)
        cms_declare_event_capacity(**build_event_capacity_signal(event))
    except Exception:
        logger.exception(
            "Failed to declare capacity for event %s (%s)",
            safe_log_value(event_id),
            safe_log_value(source),
        )
        return False
    logger.info("Declared capacity for event %s (%s)", safe_log_value(event_id), safe_log_value(source))
    return True
