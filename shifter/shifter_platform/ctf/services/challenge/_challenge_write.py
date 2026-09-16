"""CTF challenge write path: create, update, and soft-delete.

``add_flag`` is resolved through the ``ctf.services.challenge`` package at
call time (``from ctf.services import challenge as _c``) rather than
imported directly, so ``unittest.mock.patch("ctf.services.challenge.add_flag")``
keeps intercepting the two internal call sites below (``_apply_challenge_m2m``
/ ``_apply_optional_challenge_associations``) after the package split -- see
the package ``__init__`` docstring for the full rationale.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ctf.enums import EventCapability
from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFChallengePrerequisite, CTFEvent
from ctf.services.authorization import assert_event_capability as _assert_event_capability
from shared.log_sanitize import safe_log_value

from ._challenge_release import _sync_release_task
from ._flag_crud import _reject_non_flag_live_edits
from ._resolve import _resolve_next_challenge, _resolve_tags, _resolve_topics

logger = logging.getLogger(__name__)

# Fields that organizers may set when creating or updating challenges.
# All other fields (event, id, timestamps, etc.) are controlled internally
# and must not be overwritten by user input. Flag material never lives on the
# challenge row -- it is persisted only as CTFFlag records (#532).
_CHALLENGE_MUTABLE_FIELDS = frozenset(
    {
        "name",
        "description",
        "category",
        "points",
        "difficulty",
        "flag_format",
        "solution",
        "max_attempts",
        "minimum_points",
        "decay_function",
        "decay_solve_count",
        "release_time",
        "order",
        "visibility",
        "target_instance_name",
        "target_port",
    }
)


def _apply_challenge_m2m(
    challenge: CTFChallenge,
    event: CTFEvent,
    *,
    tag_names: list[str] | None,
    topic_names: list[str] | None,
    flags_list: list[dict[str, Any]] | None,
    actor_id: int,
) -> None:
    """Apply tags, topics, and per-challenge flag records after a challenge
    has been created/updated. Caller is responsible for the surrounding
    `transaction.atomic()`.
    """
    if flags_list:
        from ctf.services import challenge as _c

        for i, fd in enumerate(flags_list):
            _c.add_flag(challenge.id, {**fd, "order": fd.get("order", i)}, actor_id=actor_id)
    if tag_names is not None:
        challenge.tags.set(_resolve_tags(event, tag_names))
    if topic_names is not None:
        challenge.topics.set(_resolve_topics(topic_names))


def _normalize_flag_write(data: dict[str, Any], flags_list: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Normalize the plaintext ``flag`` input alias into the canonical ``flags``
    list. ``CTFFlag`` is the sole source of flag truth (#532), so a single
    ``flag`` becomes exactly one static flag entry -- it is never persisted on
    the challenge row.

    Pops ``flag`` from ``data`` and returns the flags list to apply:

    - Rejects a payload that supplies both ``flag`` and ``flags``.
    - Rejects an explicitly empty ``flags`` list.
    - A nonblank ``flag`` yields a one-entry static flags list.
    - A blank/absent ``flag`` with no ``flags`` returns ``None`` (on update this
      means "leave the current flag set unchanged").
    """
    has_flag = "flag" in data
    plaintext_flag = str(data.pop("flag", "") or "").strip()
    if has_flag and flags_list is not None:
        raise CTFValidationError(
            "Provide either 'flag' or 'flags', not both",
            details={"conflicting_fields": ["flag", "flags"]},
        )
    if flags_list is not None and len(flags_list) == 0:
        raise CTFValidationError(
            "flags cannot be empty",
            details={"missing_fields": ["flags"]},
        )
    if plaintext_flag:
        return [{"flag": plaintext_flag, "flag_type": "static"}]
    return flags_list


def _build_challenge_safe_data(data: dict[str, Any]) -> dict[str, Any]:
    """Filter `data` to allowed challenge fields, plus the pre-resolved
    `next_challenge` instance. `next_challenge` is kept out of the generic
    allowlist so unvalidated JSON FK input cannot crash FK assignment.
    """
    safe_data = {k: v for k, v in data.items() if k in _CHALLENGE_MUTABLE_FIELDS}
    if "next_challenge" in data:
        safe_data["next_challenge"] = data["next_challenge"]
    return safe_data


