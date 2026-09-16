"""Participant lifecycle operations (add, resend login info, delete)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFEvent, CTFParticipant, CTFTeam
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def add_participant(
    event_id: UUID,
    email: str,
    name: str,
    team_id: UUID | None = None,
) -> CTFParticipant:
    """Add a participant to a CTF event by provisioning a fresh isolated account.

    Immediate seat provisioning: the returned participation is ``registered``
    with a linked isolated account -- there is no invitation awaiting acceptance.

    Args:
        event_id: UUID of the event.
        email: Optional delivery email for non-secret login information.
        name: Participant's display name.
        team_id: Optional team UUID to assign.

    Returns:
        The created CTFParticipant instance.

    Raises:
        CTFNotFoundError: If event or team doesn't exist.
        CTFValidationError: If participant already exists or data is invalid.
    """
    logger.info("Creating participant account for event %s", safe_log_value(event_id))

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    # CTF-705: the registration deadline closes SELF-registration; organizer
    # manual additions (this path and bulk import) intentionally bypass it so
    # stragglers can be added to a live event. Capacity still applies below.

    # Capacity is enforced under the event row lock inside the transaction
    # below (#1145), so concurrent invites cannot race past max_participants.

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

        # CTF-601: a delivery email may appear at most once per event; check
        # under the event lock so concurrent invites cannot double-insert
        # (the partial unique constraint backstops any other write path).
        normalized_email = email.lower().strip()
        if normalized_email and event.participants.filter(email=normalized_email).exists():
            raise CTFValidationError(
                "A participant with this email already exists for this event",
                code="CTF_DUPLICATE_EMAIL",
                details={"event_id": str(event_id), "email": normalized_email},
            )

        if team is not None:
            # CTF-505 (#648): organizer team assignment honors the same
            # capacity cap as participant joins; lock the team row so
            # concurrent assignments cannot race past the limit.
            locked_team = CTFTeam.objects.select_for_update().get(pk=team.pk)
            if locked_team.is_full:
                raise CTFValidationError(
                    "Team is at its size limit",
                    code="CTF_TEAM_FULL",
                    details={"team_id": str(locked_team.pk)},
                )

        from ctf.services.participant.accounts import provision_participant_seat
        from ctf.services.range import request_event_provisioning

        # Organizer add is immediate seat provisioning: the participation is
        # registered with a fresh isolated account in one step (no transient
        # INVITED hop, no invitation awaiting acceptance).
        participant = provision_participant_seat(event, email=normalized_email, name=name.strip(), team=team)
        transaction.on_commit(lambda: request_event_provisioning(event.pk, source="participant_accounts"))

        logger.info(
            "Provisioned participant account for event %s (id: %s)",
            safe_log_value(event_id),
            participant.id,
        )

    # CTF-1203: new-registration webhook, post-commit and best-effort.
    from ctf.services.webhook import emit_webhook

    emit_webhook(
        event,
        "participant_registered",
        {"participant_id": str(participant.pk), "name": participant.name},
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

    with transaction.atomic():
        # Clear CTF participant profile if user was linked
        if participant.user is not None:
            from ctf.services.participant.accounts import anonymize_participant_account

            anonymize_participant_account(participant.pk)

        participant.delete(soft=True)

        # Stop this participation's unclaimed communications and erase its delivery
        # coordinate in the same transaction as the removal; the immutable snapshot
        # identity survives as bounded evidence (#2099, AC3).
        from ctf.services.communication import on_participant_removed

        on_participant_removed(participant)

    logger.info("Deleted participant %s", safe_log_value(participant_id))

    return True


def resend_login_info(participant_id: UUID) -> CTFParticipant:
    """Compatibility facade for resending non-secret login information."""
    from ctf.services.participant.credentials import reset_participant_credentials

    return reset_participant_credentials(participant_id)


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
