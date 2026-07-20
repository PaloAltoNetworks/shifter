"""Per-event range-instance visibility for CTF participants (#483).

Registered as the platform's instance-visibility policy at app startup.
Participants see the instance OS types their event allows
(``CTFEvent.visible_os_types``, defaulting to attacker boxes only); an empty
list means the event exposes every instance. Non-participant users are
never filtered. Any internal failure falls back to the legacy kali-only
filter for participant accounts — restrictive by default, never wide open.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

logger = logging.getLogger(__name__)

_LEGACY_DEFAULT = ["kali"]


def _visible_os_types_for(user: AbstractBaseUser | AnonymousUser) -> list[str] | None:
    """Return the OS-type allowlist for `user`, or None for no filtering."""
    from shared.auth import is_ctf_participant_only

    if not is_ctf_participant_only(user):
        return None
    from ctf.services.participant import get_viewing_participant_by_user

    participant = get_viewing_participant_by_user(user)  # type: ignore[arg-type]
    if participant is None:
        return list(_LEGACY_DEFAULT)
    configured = participant.event.visible_os_types
    return [str(os_type).lower() for os_type in configured] if configured else None


def ctf_instance_visibility_policy(user: AbstractBaseUser | AnonymousUser, instances: list[Any]) -> list[Any]:
    """Filter instances to the participant's event-configured OS types."""
    try:
        allowed = _visible_os_types_for(user)
    except Exception:
        logger.exception("CTF visibility resolution failed; applying the restrictive default")
        allowed = list(_LEGACY_DEFAULT)
    if allowed is None:
        return instances
    return [inst for inst in instances if str(getattr(inst, "os_type", "")).lower() in allowed]


def register_ctf_visibility_policy() -> None:
    """Register the policy with the shared seam (idempotent)."""
    from shared.range_visibility import register_visibility_policy

    register_visibility_policy(ctf_instance_visibility_policy)