def create_challenge(
    event_id: UUID,
    challenge_data: dict[str, Any],
    *,
    actor_id: int,
    source_id: str = "",
) -> CTFChallenge:
    """Create a new challenge.

    Args:
        event_id: UUID of the event to add the challenge to.
        challenge_data: Dictionary containing challenge fields.
            Must include 'flag' (plaintext) which will be hashed.
            May include 'flags' (list of dicts) for multi-flag challenges.
        actor_id: User pk of the caller. Required (issue #765 DiD): the
            service refuses unless `actor_id == event.created_by_id`, even
            when the view-layer ownership check has already passed. Pass
            `request.user.pk` from view callers.
        source_id: Optional stable identity supplied by trusted content
            hydration. Ordinary challenge payloads cannot set this field.

    Returns:
        The created CTFChallenge instance.

    Raises:
        CTFNotFoundError: If event doesn't exist.
        CTFPermissionError: If actor does not own the event.
        CTFStateError: If event is not modifiable.
        CTFValidationError: If challenge data is invalid.
    """
    logger.info("Creating challenge for event %s", safe_log_value(event_id))

    # Get and validate event
    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    _assert_event_capability(actor_id, event, EventCapability.CHALLENGES)

    if not event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot add challenges to event in {event.status} state",
            details={"event_id": str(event_id), "status": event.status},
        )

    data = challenge_data.copy()
    flags_list = data.pop("flags", None)
    tag_names = data.pop("tags", None)
    topic_names = data.pop("topics", None)

    # Resolve next_challenge before allowlist filtering: codex review
    # cycle 6 — raw FK passthrough caused 500s and skipped same-event /
    # self-reference checks. Helper raises CTFValidationError on bad input.
    if "next_challenge" in data:
        data["next_challenge"] = _resolve_next_challenge(data["next_challenge"], event=event)

    # CTFFlag is the sole source of flag truth (#532): normalize the plaintext
    # `flag` alias into one static CTFFlag. A challenge must have at least one.
    flags_list = _normalize_flag_write(data, flags_list)
    if not flags_list:
        raise CTFValidationError(
            "Flag is required",
            details={"missing_fields": ["flag"]},
        )

    safe_data = _build_challenge_safe_data(data)
    safe_data["source_id"] = source_id

    with transaction.atomic():
        from ctf.services.content_hydration import mark_content_hydration_drift

        mark_content_hydration_drift(event.pk, actor_id=actor_id, reason="challenge_created")
        challenge = CTFChallenge.objects.create(event=event, **safe_data)
        _apply_challenge_m2m(
            challenge,
            event,
            tag_names=tag_names,
            topic_names=topic_names,
            flags_list=flags_list,
            actor_id=actor_id,
        )
        logger.info(
            "Created challenge %s for event %s: %s",
            challenge.id,
            safe_log_value(event_id),
            safe_log_value(challenge.name),
        )

    _sync_release_task(challenge)

    return challenge


def _build_safe_update_payload(data: dict[str, Any], challenge: CTFChallenge) -> dict[str, Any]:
    """Resolve `next_challenge`, then filter to allowed fields.

    Mass-assignment safety: only `_CHALLENGE_MUTABLE_FIELDS` is allowed, plus an
    explicit pass-through for `next_challenge` (kept out of the generic allowlist
    so JSON callers can't crash FK assignment). Flag material is handled
    separately via CTFFlag replacement, not on the challenge row (#532).
    """
    if "next_challenge" in data:
        data["next_challenge"] = _resolve_next_challenge(
            data["next_challenge"],
            event=challenge.event,
            self_id=challenge.pk,
        )

    safe_data = {k: v for k, v in data.items() if k in _CHALLENGE_MUTABLE_FIELDS}
    if "next_challenge" in data:
        safe_data["next_challenge"] = data["next_challenge"]
    return safe_data


