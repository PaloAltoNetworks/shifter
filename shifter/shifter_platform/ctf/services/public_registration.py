"""Public CTF event projection and pending-registration intake (#2157)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from ctf.enums import EventStatus, PublicRegistrationDisposition
from ctf.models import CTFEvent, CTFPublicRegistrationRequest
from ctf.services.audit import audit_public_registration_disposition

MAX_PUBLIC_DESCRIPTION_CHARS = 5_000
MAX_PENDING_REGISTRATION_REQUESTS = 2_000


class PublicEventUnavailable(LookupError):
    """Raised for every undiscoverable public-event variant."""


class PublicRegistrationClosed(RuntimeError):
    """Raised when an otherwise visible event no longer accepts requests."""


class PublicRegistrationQueueFull(RuntimeError):
    """Raised when the event's bounded pending-intake queue is full."""


class PublicRegistrationRequestNotFound(LookupError):
    """Raised when an organizer request identifier does not resolve."""


class PublicRegistrationAlreadyDispositioned(RuntimeError):
    """Raised when an organizer repeats or races a terminal disposition."""


@dataclass(frozen=True, slots=True)
class PublicEventProjection:
    """Allowlisted browser projection of one explicitly published event."""

    event_id: UUID
    name: str
    description: str
    event_start: datetime
    event_end: datetime
    registration_deadline: datetime
    registration_open: bool
    event_timezone: str


@dataclass(frozen=True, slots=True)
class PublicRegistrationSubmission:
    """Disclosure-resistant outcome returned by the intake service."""

    request_id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class PublicRegistrationDispositionResult:
    """Bounded result of one organizer disposition command."""

    request_id: UUID
    disposition: str
    participant_id: UUID | None


def _project_eligible_event(event: CTFEvent, *, at: datetime) -> PublicEventProjection:
    """Apply the one publication policy used by public GET and POST."""
    if (
        event.deleted_at is not None
        or not event.public_registration_enabled
        or event.workspace_id is None
        or event.status != EventStatus.REGISTRATION.value
    ):
        raise PublicEventUnavailable
    deadline = event.effective_registration_deadline
    description = event.description if len(event.description) <= MAX_PUBLIC_DESCRIPTION_CHARS else ""
    return PublicEventProjection(
        event_id=event.pk,
        name=event.name,
        description=description,
        event_start=event.event_start,
        event_end=event.event_end,
        registration_deadline=deadline,
        registration_open=at < deadline,
        event_timezone=event.event_timezone,
    )


def resolve_public_event(event_public_id: UUID, *, at: datetime | None = None) -> PublicEventProjection:
    """Resolve one public locator without exposing why another locator failed."""
    try:
        event = CTFEvent.objects.get(pk=event_public_id)
    except CTFEvent.DoesNotExist:
        raise PublicEventUnavailable from None
    return _project_eligible_event(event, at=at or timezone.now())


def _existing_submission(event: CTFEvent, normalized_email: str) -> CTFPublicRegistrationRequest | None:
    """Return the live intake row already associated with this event/email."""
    return event.public_registration_requests.filter(email__iexact=normalized_email).first()


def submit_public_registration_request(
    event_public_id: UUID,
    *,
    name: str,
    email: str,
    at: datetime | None = None,
) -> PublicRegistrationSubmission:
    """Store one idempotent pending request under the event publication lock."""
    normalized_name = name.strip()
    normalized_email = email.strip().lower()
    with transaction.atomic():
        try:
            event = CTFEvent.objects.select_for_update().get(pk=event_public_id)
        except CTFEvent.DoesNotExist:
            raise PublicEventUnavailable from None
        projection = _project_eligible_event(event, at=at or timezone.now())
        if not projection.registration_open:
            raise PublicRegistrationClosed

        existing = _existing_submission(event, normalized_email)
        if existing is not None:
            return PublicRegistrationSubmission(request_id=existing.pk, created=False)
        pending_count = event.public_registration_requests.filter(
            disposition=PublicRegistrationDisposition.PENDING.value
        ).count()
        if pending_count >= MAX_PENDING_REGISTRATION_REQUESTS:
            raise PublicRegistrationQueueFull

        request_row = CTFPublicRegistrationRequest(
            event=event,
            name=normalized_name,
            email=normalized_email,
        )
        request_row.save()
        return PublicRegistrationSubmission(request_id=request_row.pk, created=True)


