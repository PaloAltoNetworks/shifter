"""CTF challenge prerequisite operations.

Add/remove prerequisite edges between challenges, cycle detection (BFS),
and the participant-facing "prerequisites met" check consumed by
``_access.assert_challenge_available_for_participant`` /
``assert_challenge_readable_for_participant``.
"""

from __future__ import annotations

import logging
from collections import deque
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFChallengePrerequisite, CTFEvent, CTFParticipant
from ctf.services.authorization import assert_actor_owns_event as _assert_actor_owns_event
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


def _assert_prerequisites_met(
    challenge: CTFChallenge,
    participant: CTFParticipant,
) -> None:
    """Raise CTFStateError if any of `challenge`'s prerequisites are unmet."""
    prereqs_met, unmet_challenges = check_prerequisites_met(challenge.id, participant.id)
    if not prereqs_met:
        unmet_names = [c.name for c in unmet_challenges]
        raise CTFStateError(
            f"Prerequisites not met. Complete first: {', '.join(unmet_names)}",
            details={
                "challenge_id": str(challenge.id),
                "unmet_prerequisites": [str(c.id) for c in unmet_challenges],
            },
        )


def add_prerequisite(
    challenge_id: UUID,
    required_challenge_id: UUID,
    *,
    actor_id: int,
) -> CTFChallengePrerequisite:
    """Add a prerequisite to a challenge.

    Args:
        challenge_id: UUID of the dependent challenge.
        required_challenge_id: UUID of the required challenge.
        actor_id: User pk of the caller. Required (issue #765 DiD).

    Returns:
        The created CTFChallengePrerequisite instance.

    Raises:
        CTFNotFoundError: If either challenge doesn't exist.
        CTFPermissionError: If actor does not own the dependent challenge's event.
        CTFStateError: If event is not content-modifiable.
        CTFValidationError: If prerequisite is invalid (self-ref, different event, circular).
    """
    try:
        challenge = CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    _assert_actor_owns_event(actor_id, challenge.event)

    try:
        required = CTFChallenge.objects.select_related("event").get(pk=required_challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Required challenge {required_challenge_id} not found",
            details={"required_challenge_id": str(required_challenge_id)},
        ) from None

    if not challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot modify challenge in event with status {challenge.event.status}",
            details={"challenge_id": str(challenge_id), "event_status": challenge.event.status},
        )

    # Validate same event
    if challenge.event_id != required.event_id:
        raise CTFValidationError(
            "Prerequisites must be in the same event",
            details={
                "challenge_event": str(challenge.event_id),
                "required_event": str(required.event_id),
            },
        )

    # Self-reference
    if challenge_id == required_challenge_id:
        raise CTFValidationError(
            "A challenge cannot be a prerequisite of itself",
            details={"challenge_id": str(challenge_id)},
        )

    # Serialize prerequisite writes for this event so the duplicate and cycle
    # checks and the insert cannot interleave with a concurrent edit (#1144).
    # Without the lock, concurrent "A requires B" and "B requires A" each pass
    # _would_create_cycle against the pre-write graph and together close an
    # A<->B cycle (the unique constraint stops duplicate edges, not cycles),
    # soft-bricking both challenges. The event row is the serialization point.
    with transaction.atomic():
        CTFEvent.objects.select_for_update().get(pk=challenge.event_id)

        # Check duplicate
        if CTFChallengePrerequisite.objects.filter(
            challenge=challenge,
            required_challenge=required,
        ).exists():
            raise CTFValidationError(
                "This prerequisite already exists",
                details={
                    "challenge_id": str(challenge_id),
                    "required_challenge_id": str(required_challenge_id),
                },
            )

        # Circular dependency check (BFS)
        if _would_create_cycle(challenge_id, required_challenge_id):
            raise CTFValidationError(
                "Adding this prerequisite would create a circular dependency",
                details={
                    "challenge_id": str(challenge_id),
                    "required_challenge_id": str(required_challenge_id),
                },
            )

        prereq = CTFChallengePrerequisite.objects.create(
            challenge=challenge,
            required_challenge=required,
        )

    logger.info(
        "Added prerequisite: %s requires %s",
        safe_log_value(challenge_id),
        safe_log_value(required_challenge_id),
    )
    return prereq


