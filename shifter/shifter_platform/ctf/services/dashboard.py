"""Bounded CTF read summaries for cross-domain composition (#1523).

The composition-root dashboard (``config.api_dashboard``) needs the active CTF
event for a user. It must consume a public CTF service facade rather than the
CTF-owned outbound ``ctf.bridges`` module (ADR-001). This returns bounded
primitives only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def active_event_summary(user: User) -> dict[str, object]:
    """Return a bounded active-CTF-event summary for ``user``.

    ``{"present": bool, "name": str | None}``. Reflects the user's active event
    only; returns no ORM object.
    """
    from ctf.bridges import get_user_role

    event = getattr(get_user_role(user), "active_ctf_event", None)
    if event is None:
        return {"present": False, "name": None}
    name = getattr(event, "name", None)
    return {"present": True, "name": str(name) if name is not None else None}
