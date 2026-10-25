"""Retired organizer email alerts remain explicitly unavailable (#1525).

The participant communication ledger does not represent organizer-only recipients.
Never turn these alerts into participant broadcasts or invent participant rows.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

EVENT_NOT_FOUND_LOG = "Event unavailable"
NO_ORGANIZER_EMAIL_LOG = "Organizer delivery unavailable"
logger = logging.getLogger(__name__)


def _unavailable(event_id: UUID, *args: Any, **kwargs: Any) -> dict[str, str]:
    """Report organizer-only delivery as an unavailable dependency."""

    logger.info("Organizer notification unavailable: event=%s dependency=1525", event_id)
    return {"outcome": "channel_unavailable"}


notify_organizer_provision_failure = _unavailable
notify_organizer_event_start = _unavailable
notify_organizer_event_end = _unavailable
notify_organizer_capacity_outcome = _unavailable