def _would_create_cycle(challenge_id: UUID, required_challenge_id: UUID) -> bool:
    """Check if adding challenge_id -> required_challenge_id would create a cycle.

    We check if required_challenge_id can reach challenge_id through existing
    prerequisite links. If so, adding this edge creates a cycle.

    Args:
        challenge_id: The dependent challenge.
        required_challenge_id: The proposed required challenge.

    Returns:
        True if adding this prerequisite would create a cycle.
    """
    # BFS from required_challenge_id following prerequisites
    # If we can reach challenge_id, there's a cycle
    visited: set[UUID] = set()
    queue: deque[UUID] = deque([required_challenge_id])

    while queue:
        current = queue.popleft()
        if current == challenge_id:
            return True
        if current in visited:
            continue
        visited.add(current)

        # Get all challenges that 'current' requires
        prereq_ids = CTFChallengePrerequisite.objects.filter(
            challenge_id=current,
        ).values_list("required_challenge_id", flat=True)
        queue.extend(prereq_ids)

    return False


def remove_prerequisite(prerequisite_id: UUID, *, actor_id: int) -> None:
    """Remove a prerequisite.

    Args:
        prerequisite_id: UUID of the prerequisite to remove.
        actor_id: User pk of the caller. Required (issue #765 DiD).

    Raises:
        CTFNotFoundError: If prerequisite doesn't exist.
        CTFPermissionError: If actor does not own the dependent challenge's event.
        CTFStateError: If event is not content-modifiable.
    """
    try:
        prereq = CTFChallengePrerequisite.objects.select_related("challenge__event").get(pk=prerequisite_id)
    except CTFChallengePrerequisite.DoesNotExist:
        raise CTFNotFoundError(
            f"Prerequisite {prerequisite_id} not found",
            details={"prerequisite_id": str(prerequisite_id)},
        ) from None

    _assert_actor_owns_event(actor_id, prereq.challenge.event)

    if not prereq.challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot modify challenge in event with status {prereq.challenge.event.status}",
            details={"prerequisite_id": str(prerequisite_id), "event_status": prereq.challenge.event.status},
        )

    prereq.delete(soft=True)
    logger.info("Removed prerequisite %s", safe_log_value(prerequisite_id))


def get_prerequisites(challenge_id: UUID) -> QuerySet[CTFChallengePrerequisite]:
    """Get prerequisites for a challenge.

    Args:
        challenge_id: UUID of the challenge.

    Returns:
        QuerySet of CTFChallengePrerequisite instances.
    """
    return CTFChallengePrerequisite.objects.filter(
        challenge_id=challenge_id,
    ).select_related("required_challenge")


def get_dependents(challenge_id: UUID) -> QuerySet[CTFChallengePrerequisite]:
    """Get challenges that depend on this challenge.

    Args:
        challenge_id: UUID of the required challenge.

    Returns:
        QuerySet of CTFChallengePrerequisite instances.
    """
    return CTFChallengePrerequisite.objects.filter(
        required_challenge_id=challenge_id,
    ).select_related("challenge")


def check_prerequisites_met(challenge_id: UUID, participant_id: UUID) -> tuple[bool, list[CTFChallenge]]:
    """Check if a participant has met all prerequisites for a challenge.

    Args:
        challenge_id: UUID of the challenge.
        participant_id: UUID of the participant.

    Returns:
        Tuple of (all_met, list of unmet required challenges).
    """
    from ctf.models import CTFSubmission

    prereqs = CTFChallengePrerequisite.objects.filter(
        challenge_id=challenge_id,
    ).select_related("required_challenge")

    if not prereqs.exists():
        return True, []

    solved_ids = set(
        CTFSubmission.objects.filter(
            participant_id=participant_id,
            is_correct=True,
        ).values_list("challenge_id", flat=True)
    )

    unmet = [p.required_challenge for p in prereqs if p.required_challenge_id not in solved_ids]
    return len(unmet) == 0, unmet
