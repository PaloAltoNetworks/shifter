"""Lifecycle invariants shared across CMS models with terminal statuses.

Models whose ``status`` field includes terminal values (DESTROYED, FAILED)
and that carry a nullable ``deleted_at`` field auto-soft-delete when
``status`` transitions to a terminal value. This module centralises that
invariant so every ``save()`` enforces it identically.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from shared.enums import TERMINAL_STATUSES


def apply_terminal_soft_delete(instance: Any, save_kwargs: dict[str, Any]) -> bool:
    """Set ``instance.deleted_at`` if ``instance.status`` is terminal.

    Reads ``instance.status`` (a string column) against the value set
    derived from :data:`shared.enums.TERMINAL_STATUSES`. When the status
    matches and ``deleted_at`` is unset, ``deleted_at`` is updated to
    ``timezone.now()``. When ``save_kwargs`` contains ``update_fields``,
    ``"deleted_at"`` is appended so the change persists on partial saves.

    Returns ``True`` when the soft-delete was applied (so the caller can
    emit a log line); ``False`` otherwise. Safe when ``instance.status``
    is an unrecognised value — it simply returns ``False``.
    """
    terminal_values = {s.value for s in TERMINAL_STATUSES}
    if instance.status in terminal_values and instance.deleted_at is None:
        instance.deleted_at = timezone.now()
        update_fields = save_kwargs.get("update_fields")
        if update_fields is not None and "deleted_at" not in update_fields:
            save_kwargs["update_fields"] = [*list(update_fields), "deleted_at"]
        return True
    return False