def _apply_optional_challenge_associations(
    challenge: CTFChallenge,
    flags_list: list[dict[str, Any]] | None,
    tag_names: list[str] | None,
    topic_names: list[str] | None,
    actor_id: int,
) -> None:
    """Apply optional flag/tag/topic updates inside the existing transaction."""
    if flags_list is not None:
        from ctf.services import challenge as _c

        challenge.flags.all().delete()
        for i, fd in enumerate(flags_list):
            _c.add_flag(challenge.id, {**fd, "order": fd.get("order", i)}, actor_id=actor_id)
    if tag_names is not None:
        challenge.tags.set(_resolve_tags(challenge.event, tag_names))
    if topic_names is not None:
        challenge.topics.set(_resolve_topics(topic_names))


def update_challenge(challenge_id: UUID, challenge_data: dict[str, Any], *, actor_id: int) -> CTFChallenge:
    """Update an existing challenge.

    Args:
        challenge_id: UUID of the challenge to update.
        challenge_data: Dictionary containing fields to update.
            If 'flag' is provided, it will be re-hashed.
            If 'flags' is provided, all existing CTFFlag records are replaced.
        actor_id: User pk of the caller. Required (issue #765 DiD): the
            service refuses unless `actor_id == challenge.event.created_by_id`.

    Returns:
        The updated CTFChallenge instance.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
        CTFPermissionError: If actor does not own the event.
        CTFStateError: If challenge's event is not modifiable.
    """
    logger.info("Updating challenge %s", safe_log_value(challenge_id))

    try:
        challenge = CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    _assert_event_capability(actor_id, challenge.event, EventCapability.CHALLENGES)

    _reject_non_flag_live_edits(challenge, challenge_data)

    data = challenge_data.copy()
    flags_list = data.pop("flags", None)
    tag_names = data.pop("tags", None)
    topic_names = data.pop("topics", None)

    # CTFFlag is the sole source of flag truth (#532): a single plaintext `flag`
    # atomically replaces the flag set with one static CTFFlag; an absent/blank
    # `flag` (and no `flags`) leaves the current flag set unchanged.
    flags_list = _normalize_flag_write(data, flags_list)

    safe_data = _build_safe_update_payload(data, challenge)

    with transaction.atomic():
        from ctf.services.content_hydration import mark_content_hydration_drift

        mark_content_hydration_drift(
            challenge.event_id,
            actor_id=actor_id,
            reason="challenge_updated",
            allow_live_repair=challenge.event.is_live_flag_repairable,
        )
        for key, value in safe_data.items():
            setattr(challenge, key, value)
        challenge.save()
        _apply_optional_challenge_associations(challenge, flags_list, tag_names, topic_names, actor_id)
        logger.info("Updated challenge %s", safe_log_value(challenge_id))

        if challenge.event.is_live_flag_repairable and ("flag" in challenge_data or flags_list is not None):
            from ctf.services.audit import audit_live_flag_repair

            audit_live_flag_repair(
                actor_id=actor_id,
                challenge_id=challenge.pk,
                flag_id=challenge.flags.order_by("order").values_list("pk", flat=True).first() or challenge.pk,
                event_id=challenge.event_id,
                action="update_legacy_flag",
            )

    _sync_release_task(challenge)

    return challenge


def delete_challenge(challenge_id: UUID, *, actor_id: int) -> None:
    """Soft-delete a challenge.

    Args:
        challenge_id: UUID of the challenge to delete.
        actor_id: User pk of the caller. Required (issue #765 DiD): the
            service refuses unless `actor_id == challenge.event.created_by_id`.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
        CTFPermissionError: If actor does not own the event.
        CTFStateError: If challenge's event is not modifiable.
    """
    logger.info("Deleting challenge %s", safe_log_value(challenge_id))

    try:
        challenge = CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    _assert_event_capability(actor_id, challenge.event, EventCapability.CHALLENGES)

    if not challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot delete challenge in event with status {challenge.event.status}",
            details={
                "challenge_id": str(challenge_id),
                "event_status": challenge.event.status,
            },
        )

    with transaction.atomic():
        from ctf.services.content_hydration import mark_content_hydration_drift

        mark_content_hydration_drift(
            challenge.event_id,
            actor_id=actor_id,
            reason="challenge_deleted",
        )
        # Soft-delete prerequisite links where this challenge is required
        CTFChallengePrerequisite.objects.filter(required_challenge=challenge).update(deleted_at=timezone.now())
        challenge.delete(soft=True)
    logger.info("Deleted challenge %s", safe_log_value(challenge_id))
