"""CTF Hint service.

Provides business logic for progressive challenge hints.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet, Sum

from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFHint, CTFHintUsage, CTFParticipant

logger = logging.getLogger(__name__)


def add_hint(challenge_id: UUID, hint_data: dict[str, Any], *, actor_id: int) -> CTFHint:
    """Add a hint to a challenge.

    Args:
        challenge_id: UUID of the challenge.
        hint_data: Dict with 'text', 'penalty' (0-100), and optional 'order'.
        actor_id: User pk of the caller. Required (issue #765 DiD).

    Returns:
        The created CTFHint instance.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
        CTFPermissionError: If actor does not own the challenge's event.
        CTFStateError: If event is not content-modifiable.
    """
    from ctf.services.authorization import assert_actor_owns_event

    try:
        challenge = CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    assert_actor_owns_event(actor_id, challenge.event)

    if not challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot modify hints in event with status {challenge.event.status}",
            details={"event_status": challenge.event.status},
        )

    text = hint_data.get("text", "")
    if not text:
        raise CTFValidationError("Hint text is required", details={"missing_fields": ["text"]})

    penalty = hint_data.get("penalty", 0)
    order = hint_data.get("order", challenge.hints.count())

    hint = CTFHint.objects.create(
        challenge=challenge,
        text=text,
        penalty=penalty,
        order=order,
    )

    logger.info("Added hint %s (order=%d) to challenge %s", hint.id, order, challenge_id)
    return hint


def update_hint(hint_id: UUID, hint_data: dict[str, Any], *, actor_id: int) -> CTFHint:
    """Update a hint's text, penalty, or order.

    Args:
        hint_id: UUID of the hint.
        hint_data: Dict with fields to update.
        actor_id: User pk of the caller. Required (issue #765 DiD).

    Returns:
        The updated CTFHint instance.

    Raises:
        CTFNotFoundError: If hint doesn't exist.
        CTFPermissionError: If actor does not own the hint's event.
        CTFStateError: If event is not content-modifiable.
    """
    from ctf.services.authorization import assert_actor_owns_event

    try:
        hint = CTFHint.objects.select_related("challenge__event").get(pk=hint_id)
    except CTFHint.DoesNotExist:
        raise CTFNotFoundError(
            f"Hint {hint_id} not found",
            details={"hint_id": str(hint_id)},
        ) from None

    assert_actor_owns_event(actor_id, hint.challenge.event)

    if not hint.challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot modify hints in event with status {hint.challenge.event.status}",
            details={"event_status": hint.challenge.event.status},
        )

    for field in ("text", "penalty", "order"):
        if field in hint_data:
            setattr(hint, field, hint_data[field])
    hint.save()

    logger.info("Updated hint %s", hint_id)
    return hint


def remove_hint(hint_id: UUID, *, actor_id: int) -> None:
    """Soft-delete a hint.

    Args:
        hint_id: UUID of the hint.
        actor_id: User pk of the caller. Required (issue #765 DiD).

    Raises:
        CTFNotFoundError: If hint doesn't exist.
        CTFPermissionError: If actor does not own the hint's event.
        CTFStateError: If event is not content-modifiable.
    """
    from ctf.services.authorization import assert_actor_owns_event

    try:
        hint = CTFHint.objects.select_related("challenge__event").get(pk=hint_id)
    except CTFHint.DoesNotExist:
        raise CTFNotFoundError(
            f"Hint {hint_id} not found",
            details={"hint_id": str(hint_id)},
        ) from None

    assert_actor_owns_event(actor_id, hint.challenge.event)

    if not hint.challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot modify hints in event with status {hint.challenge.event.status}",
            details={"event_status": hint.challenge.event.status},
        )

    hint.delete(soft=True)
    logger.info("Removed hint %s", hint_id)


def get_hints(challenge_id: UUID) -> QuerySet[CTFHint]:
    """Get all hints for a challenge, ordered by reveal order.

    Args:
        challenge_id: UUID of the challenge.

    Returns:
        QuerySet of CTFHint instances.
    """
    return CTFHint.objects.filter(challenge_id=challenge_id).order_by("order", "created_at")


def use_hint(
    participant_id: UUID,
    hint_id: UUID,
    *,
    expected_challenge_id: UUID | None = None,
) -> dict[str, Any]:
    """Unlock a specific hint for a participant.

    Validates sequential ordering: all preceding hints must be unlocked first.

    Args:
        participant_id: UUID of the participant.
        hint_id: UUID of the hint to unlock.
        expected_challenge_id: When supplied, the service refuses unless
            `hint.challenge_id == expected_challenge_id`. Issue #769: this
            keeps route/body coherence (and any analogous internal-caller
            invariant) inside the service contract instead of the view —
            so a future caller cannot bypass the check by going around the
            HTTP layer.

    Returns:
        Dict with hint text, penalty, order, and cumulative penalty.

    Raises:
        CTFNotFoundError: If participant or hint doesn't exist.
        CTFStateError: If event is not active.
        CTFValidationError: If preceding hints not unlocked, or when
            `expected_challenge_id` is supplied and the hint belongs to
            a different challenge.
    """
    try:
        participant = CTFParticipant.objects.select_related("event").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    try:
        hint = CTFHint.objects.select_related("challenge__event").get(pk=hint_id)
    except CTFHint.DoesNotExist:
        raise CTFNotFoundError(
            f"Hint {hint_id} not found",
            details={"hint_id": str(hint_id)},
        ) from None

    # Issue #769: route/body (and internal-caller) coherence — any caller
    # that thinks it's unlocking a hint for `expected_challenge_id` MUST
    # be refused if the hint actually belongs to a different challenge.
    # Done before the availability check so a probe cannot use the
    # availability error envelope to confirm a hint exists for a different
    # challenge.
    if expected_challenge_id is not None and hint.challenge_id != expected_challenge_id:
        raise CTFValidationError(
            "Hint does not belong to this challenge",
            details={
                "challenge_id": str(expected_challenge_id),
                "hint_id": str(hint_id),
            },
        )

    # Issue #769: enforce the same participant→challenge availability policy
    # as flag submission. Hints leak the solution path; they must not be
    # easier to obtain than flags. Single source of truth lives in
    # ctf.services.challenge.assert_challenge_available_for_participant.
    from ctf.services.challenge import assert_challenge_available_for_participant

    assert_challenge_available_for_participant(participant, hint.challenge)

    # Check if already unlocked (idempotent)
    existing = CTFHintUsage.objects.filter(participant=participant, hint=hint).first()
    if existing:
        total = get_total_hint_penalty(participant_id, hint.challenge_id)
        return {
            "text": hint.text,
            "penalty": hint.penalty,
            "order": hint.order,
            "total_penalty": total,
            "already_unlocked": True,
        }

    # Validate sequential order: all hints with lower order must be unlocked
    preceding_hints = CTFHint.objects.filter(
        challenge=hint.challenge,
        order__lt=hint.order,
    )
    unlocked_ids = set(
        CTFHintUsage.objects.filter(
            participant=participant,
            hint__challenge=hint.challenge,
        ).values_list("hint_id", flat=True)
    )
    for preceding in preceding_hints:
        if preceding.id not in unlocked_ids:
            raise CTFValidationError(
                f"Must unlock hint #{preceding.order} first",
                details={"required_hint_order": preceding.order, "hint_id": str(preceding.id)},
            )

    # Issue #769 race-safety: idempotency was a separate read-then-create,
    # so two concurrent requests could both miss the existing row and one
    # would crash the `unique_active_hint_usage` constraint with an
    # unhandled IntegrityError. Wrap in atomic+IntegrityError handler so
    # the documented idempotent response wins instead.
    #
    # Codex review (cycle 3): a bare `except IntegrityError` would also
    # convert FK violations or future constraint failures into
    # `already_unlocked=True`, returning hint text without persisting a
    # usage row that scoring relies on for the penalty. After catching,
    # re-read for the active usage row; only treat as idempotent when
    # that row actually exists, otherwise re-raise.
    already_unlocked = False
    try:
        with transaction.atomic():
            CTFHintUsage.objects.create(participant=participant, hint=hint)
    except IntegrityError:
        existing_after = CTFHintUsage.objects.filter(participant=participant, hint=hint).first()
        if existing_after is None:
            # Some OTHER constraint failed (FK, unrelated unique, future
            # constraint). The hint usage row we expected is not there;
            # surface the error rather than silently lying to the caller.
            raise
        already_unlocked = True

    total = get_total_hint_penalty(participant_id, hint.challenge_id)

    logger.info(
        "Hint unlocked: participant=%s, hint=%s, challenge=%s, penalty=%d%%",
        participant_id,
        hint_id,
        hint.challenge_id,
        hint.penalty,
    )

    return {
        "text": hint.text,
        "penalty": hint.penalty,
        "order": hint.order,
        "total_penalty": total,
        "already_unlocked": already_unlocked,
    }


def get_unlocked_hints(participant_id: UUID, challenge_id: UUID) -> list[CTFHint]:
    """Get all hints a participant has unlocked for a challenge.

    Args:
        participant_id: UUID of the participant.
        challenge_id: UUID of the challenge.

    Returns:
        List of unlocked CTFHint instances, ordered by reveal order.
    """
    unlocked_ids = CTFHintUsage.objects.filter(
        participant_id=participant_id,
        hint__challenge_id=challenge_id,
    ).values_list("hint_id", flat=True)

    return list(CTFHint.objects.filter(id__in=unlocked_ids).order_by("order", "created_at"))


def get_total_hint_penalty(participant_id: UUID, challenge_id: UUID) -> int:
    """Calculate cumulative hint penalty for a participant on a challenge.

    Args:
        participant_id: UUID of the participant.
        challenge_id: UUID of the challenge.

    Returns:
        Total penalty percentage (sum of unlocked hint penalties, capped at 100).
    """
    total = (
        CTFHintUsage.objects.filter(
            participant_id=participant_id,
            hint__challenge_id=challenge_id,
        )
        .aggregate(total=Sum("hint__penalty"))
        .get("total")
    ) or 0

    return min(total, 100)
