"""CTFEventPage — organizer-authored informational event pages (CTF-1303).

Split from ``event.py`` to keep each model module within the file-size budget
(python:S104). The page-related constants (``RESERVED_BRIEFING_SLUG``,
``MAX_EVENT_PAGE_BODY_CHARS``, ``MAX_EVENT_PAGES_PER_EVENT``) stay in
``ctf.models.event`` where other layers import them; this module owns only the
model. Re-exported by ``ctf/models/__init__.py`` so ``from ctf.models import
CTFEventPage`` keeps working unchanged.
"""

from __future__ import annotations

from django.db import models

from ._base import CTFBaseModel
from .event import CTFEvent


class CTFEventPage(CTFBaseModel):
    """One organizer-authored informational page for an event (CTF-1303)."""

    event = models.ForeignKey(
        CTFEvent,
        on_delete=models.CASCADE,
        related_name="pages",
        help_text="Event this page belongs to",
    )
    title = models.CharField(
        max_length=120,
        help_text="Page title shown in the participant navigation",
    )
    slug = models.SlugField(
        max_length=140,
        help_text="URL-safe identifier, unique per event",
    )
    body = models.TextField(
        help_text="Markdown content",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order in the participant navigation",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_event_page"
        ordering = ["order", "title"]
        verbose_name = "CTF Event Page"
        verbose_name_plural = "CTF Event Pages"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "slug"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_ctf_event_page_slug",
            ),
        ]

    def __str__(self) -> str:
        """Return the page title with its event."""
        return f"{self.title} ({self.event_id})"
