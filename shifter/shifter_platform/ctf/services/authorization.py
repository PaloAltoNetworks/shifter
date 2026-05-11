"""CTF service-layer authorization helpers.

This module is the shared source of truth for cross-cutting ownership and
membership checks that organizer-content services apply as defense-in-depth
behind the view layer (issue #765). Putting the policy here, rather than in
a private helper inside `ctf.services.challenge`, keeps services that don't
own the policy (hint, attachment, prerequisite, future organizer-scoped
services) from depending on a sibling service's private implementation
detail.

The view layer continues to apply `_check_event_ownership` for fast 403s
on JSON envelopes; the service layer applies these checks again so any
internal caller that bypasses the view layer is still refused.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ctf.exceptions import CTFPermissionError

if TYPE_CHECKING:
    from ctf.models import CTFEvent

logger = logging.getLogger(__name__)


def assert_actor_owns_event(actor_id: int, event: CTFEvent) -> None:
    """Raise `CTFPermissionError` when `actor_id` does not own `event`.

    Defense-in-depth (issue #765): organizer-content service mutators call
    this before mutating, even when the view layer has already checked
    ownership. The error envelope intentionally omits the owner pk to avoid
    leaking internal user identifiers; details name only the requested
    event.
    """
    if event.created_by_id != actor_id:
        logger.warning(
            "CTF service permission denied: actor=%s event=%s",
            actor_id,
            event.id,
        )
        raise CTFPermissionError(
            "Actor does not own this event",
            details={"event_id": str(event.id)},
        )
