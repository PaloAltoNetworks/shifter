"""Retired legacy write entry points; retained imports cannot bypass the ledger."""

from __future__ import annotations

from typing import Any, NoReturn

from ctf.exceptions import CTFCommunicationError


def retired_write(*args: Any, **kwargs: Any) -> NoReturn:
    """Fail closed for stale callers, including scheduler dispatch."""
    raise CTFCommunicationError("Legacy notification writes are retired", code="CTF_COMMUNICATION_RETIRED")


send_announcement = retired_write
_deliver_announcement = retired_write
schedule_notification = retired_write
deliver_scheduled_notification = retired_write
cancel_scheduled_notification = retired_write
