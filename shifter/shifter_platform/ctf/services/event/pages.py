"""Event custom-page and reserved-briefing service (CTF-1303 / #1854).

The single CTF-owned boundary for reading and mutating ``CTFEventPage`` rows,
including the reserved per-event participant briefing (``RESERVED_BRIEFING_SLUG``).
The organizer page API and the participant briefing lookup both go through here
so page bounds, reserved-slug resolution, duplicate-conflict mapping, and audit
live in exactly one place rather than being duplicated across views. Guidance
source is stored verbatim; sanitisation is the render layer's job, not a
destructive write transform.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from ctf.exceptions import CTFValidationError
from ctf.models import CTFEventPage
from ctf.models.event import (
    MAX_EVENT_PAGE_BODY_CHARS,
    MAX_EVENT_PAGES_PER_EVENT,
    RESERVED_BRIEFING_SLUG,
)

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFEvent


def list_active_pages(event_id: UUID, *, include_reserved: bool = False) -> list[CTFEventPage]:
    """Return the event's active pages in display order.

    Excludes the reserved briefing page by default so it never appears in the
    generic participant event-pages list; the briefing owns its own surface.
    The organizer editor passes ``include_reserved=True`` and separates the
    reserved page itself.
    """
    queryset = CTFEventPage.objects.filter(event_id=event_id, deleted_at__isnull=True)
    if not include_reserved:
        queryset = queryset.exclude(slug=RESERVED_BRIEFING_SLUG)
    return list(queryset)


def get_active_briefing(event_id: UUID) -> CTFEventPage | None:
    """Return the event's active reserved briefing page, or ``None``.

    A soft-deleted or absent briefing returns ``None`` so the caller renders its
    generic fallback; an infrastructure failure raises instead of masquerading
    as absence.
    """
    return CTFEventPage.objects.filter(
        event_id=event_id,
        slug=RESERVED_BRIEFING_SLUG,
        deleted_at__isnull=True,
    ).first()


def create_event_page(
    event: CTFEvent,
    *,
    title: str,
    body: str,
    slug: str | None = None,
    order: int = 0,
    actor_id: int | None = None,
) -> CTFEventPage:
    """Create a page under the single service boundary, enforcing bounds.

    Raises :class:`CTFValidationError` for an over-limit body, when the event
    already holds the maximum number of pages, or for a duplicate slug (the DB
    conditional-unique constraint is the concurrency backstop, mapped here to a
    controlled validation response rather than a 500).
    """
    if len(body) > MAX_EVENT_PAGE_BODY_CHARS:
        raise CTFValidationError("Page body exceeds the maximum length.")
    active_count = CTFEventPage.objects.filter(event=event, deleted_at__isnull=True).count()
    if active_count >= MAX_EVENT_PAGES_PER_EVENT:
        raise CTFValidationError("This event already has the maximum number of pages.")
    resolved_slug = slugify(slug or title)[:140]
    try:
        with transaction.atomic():
            page = CTFEventPage.objects.create(
                event=event,
                title=title,
                slug=resolved_slug,
                body=body,
                order=order,
            )
    except (ValidationError, IntegrityError) as exc:
        raise CTFValidationError("A page with this slug already exists.") from exc
    _audit(actor_id, event_id=event.pk, page=page, action="create")
    return page


def update_event_page(
    page: CTFEventPage,
    *,
    fields: dict[str, object],
    actor_id: int | None = None,
) -> CTFEventPage:
    """Apply the given ``title``/``body``/``order`` subset with bounds; slug is stable."""
    body = fields.get("body")
    if isinstance(body, str) and len(body) > MAX_EVENT_PAGE_BODY_CHARS:
        raise CTFValidationError("Page body exceeds the maximum length.")
    for name in ("title", "body", "order"):
        if name in fields:
            setattr(page, name, fields[name])
    page.save()
    _audit(actor_id, event_id=page.event_id, page=page, action="update")
    return page


def delete_event_page(page: CTFEventPage, *, actor_id: int | None = None) -> None:
    """Soft-delete the page; soft-deleting the reserved briefing restores fallback."""
    page.delete(soft=True)
    _audit(actor_id, event_id=page.event_id, page=page, action="delete")


def _audit(actor_id: int | None, *, event_id: UUID, page: CTFEventPage, action: str) -> None:
    """Record the mutation with ids/lengths only; guidance body never enters audit."""
    if actor_id is None:
        return
    from ctf.services.audit import audit_event_page

    audit_event_page(
        actor_id=actor_id,
        event_id=event_id,
        page_id=page.pk,
        slug=page.slug,
        body_length=len(page.body),
        action=action,
    )
