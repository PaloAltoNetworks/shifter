"""CTF challenge tag/topic/next-challenge resolution helpers.

Get-or-create helpers for per-event challenge tags and global topics, plus
the ``next_challenge`` payload resolver shared by the challenge CRUD
submodule (``_challenge_crud``).
"""

from __future__ import annotations

from uuid import UUID

from ctf.exceptions import CTFValidationError
from ctf.models import CTFChallenge, CTFChallengeTag, CTFEvent, CTFTopic


def _resolve_tags(event: CTFEvent, tag_names: list[str]) -> list[CTFChallengeTag]:
    """Get-or-create CTFChallengeTag objects for the given names within an event.

    Tag names are normalized to lowercase to prevent duplicates like "XDR" vs "xdr".
    """
    tags = []
    seen: set[str] = set()
    for name in tag_names:
        name = name.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        tag, _ = CTFChallengeTag.objects.get_or_create(
            event=event,
            name=name,
        )
        tags.append(tag)
    return tags


def _resolve_topics(topic_names: list[str]) -> list[CTFTopic]:
    """Get-or-create CTFTopic objects for the given names.

    Topic names are normalized to lowercase. Topics are global (not event-scoped).
    """
    topics = []
    seen: set[str] = set()
    for name in topic_names:
        name = name.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        topic, _ = CTFTopic.objects.get_or_create(name=name)
        topics.append(topic)
    return topics


def _resolve_next_challenge(
    raw: CTFChallenge | UUID | str | None,
    *,
    event: CTFEvent,
    self_id: UUID | None = None,
) -> CTFChallenge | None:
    """Resolve a `next_challenge` payload value into a CTFChallenge instance.

    Codex review (#765 cycle 6): an earlier change put `next_challenge` in
    the generic mutable-field allowlist, which let raw JSON UUIDs flow
    straight into `CTFChallenge.objects.create(...)` and crash with a 500
    on FK assignment, while internal callers passing a model instance
    bypassed self-reference and cross-event validation. Centralise the
    parse + validation here so every write path through
    `create_challenge` / `update_challenge` enforces the same rules.

    Accepts:
        - `None` / missing → no next challenge (return None)
        - `CTFChallenge` instance → validated and returned
        - UUID / str (UUID-shaped) → loaded and validated
        - anything else → `CTFValidationError`

    `self_id` is the id of the challenge being updated, so we can reject
    self-references. Cross-event references are also rejected.
    """
    if raw is None:
        return None

    if isinstance(raw, CTFChallenge):
        candidate = raw
    else:
        try:
            candidate_id = raw if isinstance(raw, UUID) else UUID(str(raw))
        except (ValueError, TypeError) as e:
            raise CTFValidationError(
                "next_challenge must be a UUID",
                details={"next_challenge": str(raw)},
            ) from e
        try:
            candidate = CTFChallenge.objects.get(pk=candidate_id)
        except CTFChallenge.DoesNotExist:
            raise CTFValidationError(
                f"next_challenge {candidate_id} not found",
                details={"next_challenge": str(candidate_id)},
            ) from None

    if self_id is not None and candidate.pk == self_id:
        raise CTFValidationError(
            "A challenge cannot be its own next_challenge",
            details={"challenge_id": str(self_id)},
        )
    if candidate.event_id != event.pk:
        raise CTFValidationError(
            "next_challenge must belong to the same event",
            details={
                "challenge_event": str(event.pk),
                "next_challenge_event": str(candidate.event_id),
            },
        )
    return candidate
