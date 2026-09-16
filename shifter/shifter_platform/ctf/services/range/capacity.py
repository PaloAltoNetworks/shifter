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
from shared.model_access.admission import EventModelDemand

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
    # PLAT-201: the per-range image shape, resolved through CMS (which owns
    # scenario hydration) so the engine never re-parses scenario content or
    # builds a parallel AMI mapping. Server-derived, never organizer-supplied.
    resource_hints["images"] = _project_images(event.scenario_id)
    # PLAT-202: typed organizer model demand, validated into the CTF-908
    # declaration rather than a parallel event contract. Best-effort here (a bad
    # hint never blocks provisioning); required-model admission is enforced
    # separately and fails closed.
    model_demand = [demand.model_dump(mode="json") for demand in parse_event_model_demand(event)]
    if model_demand:
        resource_hints["model_demand"] = model_demand
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


def parse_event_model_demand(event: CTFEvent) -> tuple[EventModelDemand, ...]:
    """Validate the organizer's typed model demand into ``EventModelDemand`` DTOs.

    Never raises: a malformed entry is dropped and logged rather than trusted,
    consistent with the best-effort declaration path. Returns one DTO per valid
    workload-role demand entry.
    """
    from pydantic import ValidationError

    raw = event.model_demand or []
    if not isinstance(raw, list):
        return ()
    demands = []
    for entry in raw:
        try:
            demands.append(EventModelDemand.model_validate(entry))
        except ValidationError:
            logger.warning("capacity: dropping malformed model demand entry")
    return tuple(demands)


def _project_images(scenario_id: str) -> dict[str, Any]:
    """Resolve the scenario's per-range image shape; never raises.

    An unresolvable scenario yields an explicitly unresolved projection rather
    than an empty-looking one, so a downstream pre-bake number is never derived
    from a scenario nobody could read.
    """
    try:
        from ctf.bridges import cms_project_scenario_images

        return cms_project_scenario_images(scenario_id)
    except Exception:
        logger.exception("Failed to project scenario images for capacity declaration")
        return {"resolved": False, "per_range": [], "shared": []}


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


def assess_declared_capacity(event_id: UUID, *, source: str) -> dict[str, Any] | None:
    """Assess the event's declared capacity against observed headroom; never raises.

    Returns a bounded, safe summary for the caller's result payload -- outcome,
    whether it blocks, and the per-metric reason codes. Raw quota limits, usage
    figures, and account identifiers never appear here: those stay in the
    operator-only assessment record and metric stream.

    ``None`` means "no opinion" (the layer is disabled, no declaration exists,
    or the assessment itself failed) and callers proceed exactly as before.
    """
    from ctf.bridges import cms_assess_event_capacity

    try:
        result = cms_assess_event_capacity(event_id)
    except Exception:
        logger.exception(
            "Failed to assess capacity for event %s (%s)",
            safe_log_value(event_id),
            safe_log_value(source),
        )
        return None
    if result is None:
        return None

    summary = {
        "outcome": result.outcome.value,
        "blocking": result.blocking,
        "partition": result.partition.name,
        "reason_codes": sorted({verdict.reason_code.value for verdict in result.verdicts}),
    }
    logger.info(
        "Capacity assessment for event %s (%s): %s",
        safe_log_value(event_id),
        safe_log_value(source),
        safe_log_value(summary["outcome"]),
    )
    return summary


def admit_range(event_id: UUID, draw_key: UUID) -> dict[str, Any] | None:
    """Draw one range's share of the event budget; never raises.

    Returns a bounded summary, or ``None`` when the layer has no opinion (no
    budget on record, or the draw itself failed). Callers treat ``None`` as
    "proceed" so a capacity bookkeeping problem can never be the reason a range
    fails to provision.
    """
    from ctf.bridges import cms_admit_range_capacity

    try:
        result = cms_admit_range_capacity(event_id, draw_key)
    except Exception:
        logger.exception("Failed to admit range capacity for event %s", safe_log_value(event_id))
        return None
    if result is None:
        return None
    return {
        "outcome": result.outcome.value,
        "blocking": result.blocking,
        "reason_codes": sorted({verdict.reason_code.value for verdict in result.verdicts}),
    }


def release_range(draw_key: UUID) -> None:
    """Return a range's capacity draw on teardown; never raises."""
    from ctf.bridges import cms_release_range_capacity

    try:
        cms_release_range_capacity(draw_key)
    except Exception:
        logger.exception("Failed to release range capacity draw")
