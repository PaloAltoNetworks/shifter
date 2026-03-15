"""Context processors for the CTF app.

Provides CTF-specific context variables to all templates.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from shared.auth import is_ctf_participant_only as _is_participant_only

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def ctf_navigation(request: HttpRequest) -> dict[str, Any]:
    """Add CTF navigation context to all templates.

    Provides:
    - is_ctf_user: Whether the user is a CTF organizer or participant.
    - is_ctf_organizer: Whether the user is a CTF organizer.
    - is_ctf_participant: Whether the user is a CTF participant.
    - is_ctf_participant_only: Whether the user is ONLY a CTF participant (no other role).
    - active_ctf_event: The user's active CTF event (for participants).
    """
    if not request.user.is_authenticated:
        return {
            "is_ctf_user": False,
            "is_ctf_organizer": False,
            "is_ctf_participant": False,
            "is_ctf_participant_only": False,
            "active_ctf_event": None,
        }

    try:
        from ctf.bridges import get_user_role

        role = get_user_role(request.user)

        result = {
            "is_ctf_user": role.is_ctf_organizer or role.is_ctf_participant,
            "is_ctf_organizer": role.is_ctf_organizer,
            "is_ctf_participant": role.is_ctf_participant,
            "is_ctf_participant_only": _is_participant_only(request.user),
            "active_ctf_event": role.active_ctf_event,
        }

        # Highlight CTF Admin in the MC sidebar when on CTF admin pages
        if role.is_ctf_organizer and request.path.startswith("/ctf/admin/"):
            result["active_nav"] = "ctf_admin"

        return result
    except Exception:
        logger.exception(
            "Error in ctf_navigation context processor for user %s",
            request.user.email,
        )
        return {
            "is_ctf_user": False,
            "is_ctf_organizer": False,
            "is_ctf_participant": False,
            "is_ctf_participant_only": False,
            "active_ctf_event": None,
        }
