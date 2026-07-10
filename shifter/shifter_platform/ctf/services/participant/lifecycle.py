"""Participant lifecycle operations (invite, resend, delete, disqualify)."""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
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

    # Capacity is enforced under the event row lock inside the transaction
    # below (#1145), so concurrent invites cannot race past max_participants.

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
        # Lock the event so the capacity check and the insert cannot race past
        # max_participants under concurrent invites (#1145).
        CTFEvent.objects.select_for_update().get(pk=event.pk)
        if event.max_participants and event.participants.count() >= event.max_participants:
            raise CTFValidationError(
                f"Event has reached maximum participants ({event.max_participants})",
                code="CTF_MAX_PARTICIPANTS_REACHED",
                details={"event_id": str(event_id), "max": event.max_participants},
            )

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

    # Maintain the materialized leaderboard (issue #850): a disqualified
    # participant drops off the individual board via the eligibility filter at
    # read time, but their team's materialized score must shed their
    # contribution now.
    if participant.team_id is not None:
        from ctf.services.scoring import recompute_team_score

        recompute_team_score(participant.team_id)

    # Clear CTF participant profile if user was linked
    if participant.user is not None:
        _clear_ctf_participant_profile(participant.user, participant.event)

    logger.info(
        "Disqualified participant %s: %s",
        participant_id,
        reason or "No reason provided",
    )

    return participant


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
    logger.info("Resending invite for participant %s", safe_log_value(participant_id))

    try:
        participant = CTFParticipant.objects.select_related("event").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    now = timezone.now()

    participant.invite_token = secrets.token_urlsafe(32)
    participant.invite_token_expires = CTFParticipant.default_invite_token_expiry(participant.event, now=now)
    participant.invited_at = now
    participant.save(update_fields=["invite_token", "invite_token_expires", "invited_at", "updated_at"])

    from ctf.services.notification import _build_registration_url, _render_email, _send_email

    registration_url = _build_registration_url(participant.invite_token)
    html_content, text_content, custom_subject = _render_email(
        "invitation",
        {
            "event": participant.event,
            "participant": participant,
            # Expose only the registration URL, not the raw token, so
            # organizer-authored templates cannot reintroduce the token into a
            # query string or other leak surface (#1088).
            "registration_url": registration_url,
        },
        event=participant.event,
    )
    # _send_email dispatches asynchronously (PLAT-103 clause 3) and returns
    # immediately with no synchronous delivery-success signal; delivery
    # failures are logged inside the background worker, not here.
    _send_email(
        recipient=participant.email,
        subject=custom_subject or f"You're invited to {participant.event.name}",
        html_content=html_content,
        text_content=text_content,
    )

    logger.info("Resent invite for participant %s", safe_log_value(participant_id))

    return participant


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


def _set_ctf_participant_profile(user: User, event: CTFEvent) -> None:
    """Set CTF Participant group and active_ctf_event for a user.

    Adds the user to the CTF Participant group (additive — never removes
    other groups) and sets active_ctf_event on the profile. ``set_active_ctf_event``
    already ensures the profile row exists, so nothing is returned (the single
    caller ignores the value, and ctf must not surface a ``management`` model type
    across the layer boundary — ADR-001).
    """
    from django.contrib.auth.models import Group

    from management.services import set_active_ctf_event
    from shared.auth import CTF_PARTICIPANT_GROUP

    participant_group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
    user.groups.add(participant_group)

    set_active_ctf_event(user, event.pk)
    logger.info(
        "Set CTF participant profile for user %s (event %s)",
        user.email,
        event.pk,
    )


def _clear_ctf_participant_profile(user: User, event: CTFEvent) -> None:
    """Re-point or clear the user's CTF profile when removed from ``event``.

    Only acts when the profile's ``active_ctf_event`` is the given event. The
    CTF Participant group is platform-wide, so it must only be removed when the
    user has no other eligible participation left; otherwise removing it (and
    nulling ``active_ctf_event``) would lock the user out of unrelated events
    they still belong to (#1142). When another eligible participation exists,
    re-point ``active_ctf_event`` to it and keep the group.
    """
    from django.contrib.auth.models import Group

    from ctf.services.participant.queries import eligible_participant_q
    from management.services import get_user_profile, set_active_ctf_event
    from shared.auth import CTF_PARTICIPANT_GROUP

    profile = get_user_profile(user)
    if profile.active_ctf_event_id != event.pk:
        return

    other = (
        CTFParticipant.objects.filter(eligible_participant_q(), user=user)
        .exclude(event=event)
        .order_by("-event__event_start")
        .first()
    )
    if other is not None:
        # Still an eligible participant elsewhere: keep CTF access, just move the
        # active event so role-scoped views resolve the remaining participation.
        set_active_ctf_event(user, other.event_id)
        logger.info(
            "Re-pointed CTF active event for user %s from %s to %s",
            user.email,
            event.pk,
            other.event_id,
        )
        return

    participant_group = Group.objects.filter(name=CTF_PARTICIPANT_GROUP).first()
    if participant_group:
        user.groups.remove(participant_group)
    set_active_ctf_event(user, None)
    logger.info(
        "Cleared CTF participant profile for user %s (event %s)",
        user.email,
        event.pk,
    )
