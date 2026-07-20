"""CTF participant availability policy (issue #769).

Single source of truth for whether a participant may submit/unlock/read a
challenge. Used by `submit_flag`, `use_hint`, `rate_challenge`, the
file-download endpoint, and the participant-facing detail page so all paths
apply the same checks; hints must not be cheaper to obtain than flag
submission.

``_assert_prerequisites_met`` is imported directly from ``_prerequisites``
(not patched by tests at ``ctf.services.challenge`` level, so no call-time
package indirection is needed here).
"""

from __future__ import annotations

from django.utils import timezone

from ctf.exceptions import CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFEvent, CTFParticipant

from ._prerequisites import _assert_prerequisites_met


def _assert_participant_eligible(participant: CTFParticipant) -> None:
    """Raise CTFStateError unless the participant is registered and non-disqualified."""
    from ctf.services.participant.queries import _PLAYING_PARTICIPANT_STATUSES

    # Participant eligibility: aligned with `eligible_participant_q`.
    if participant.registered_at is None or participant.status not in _PLAYING_PARTICIPANT_STATUSES:
        raise CTFStateError(
            "Participant is not eligible",
            details={
                "participant_id": str(participant.id),
                "status": participant.status,
            },
        )


def _assert_event_active_and_in_window(event: CTFEvent) -> None:
    """Raise CTFStateError unless the event is ACTIVE and within its competition window."""
    from ctf.enums import EventStatus

    if event.status != EventStatus.ACTIVE.value:
        raise CTFStateError(
            f"Event is not active (status: {event.status})",
            details={"event_id": str(event.id), "status": event.status},
        )

    now = timezone.now()
    if now < event.event_start or now > event.event_end:
        raise CTFStateError(
            "Event is not within its competition window",
            details={
                "event_id": str(event.id),
                "event_start": event.event_start.isoformat(),
                "event_end": event.event_end.isoformat(),
                "server_time": now.isoformat(),
            },
        )


def _assert_challenge_visible_and_released(challenge: CTFChallenge) -> None:
    """Raise CTFStateError unless the challenge is visible (not hidden/locked) and released."""
    if challenge.visibility == "hidden":
        raise CTFStateError(
            "Challenge is not available",
            details={"challenge_id": str(challenge.id)},
        )
    if challenge.visibility == "locked":
        raise CTFStateError(
            "Challenge is locked",
            details={"challenge_id": str(challenge.id)},
        )

    if not challenge.is_released:
        raise CTFStateError(
            "Challenge has not been released yet",
            details={
                "challenge_id": str(challenge.id),
                "release_time": challenge.release_time.isoformat() if challenge.release_time else None,
            },
        )


def assert_challenge_available_for_participant(
    participant: CTFParticipant,
    challenge: CTFChallenge,
) -> None:
    """Raise if `participant` cannot legitimately interact with `challenge`.

    Single source of truth for participant→challenge availability. Used by
    `submit_flag`, `use_hint`, `rate_challenge`, and the file-download
    endpoint so all paths apply the same checks; hints must not be cheaper
    to obtain than flag submission (issue #769).

    Checks, in order: (0) participant is registered & non-disqualified
    (codex review #765 cycle 6 — without this, an internal caller passing
    a raw participant_id for an INVITED or DISQUALIFIED row would bypass
    the eligibility check applied at the view layer), (1) challenge
    belongs to participant's event, (2) event is in ACTIVE status,
    (3) `now` is within `event_start..event_end`, (4) challenge visibility
    is not `hidden` or `locked`, (5) `challenge.is_released`,
    (6) prerequisites met.

    Raises:
        CTFValidationError: when challenge.event != participant.event.
        CTFStateError: any availability gate fails (including ineligible
            participant).
    """
    _assert_participant_eligible(participant)

    if challenge.event_id != participant.event_id:
        raise CTFValidationError(
            "Challenge does not belong to participant's event",
            details={
                "participant_event": str(participant.event_id),
                "challenge_event": str(challenge.event_id),
            },
        )

    _assert_event_active_and_in_window(challenge.event)
    _assert_challenge_visible_and_released(challenge)
    _assert_prerequisites_met(challenge, participant)


def assert_challenge_readable_for_participant(
    participant: CTFParticipant,
    challenge: CTFChallenge,
) -> None:
    """Raise if `participant` cannot READ this challenge's content.

    Codex review (#765 cycle 8): the submit/hint policy was too strict for
    the read-only detail page. `LOCKED` is documented as
    "shown-but-not-submittable", and the detail page also serves the
    `show_solution` view for ENDED/ARCHIVED events. Read-availability
    therefore omits the event-status, event-window, and locked-visibility
    gates that the write/unlock policy enforces.

    Read-availability still requires:
      - participant eligibility (registered, non-disqualified)
      - same-event match
      - challenge not HIDDEN
      - `challenge.is_released` (so future-release content stays hidden)
      - prerequisites met

    Used by participant-facing read endpoints (`challenge_detail`).
    Submit/hint/file-download endpoints continue to use
    `assert_challenge_available_for_participant`.
    """
    from ctf.services.participant.queries import _PLAYING_PARTICIPANT_STATUSES

    if participant.registered_at is None or participant.status not in _PLAYING_PARTICIPANT_STATUSES:
        raise CTFStateError(
            "Participant is not eligible",
            details={"participant_id": str(participant.id), "status": participant.status},
        )

    if challenge.event_id != participant.event_id:
        raise CTFValidationError(
            "Challenge does not belong to participant's event",
            details={
                "participant_event": str(participant.event_id),
                "challenge_event": str(challenge.event_id),
            },
        )

    if challenge.visibility == "hidden":
        raise CTFStateError(
            "Challenge is not available",
            details={"challenge_id": str(challenge.id)},
        )

    if not challenge.is_released:
        raise CTFStateError(
            "Challenge has not been released yet",
            details={
                "challenge_id": str(challenge.id),
                "release_time": challenge.release_time.isoformat() if challenge.release_time else None,
            },
        )

    _assert_prerequisites_met(challenge, participant)