def list_pending_public_registration_requests(
    event_id: UUID,
    *,
    actor_id: int,
) -> QuerySet[CTFPublicRegistrationRequest]:
    """Return the event's pending queue after service-boundary authorization."""
    from ctf.enums import EventCapability
    from ctf.services.authorization import assert_event_capability

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise PublicRegistrationRequestNotFound from None
    assert_event_capability(actor_id, event, EventCapability.PARTICIPANTS)
    return event.public_registration_requests.filter(disposition=PublicRegistrationDisposition.PENDING.value).order_by(
        "created_at", "id"
    )


def _locked_pending_request(request_id: UUID, *, actor_id: int) -> CTFPublicRegistrationRequest:
    """Lock and authorize one still-pending request."""
    from ctf.enums import EventCapability
    from ctf.services.authorization import assert_event_capability

    try:
        request_row = (
            CTFPublicRegistrationRequest.objects.select_for_update().select_related("event").get(pk=request_id)
        )
    except CTFPublicRegistrationRequest.DoesNotExist:
        raise PublicRegistrationRequestNotFound from None
    assert_event_capability(actor_id, request_row.event, EventCapability.PARTICIPANTS)
    if request_row.disposition != PublicRegistrationDisposition.PENDING.value:
        raise PublicRegistrationAlreadyDispositioned
    return request_row


def approve_public_registration_request(request_id: UUID, *, actor_id: int) -> PublicRegistrationDispositionResult:
    """Admit one request through the canonical participant service."""
    from ctf.services.participant.lifecycle import add_participant

    with transaction.atomic():
        request_row = _locked_pending_request(request_id, actor_id=actor_id)
        participant = add_participant(request_row.event_id, request_row.email, request_row.name)
        request_row.disposition = PublicRegistrationDisposition.APPROVED.value
        request_row.dispositioned_at = timezone.now()
        request_row.save(update_fields=["disposition", "dispositioned_at", "updated_at"])
        audit_public_registration_disposition(
            actor_id=actor_id,
            event_id=request_row.event_id,
            request_id=request_row.pk,
            disposition=request_row.disposition,
        )
        return PublicRegistrationDispositionResult(
            request_id=request_row.pk,
            disposition=request_row.disposition,
            participant_id=participant.pk,
        )


def reject_public_registration_request(request_id: UUID, *, actor_id: int) -> PublicRegistrationDispositionResult:
    """Reject one pending request without invoking participant admission."""
    with transaction.atomic():
        request_row = _locked_pending_request(request_id, actor_id=actor_id)
        request_row.disposition = PublicRegistrationDisposition.REJECTED.value
        request_row.dispositioned_at = timezone.now()
        request_row.save(update_fields=["disposition", "dispositioned_at", "updated_at"])
        audit_public_registration_disposition(
            actor_id=actor_id,
            event_id=request_row.event_id,
            request_id=request_row.pk,
            disposition=request_row.disposition,
        )
        return PublicRegistrationDispositionResult(
            request_id=request_row.pk,
            disposition=request_row.disposition,
            participant_id=None,
        )


def purge_expired_public_registration_requests(
    *,
    at: datetime | None = None,
    batch_size: int = 500,
) -> int:
    """Hard-delete one bounded batch of intake PII after event retention expires."""
    from datetime import timedelta

    from django.conf import settings
    from django.db.models import Q

    retention_hours = max(
        0,
        int(getattr(settings, "CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS", 24)),
    )
    cutoff = (at or timezone.now()) - timedelta(hours=retention_hours)
    limit = max(1, min(int(batch_size), 5_000))
    expired_event = Q(event__event_end__lte=cutoff) | Q(
        event__status=EventStatus.CANCELLED.value,
        event__updated_at__lte=cutoff,
    )
    request_ids = list(
        CTFPublicRegistrationRequest.all_objects.filter(expired_event)
        .order_by("created_at", "id")
        .values_list("pk", flat=True)[:limit]
    )
    if not request_ids:
        return 0
    CTFPublicRegistrationRequest.all_objects.filter(pk__in=request_ids).delete()
    return len(request_ids)
