"""Recording of upstream event-capacity declarations (CTF-908, #621).

The engine is the durable sink for "how big is this event" signals produced
by the CTF layer before spinup. Consumers (capacity-aware provisioning,
PLAT-201) read the newest row per event; this module deliberately implements
no allocation strategy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from engine.models import CapacityDeclaration

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventCapacitySignal:
    """One upstream capacity declaration, validated at the layer boundary."""

    event_ref: UUID
    expected_concurrent_ranges: int
    cohort_size: int
    event_name: str = ""
    source: str = "ctf"
    window_start: datetime | None = None
    window_end: datetime | None = None
    resource_hints: dict[str, Any] = field(default_factory=dict)


def record_capacity_declaration(signal: EventCapacitySignal) -> CapacityDeclaration:
    """Persist one declaration row (append-only history).

    Idempotence is by content: re-declaring identical numbers for the same
    event is skipped so scheduled re-runs do not spam the history; any change
    appends a fresh row.
    """
    from engine.models import CapacityDeclaration

    latest = CapacityDeclaration.objects.filter(event_ref=signal.event_ref).order_by("-declared_at").first()
    if (
        latest is not None
        and latest.expected_concurrent_ranges == signal.expected_concurrent_ranges
        and latest.cohort_size == signal.cohort_size
        and latest.resource_hints == signal.resource_hints
        and latest.window_start == signal.window_start
        and latest.window_end == signal.window_end
    ):
        return latest
    declaration = CapacityDeclaration.objects.create(
        source=signal.source,
        event_ref=signal.event_ref,
        event_name=signal.event_name,
        expected_concurrent_ranges=signal.expected_concurrent_ranges,
        cohort_size=signal.cohort_size,
        window_start=signal.window_start,
        window_end=signal.window_end,
        resource_hints=signal.resource_hints,
    )
    logger.info(
        "Recorded capacity declaration for event %s: ranges=%d cohort=%d",
        signal.event_ref,
        signal.expected_concurrent_ranges,
        signal.cohort_size,
    )
    return declaration


def latest_capacity_declaration(event_ref: UUID) -> CapacityDeclaration | None:
    """Return the current (newest) declaration for one event, if any."""
    from engine.models import CapacityDeclaration

    return CapacityDeclaration.objects.filter(event_ref=event_ref).order_by("-declared_at").first()
