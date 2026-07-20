"""CTF Event service.

Provides business logic for CTF event lifecycle management. The
implementation is split across private submodules (``_crud``,
``_lifecycle``, ``_queries``, ``_tasks``) and re-exported here so callers
continue to use ``from ctf.services.event import X`` / ``from ctf.services
import event``.

The re-exports also rebind names that tests historically patch at
``ctf.services.event.<name>`` (``CTFEvent``, ``transaction``, plus the
``_schedule_event_tasks`` / ``_cancel_event_tasks`` scheduled-task helpers)
so existing ``unittest.mock.patch`` targets still work.

PATCH LOCALITY: ``_crud.py`` and ``_lifecycle.py`` never bind
``_schedule_event_tasks`` / ``_cancel_event_tasks`` into their own module
namespace at import time. Instead they resolve those names through this
package at call time (``from ctf.services import event as _e``, then e.g.
``_e._cancel_event_tasks(...)``), so a ``patch("ctf.services.event.<name>")``
mutates the single attribute those submodules actually look up when they
run. ``CTFEvent`` and ``transaction`` need no such indirection: patching
``ctf.services.event.CTFEvent.objects`` or
``ctf.services.event.transaction.atomic`` mutates an attribute on the
shared class / module object itself, which every submodule sees regardless
of how it imported the reference.
"""

from __future__ import annotations

# --- Names tests patch via ``patch("ctf.services.event.X")`` ---------------
# Rebound here so the patch target resolves at the package level (see the
# PATCH LOCALITY note above).
from django.db import transaction

from ctf.models import CTFEvent
from ctf.services.event.staff import (
    actor_has_event_capability,
    assign_event_staff,
    list_event_staff,
    revoke_event_staff,
)

from ._crud import (
    _EVENT_MUTABLE_FIELDS,
    create_event,
    delete_event,
    event_pk_if_exists,
    force_delete_event,
    get_event,
    list_events_for_organizer,
    update_event,
)
from ._lifecycle import (
    activate_event,
    archive_event,
    cancel_event,
    complete_event,
    end_event,
    open_registration,
    pause_event,
    resume_event,
    schedule_event,
    start_event,
)
from ._queries import get_event_stats, get_organizer_events
from .scheduling import _cancel_event_tasks, _schedule_event_tasks

__all__ = (
    "_EVENT_MUTABLE_FIELDS",
    "CTFEvent",
    "_cancel_event_tasks",
    "_schedule_event_tasks",
    "activate_event",
    "actor_has_event_capability",
    "archive_event",
    "assign_event_staff",
    "cancel_event",
    "complete_event",
    "create_event",
    "delete_event",
    "end_event",
    "event_pk_if_exists",
    "force_delete_event",
    "get_event",
    "get_event_stats",
    "get_organizer_events",
    "list_event_staff",
    "list_events_for_organizer",
    "open_registration",
    "pause_event",
    "resume_event",
    "revoke_event_staff",
    "schedule_event",
    "start_event",
    "transaction",
    "update_event",
)
