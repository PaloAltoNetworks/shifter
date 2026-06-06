"""CTF Participant service.

Provides business logic for participant management.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFEvent, CTFParticipant, CTFTeam
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def invite_participant(
    event_id: UUID,
    email: str,
    name: str,
    team_id: UUID | None = None,
) -> CTFParticipant:
    """Invite a participant to a CTF event.

    Args:
        event_id: UUID of the event.
        email: Participant's email address.
        name: Participant's display name.
        team_id: Optional team UUID to assign.

    Returns:
        The created CTFParticipant instance.

    Raises:
        CTFNotFoundError: If event or team doesn't exist.
        CTFValidationError: If participant already exists or data is invalid.
    """
    logger.info("Inviting participant %s to event %s", safe_log_value(email), safe_log_value(event_id))

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    # Check registration deadline
    if event.registration_deadline and timezone.now() > event.registration_deadline:
        raise CTFValidationError(
            "Registration deadline has passed",
            code="CTF_REGISTRATION_DEADLINE_PASSED",
            details={
                "event_id": str(event_id),
                "deadline": event.registration_deadline.isoformat(),
            },
        )

    # Check max participants
    if event.max_participants:
        current_count = event.participants.count()
        if current_count >= event.max_participants:
            raise CTFValidationError(
                f"Event has reached maximum participants ({event.max_participants})",
                code="CTF_MAX_PARTICIPANTS_REACHED",
                details={"event_id": str(event_id), "max": event.max_participants},
            )

    # Check for existing participant
    if CTFParticipant.objects.filter(event=event, email__iexact=email).exists():
        raise CTFValidationError(
            f"Participant with email {email} already exists in this event",
            code="CTF_DUPLICATE_PARTICIPANT",
            details={"email": email, "event_id": str(event_id)},
        )

    team = None
    if team_id:
        try:
            team = CTFTeam.objects.get(pk=team_id, event=event)
        except CTFTeam.DoesNotExist:
            raise CTFNotFoundError(
                f"Team {team_id} not found in event {event_id}",
                details={"team_id": str(team_id), "event_id": str(event_id)},
            ) from None

    with transaction.atomic():
        participant = CTFParticipant.objects.create(
            event=event,
            email=email.lower().strip(),
            name=name.strip(),
            team=team,
            status=ParticipantStatus.INVITED.value,
        )

        # Auto-register: create Django user and link to participant
        _auto_register_participant(participant)

        logger.info(
            "Invited participant %s to event %s (id: %s)",
            safe_log_value(email),
            safe_log_value(event_id),
            participant.id,
        )

    return participant


def _parse_participants_csv(csv_content: str) -> list[tuple[str, str]]:
    """Parse a CSV string into (name, email) tuples; raise on per-row errors.

    Empty rows are skipped. Per-row failures are accumulated and reported in
    one `CTFValidationError` so the caller can present every issue at once.
    """
    reader = csv.reader(io.StringIO(csv_content))
    participants_data: list[tuple[str, str]] = []
    errors: list[str] = []
    for line_num, row in enumerate(reader, start=1):
        if not row or (len(row) == 1 and not row[0].strip()):
            continue
        if len(row) < 2:
            errors.append(f"Line {line_num}: Expected name,email format")
            continue
        name = row[0].strip()
        email = row[1].strip().lower()
        if not name:
            errors.append(f"Line {line_num}: Name is required")
            continue
        if not email or "@" not in email:
            errors.append(f"Line {line_num}: Invalid email format")
            continue
        participants_data.append((name, email))
    if errors:
        raise CTFValidationError(
            "CSV validation errors",
            code="CTF_CSV_VALIDATION_ERROR",
            details={"errors": errors},
        )
    return participants_data


def _emails_or_raise_on_duplicate(participants_data: list[tuple[str, str]]) -> set[str]:
    """Return the set of unique emails; raise if any duplicate appears in input."""
    seen_emails: set[str] = set()
    duplicates: list[str] = []
    for _name, email in participants_data:
        if email in seen_emails:
            duplicates.append(email)
        seen_emails.add(email)
    if duplicates:
        raise CTFValidationError(
            "Duplicate emails in import",
            code="CTF_DUPLICATE_EMAILS",
            details={"duplicates": duplicates},
        )
    return seen_emails


def _assert_event_accepts_import(event: CTFEvent, participants_data: list[tuple[str, str]]) -> None:
    """Reject the import if the event is past deadline or would exceed cap."""
    if event.registration_deadline and timezone.now() > event.registration_deadline:
        raise CTFValidationError(
            "Registration deadline has passed",
            code="CTF_REGISTRATION_DEADLINE_PASSED",
            details={
                "event_id": str(event.pk),
                "deadline": event.registration_deadline.isoformat(),
            },
        )
    if not event.max_participants:
        return
    current_count = event.participants.count()
    if current_count + len(participants_data) > event.max_participants:
        raise CTFValidationError(
            f"Import would exceed maximum participants ({event.max_participants})",
            code="CTF_MAX_PARTICIPANTS_EXCEEDED",
            details={
                "current": current_count,
                "importing": len(participants_data),
                "max": event.max_participants,
            },
        )


def bulk_import_participants(
    event_id: UUID,
    csv_content: str,
) -> list[CTFParticipant]:
    """Bulk import participants from CSV content.

    CSV format: name,email (one per line)

    Args:
        event_id: UUID of the event.
        csv_content: CSV string with participant data.

    Returns:
        List of created CTFParticipant instances.

    Raises:
        CTFNotFoundError: If event doesn't exist.
        CTFValidationError: If CSV format is invalid.
    """
    logger.info("Bulk importing participants to event %s", safe_log_value(event_id))

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants_data = _parse_participants_csv(csv_content)
    seen_emails = _emails_or_raise_on_duplicate(participants_data)
    _assert_event_accepts_import(event, participants_data)

    existing = CTFParticipant.objects.filter(
        event=event,
        email__in=seen_emails,
    ).values_list("email", flat=True)
    if existing:
        raise CTFValidationError(
            "Some participants already exist",
            code="CTF_EXISTING_PARTICIPANTS",
            details={"existing": list(existing)},
        )

    created: list[CTFParticipant] = []
    with transaction.atomic():
        for name, email in participants_data:
            participant = CTFParticipant.objects.create(
                event=event,
                email=email,
                name=name,
                status=ParticipantStatus.INVITED.value,
            )
            _auto_register_participant(participant)
            created.append(participant)

    logger.info(
        "Bulk imported %d participants to event %s",
        len(created),
        safe_log_value(event_id),
    )
    return created


def get_participant_by_user(user: User, event_id: UUID | None = None) -> CTFParticipant | None:
    """Get an eligible participant record for a user.

    Codex review (issue #765/#768/#769) cycle 4: this helper is the entry
    point for every challenge-, hint-, scoreboard-, and dashboard-scoped
    view that resolves "the participant for this request." It now filters
    by `eligible_participant_q()` so a user with mixed eligibility across
    events can never act as a disqualified row in event A just because
    they are also eligible in event B. Callers MUST pass `event_id` when
    the route names a specific event (or a challenge belonging to one),
    so a multi-event user resolves to the correct participant.

    Args:
        user: The Django user.
        event_id: Event UUID to filter by. Strongly recommended for
            challenge- or event-scoped surfaces; without it, the helper
            returns the first eligible row across any event, which is
            only the right semantic for surfaces that are platform-wide
            (the active-event dashboard pulls its event from
            `UserProfile.active_ctf_event_id` and passes it here).

    Returns:
        The CTFParticipant instance or None.
    """
    qs = CTFParticipant.objects.filter(eligible_participant_q(), user=user)
    if event_id:
        qs = qs.filter(event_id=event_id)

    return qs.select_related("event", "team").first()


# Participant statuses considered "playing" for access-control AND scoring.
# DISQUALIFIED is intentionally excluded — a disqualified participant must
# be invisible to scoring AND blocked from access-control surfaces. Codex
# review #765/#768/#769 caught the predicate divergence between scoring
# and access checks; `eligible_participant_q` below is now the single
# source of truth and is reused by both layers.
_PLAYING_PARTICIPANT_STATUSES: tuple[str, ...] = (
    ParticipantStatus.ACTIVE.value,
    ParticipantStatus.REGISTERED.value,
    ParticipantStatus.COMPLETED.value,
)


def eligible_participant_q(field_prefix: str = "") -> Q:
    """Return a `Q` predicate matching participants eligible for scoring/access.

    A participant is eligible iff they have completed registration
    (`registered_at` is set) AND their status is one of ACTIVE / REGISTERED
    / COMPLETED — i.e. NOT disqualified. This is the single shared
    predicate used by `is_active_participant` (access control), by
    `get_scoreboard` (individual rankings), and by `get_team_scoreboard`
    (team aggregates) so the three layers cannot drift apart.

    Args:
        field_prefix: Django ORM lookup prefix to prepend, e.g. `""` when
            filtering on `CTFParticipant` directly, or `"members__"` when
            filtering on `CTFTeam` and reaching across the team→members
            relation. Must end in `__` when non-empty.

    Returns:
        A `Q` object combining the registration and status checks.
    """
    p = field_prefix
    return Q(**{f"{p}registered_at__isnull": False, f"{p}status__in": _PLAYING_PARTICIPANT_STATUSES})


def is_active_participant(user: User, event: CTFEvent | None = None) -> bool:
    """Return True if `user` is a non-disqualified registered participant.

    Used by `@ctf_participant_required`, the scoreboard endpoint, the
    challenge-file download endpoint, and any other surface that needs the
    same predicate as the scoring service. Without this, a disqualified
    participant whose `registered_at` is still set could pass the gate even
    though scoring excludes their rows.

    Args:
        user: The Django user to check.
        event: When supplied, scope the check to a single event; otherwise
            "is participant of any event" (e.g. for the platform-wide
            participant role decorator).
    """
    qs = CTFParticipant.objects.filter(eligible_participant_q(), user=user)
    if event is not None:
        qs = qs.filter(event=event)
    return qs.exists()


def disqualify_participant(participant_id: UUID, reason: str | None = None) -> CTFParticipant:
    """Disqualify a participant from the event.

    Args:
        participant_id: UUID of the participant.
        reason: Optional reason for disqualification.

    Returns:
        The updated CTFParticipant instance.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    logger.info("Disqualifying participant %s", participant_id)

    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    participant.status = ParticipantStatus.DISQUALIFIED.value
    participant.save(update_fields=["status", "updated_at"])

    # Clear CTF participant profile if user was linked
    if participant.user is not None:
        _clear_ctf_participant_profile(participant.user, participant.event)

    logger.info(
        "Disqualified participant %s: %s",
        participant_id,
        reason or "No reason provided",
    )

    return participant


def list_participants_for_event(event_id: UUID) -> QuerySet[CTFParticipant]:
    """List all participants for an event.

    Args:
        event_id: UUID of the event.

    Returns:
        QuerySet of CTFParticipant instances.
    """
    return CTFParticipant.objects.filter(event_id=event_id).select_related("team", "user", "bracket").order_by("name")


def get_participant(participant_id: UUID) -> CTFParticipant:
    """Get a participant by ID.

    Args:
        participant_id: UUID of the participant.

    Returns:
        The CTFParticipant instance.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    try:
        return CTFParticipant.objects.select_related("event", "team", "user").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None


def delete_participant(participant_id: UUID) -> bool:
    """Soft delete a participant.

    Args:
        participant_id: UUID of the participant.

    Returns:
        True if deleted successfully.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    logger.info("Deleting participant %s", safe_log_value(participant_id))

    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    # Clear CTF participant profile if user was linked
    if participant.user is not None:
        _clear_ctf_participant_profile(participant.user, participant.event)

    participant.delete(soft=True)
    logger.info("Deleted participant %s", safe_log_value(participant_id))

    return True


def resend_invite(participant_id: UUID) -> CTFParticipant:
    """Resend magic link email to a participant and refresh the token.

    Works for any participant regardless of registration status.

    Args:
        participant_id: UUID of the participant.

    Returns:
        The updated CTFParticipant instance.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    import secrets

    logger.info("Resending invite for participant %s", safe_log_value(participant_id))

    try:
        participant = CTFParticipant.objects.select_related("event").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    # Generate new token — valid through min(event end, configured expiry)
    from datetime import timedelta

    from django.conf import settings

    now = timezone.now()
    hours = getattr(settings, "MAGIC_LINK_EXPIRY_HOURS", 24)
    config_expiry = now + timedelta(hours=hours)
    token_expires = min(participant.event.event_end, config_expiry)

    participant.invite_token = secrets.token_urlsafe(32)
    participant.invite_token_expires = token_expires
    participant.invited_at = now
    participant.save(update_fields=["invite_token", "invite_token_expires", "invited_at", "updated_at"])

    # Send the invitation email
    from ctf.services.notification import _build_registration_url, _render_email, _send_email

    registration_url = _build_registration_url(participant.invite_token)
    html_content, text_content, custom_subject = _render_email(
        "invitation",
        {
            "event": participant.event,
            "participant": participant,
            "invite_token": participant.invite_token,
            "registration_url": registration_url,
        },
        event=participant.event,
    )
    sent = _send_email(
        recipient=participant.email,
        subject=custom_subject or f"You're invited to {participant.event.name}",
        html_content=html_content,
        text_content=text_content,
    )
    if not sent:
        logger.warning("Failed to send resend invite email for participant %s", safe_log_value(participant_id))

    logger.info("Resent invite for participant %s", safe_log_value(participant_id))

    return participant


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _auto_register_participant(participant: CTFParticipant) -> None:
    """Create a Django user and register the participant.

    Find-or-creates a Django user from the participant's email (with an
    unusable password), then links them and sets status to registered.
    This eliminates the separate "registration" step — participants are
    ready to access the platform as soon as they're added.
    """
    from django.contrib.auth.models import User

    user = User.objects.filter(email__iexact=participant.email).first()
    if user is None:
        user = User.objects.create_user(
            username=participant.email,
            email=participant.email,
            first_name=participant.name.split()[0] if participant.name else "",
            last_name=" ".join(participant.name.split()[1:]) if participant.name else "",
        )
        user.set_unusable_password()
        user.save()

    participant.user = user
    participant.status = ParticipantStatus.REGISTERED.value
    participant.registered_at = timezone.now()
    participant.save(update_fields=["user", "status", "registered_at", "updated_at"])
    _set_ctf_participant_profile(user, participant.event)

    logger.info(
        "Auto-registered participant %s (user %s)",
        participant.pk,
        user.email,
    )


def _set_ctf_participant_profile(user: User, event: CTFEvent):
    """Set CTF Participant group and active_ctf_event for a user.

    Adds the user to the CTF Participant group (additive — never removes
    other groups) and sets active_ctf_event on the profile.
    """
    from django.contrib.auth.models import Group

    from management.services import get_user_profile, set_active_ctf_event
    from shared.auth import CTF_PARTICIPANT_GROUP

    participant_group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
    user.groups.add(participant_group)

    set_active_ctf_event(user, event.pk)
    logger.info(
        "Set CTF participant profile for user %s (event %s)",
        user.email,
        event.pk,
    )
    return get_user_profile(user)


def _clear_ctf_participant_profile(user: User, event: CTFEvent) -> None:
    """Remove CTF Participant group and clear active_ctf_event.

    Only clears if the profile's active_ctf_event matches the given event,
    to avoid clobbering a profile linked to a different event.
    """
    from django.contrib.auth.models import Group

    from management.services import get_user_profile, set_active_ctf_event
    from shared.auth import CTF_PARTICIPANT_GROUP

    profile = get_user_profile(user)
    if profile.active_ctf_event_id == event.pk:
        participant_group = Group.objects.filter(name=CTF_PARTICIPANT_GROUP).first()
        if participant_group:
            user.groups.remove(participant_group)
        set_active_ctf_event(user, None)
        logger.info(
            "Cleared CTF participant profile for user %s (event %s)",
            user.email,
            event.pk,
        )
