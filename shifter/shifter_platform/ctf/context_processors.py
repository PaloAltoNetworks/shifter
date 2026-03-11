"""Context processors for the CTF app.

Provides CTF-specific context variables to all templates.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def ctf_navigation(request: HttpRequest) -> dict[str, Any]:
    """Add CTF navigation context to all templates.

    Provides:
    - is_ctf_user: Whether the user is a CTF organizer or participant.
    - is_ctf_organizer: Whether the user is a CTF organizer.
    - is_ctf_participant: Whether the user is a CTF participant.
    - active_ctf_event: The user's active CTF event (for participants).
    """
    if not request.user.is_authenticated:
        return {
            "is_ctf_user": False,
            "is_ctf_organizer": False,
            "is_ctf_participant": False,
            "active_ctf_event": None,
        }

    try:
        from management.services import get_user_profile

        profile = get_user_profile(request.user)

        is_organizer = profile.is_ctf_organizer
        is_participant = profile.is_ctf_participant

        return {
            "is_ctf_user": is_organizer or is_participant,
            "is_ctf_organizer": is_organizer,
            "is_ctf_participant": is_participant,
            "active_ctf_event": profile.active_ctf_event if is_participant else None,
        }
    except Exception:
        logger.exception(
            "Error in ctf_navigation context processor for user %s",
            request.user.email,
        )
        return {
            "is_ctf_user": False,
            "is_ctf_organizer": False,
            "is_ctf_participant": False,
            "active_ctf_event": None,
        }
