"""Challenge and event-data import/export (CTF-1101..1104).

Two challenge formats:

- ``shifter`` (``shifter-challenges/v3``): full-fidelity round-trip between
  Shifter instances. Flags travel as per-flag ``CTFFlag`` values (normalized
  plaintext static flag / regex pattern / validator config) in a required,
  non-empty ``flags`` collection, and are re-validated through the canonical
  flag path on import. Earlier formats carried one-way flag hashes (``v2``) or a
  challenge-level ``flag_hash`` (``v1``) and are rejected; there is no
  compatibility adapter.
- ``ctfd``: CTFd's JSON challenge shape (name/value/hints[content,cost]).
  Exports omit flag values and Shifter-only fields; imports accept plaintext
  CTFd flags.

Imports are per-challenge partial-success: bad or duplicate entries are
reported and skipped, valid entries land (CTF-1101).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import transaction

from ctf.enums import ChallengeDifficulty
from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFChallenge, CTFEvent, CTFFlag, CTFHint
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

# v2 (#532) made CTFFlag rows the sole source of flag truth. v3 carries static
# flags as normalized plaintext ``value`` instead of one-way hashes, so a v2
# export can no longer verify anything: the discriminator is advanced (rather
# than silently redefining v2) and earlier exports are rejected outright.
SHIFTER_FORMAT = "shifter-challenges/v3"
_LEGACY_SHIFTER_FORMATS = ("shifter-challenges/v1", "shifter-challenges/v2")

_CHALLENGE_SCALARS = (
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
    "order",
    "visibility",
    "target_instance_name",
    "target_port",
)


def _get_event(event_id: UUID) -> CTFEvent:
    """Load a live event or raise not-found."""
    try:
        return CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(f"Event {event_id} not found", details={"event_id": str(event_id)}) from None


def export_challenges(
    event_id: UUID,
    *,
    fmt: str = "shifter",
    challenge_ids: list[UUID] | None = None,
) -> dict[str, Any]:
    """Export an event's challenges (optionally a subset) as a portable document."""
    event = _get_event(event_id)
    challenges = (
        CTFChallenge.objects.filter(event=event, deleted_at__isnull=True)
        .prefetch_related("flags", "hints", "tags", "topics")
        .order_by("order", "name")
    )
    if challenge_ids:
        challenges = challenges.filter(pk__in=challenge_ids)

    if fmt == "ctfd":
        return {
            "challenges": [
                {
                    "name": c.name,
                    "description": c.description,
                    "category": c.category,
                    "value": c.points,
                    # Not a native CTFd field; the CTFd importer reads it back.
                    "difficulty": c.difficulty,
                    "type": "standard",
                    "state": "visible" if c.visibility == "visible" else "hidden",
                    # CTFd exports do not carry flag entries.
                    "flags": [],
                    "hints": [{"content": h.text, "cost": h.penalty} for h in c.hints.all().order_by("order")],
                    "files": [f.filename for f in c.files.all()],
                    "tags": [t.name for t in c.tags.all()],
                }
                for c in challenges
            ]
        }

    return {
        "format": SHIFTER_FORMAT,
        "event": {"id": str(event.pk), "name": event.name},
        "challenges": [
            {
                **{field: getattr(c, field) for field in _CHALLENGE_SCALARS},
                "flags": [
                    {
                        "flag_type": f.flag_type,
                        "value": f.value,
                        "case_sensitive": f.case_sensitive,
                        "order": f.order,
                        "validator_config": f.validator_config,
                    }
                    for f in c.flags.all().order_by("order")
                ],
                "hints": [
                    {"text": h.text, "penalty": h.penalty, "order": h.order} for h in c.hints.all().order_by("order")
                ],
                "tags": [t.name for t in c.tags.all()],
                "topics": [t.name for t in c.topics.all()],
                "files": [f.filename for f in c.files.all()],
            }
            for c in challenges
        ],
    }


def import_challenges(event_id: UUID, payload: dict[str, Any], *, actor_id: int) -> dict[str, Any]:
    """Import challenges from a shifter or CTFd document (partial-success)."""
    event = _get_event(event_id)
    raw_challenges = payload.get("challenges")
    if not isinstance(raw_challenges, list):
        raise CTFValidationError("Payload has no challenges list", code="CTF_INVALID_IMPORT")
    fmt = payload.get("format")
    if fmt in _LEGACY_SHIFTER_FORMATS:
        raise CTFValidationError(
            f"{fmt} exports are no longer importable: flags are now stored and exported as plaintext "
            f"values ({SHIFTER_FORMAT}). Re-export the event from a current Shifter instance.",
            code="CTF_UNSUPPORTED_FORMAT",
        )
    is_ctfd = fmt != SHIFTER_FORMAT

    existing_names = set(
        CTFChallenge.objects.filter(event=event, deleted_at__isnull=True).values_list("name", flat=True)
    )
    created: list[str] = []
    errors: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_challenges):
        name, error = _import_entry(event, entry, index, existing_names, is_ctfd=is_ctfd, actor_id=actor_id)
        if error is not None:
            errors.append(error)
        else:
            existing_names.add(name)
            created.append(name)

    logger.info("Imported %d challenges into event %s (%d errors)", len(created), safe_log_value(event_id), len(errors))
    return {"created": created, "errors": errors}


def _entry_precheck(entry: object, index: int, existing_names: set[str]) -> tuple[str, dict[str, Any] | None]:
    """Validate shape/name/duplication before attempting a create."""
    if not isinstance(entry, dict):
        return "", {"index": index, "error": "entry must be an object"}
    name = str(entry.get("name") or "").strip()
    error: dict[str, Any] | None = None
    if not name:
        error = {"index": index, "error": "name is required"}
    elif name in existing_names:
        error = {"index": index, "name": name, "error": "already exists in this event"}
    return name, error


def _import_entry(
    event: CTFEvent,
    entry: object,
    index: int,
    existing_names: set[str],
    *,
    is_ctfd: bool,
    actor_id: int,
) -> tuple[str, dict[str, Any] | None]:
    """Import one entry; return ``(name, None)`` on success or ``(name, error)``."""
    name, error = _entry_precheck(entry, index, existing_names)
    if error is None and isinstance(entry, dict):
        try:
            with transaction.atomic():
                if is_ctfd:
                    _create_from_ctfd(event, entry, actor_id=actor_id)
                else:
                    _create_from_shifter(event, entry, actor_id=actor_id)
        except (CTFValidationError, ValueError) as exc:
            logger.info("Challenge import entry %d failed: %s", index, safe_log_value(str(exc)))
            error = {"index": index, "name": name, "error": "Challenge entry failed validation."}
        except Exception:
            logger.exception("Challenge import entry %d failed", index)
            error = {"index": index, "name": name, "error": "Could not import challenge."}
    return name, error


def _create_from_ctfd(event: CTFEvent, entry: dict[str, Any], *, actor_id: int) -> CTFChallenge:
    """Create one challenge from a CTFd-shaped entry (plaintext flags)."""
    from ctf.services.challenge import create_challenge

    first_flag = _first_ctfd_flag(entry)
    data: dict[str, Any] = {
        "name": str(entry.get("name")).strip(),
        # The model requires a description; CTFd packs may omit it.
        "description": str(entry.get("description") or "").strip() or str(entry.get("name")).strip(),
        "category": str(entry.get("category") or "misc").lower(),
        "points": int(entry.get("value") or 0),
        "flag": first_flag,
        "visibility": "visible" if entry.get("state", "visible") == "visible" else "hidden",
    }
    difficulty = _ctfd_difficulty(entry)
    if difficulty is not None:
        data["difficulty"] = difficulty
    challenge = create_challenge(event.pk, data, actor_id=actor_id)
    _create_ctfd_hints(challenge, entry.get("hints") or [])
    return challenge


# CTFd has no native difficulty field; packs carry it as a top-level key or a
# ``difficulty:<level>`` tag. ``insane`` is the common CTFd name for the top tier.
_CTFD_DIFFICULTY_TAG_PREFIX = "difficulty:"
_CTFD_DIFFICULTY_ALIASES = {"insane": ChallengeDifficulty.EXPERT.value}


def _ctfd_difficulty(entry: dict[str, Any]) -> str | None:
    """Return the entry's difficulty, ``None`` when absent, or raise when unsupported."""
    raw = entry.get("difficulty")
    if not raw:
        for tag in entry.get("tags") or []:
            value = tag.get("value") if isinstance(tag, dict) else tag
            if isinstance(value, str) and value.lower().startswith(_CTFD_DIFFICULTY_TAG_PREFIX):
                raw = value[len(_CTFD_DIFFICULTY_TAG_PREFIX) :]
                break
    if not raw:
        return None
    normalized = str(raw).strip().lower()
    normalized = _CTFD_DIFFICULTY_ALIASES.get(normalized, normalized)
    if normalized not in {level.value for level in ChallengeDifficulty}:
        raise CTFValidationError("Unsupported challenge difficulty", code="CTF_INVALID_IMPORT")
    return normalized


def _first_ctfd_flag(entry: dict[str, Any]) -> str:
    """Extract the first usable plaintext flag from a CTFd entry, or raise."""
    flags = [f for f in entry.get("flags") or [] if isinstance(f, (dict, str))]
    first_flag = None
    if flags:
        raw = flags[0]
        first_flag = raw if isinstance(raw, str) else str(raw.get("content") or "")
    if not first_flag:
        raise CTFValidationError("CTFd entry has no flag content", code="CTF_INVALID_IMPORT")
    return first_flag


def _create_ctfd_hints(challenge: CTFChallenge, hints: list[Any]) -> None:
    """Create hints from CTFd ``content``/``cost`` entries."""
    for order, hint in enumerate(hints, start=1):
        if isinstance(hint, dict) and hint.get("content"):
            CTFHint.objects.create(
                challenge=challenge,
                text=str(hint["content"]),
                penalty=int(hint.get("cost") or 0),
                order=order,
            )


def _create_from_shifter(event: CTFEvent, entry: dict[str, Any], *, actor_id: int) -> CTFChallenge:
    """Create one challenge from a shifter-format entry.

    CTFFlag rows are the sole source of flag truth (#532): a valid shifter entry
    must carry at least one flag with a stored value.
    """
    scalars = {field: entry[field] for field in _CHALLENGE_SCALARS if field in entry and entry[field] is not None}
    valid_flags = [f for f in (entry.get("flags") or []) if isinstance(f, dict) and f.get("value")]
    if not valid_flags:
        raise CTFValidationError("Shifter entry has no flags", code="CTF_INVALID_IMPORT")
    from ctf.services.content_hydration import mark_content_hydration_drift

    mark_content_hydration_drift(
        event.pk,
        actor_id=actor_id,
        reason="challenge_imported",
    )
    challenge = CTFChallenge.objects.create(event=event, **scalars)
    _create_shifter_flags(challenge, valid_flags)
    _create_shifter_hints(challenge, entry.get("hints") or [])
    return challenge


def _create_shifter_flags(challenge: CTFChallenge, flags: list[Any]) -> None:
    """Recreate exported flag rows through the canonical flag-value path.

    Imported values are validated exactly like an organizer-added flag: static
    flags are normalized, regex patterns pass the ReDoS policy, and validator
    configs are checked. An invalid flag fails the whole entry.
    """
    from ctf.services.challenge import _flag_value_for_payload, validate_http_flag_config

    for flag in flags:
        if not isinstance(flag, dict) or not flag.get("value"):
            continue
        flag_type = str(flag.get("flag_type") or "static")
        validator_config = flag.get("validator_config") or {}
        if flag_type == "http":
            validator_config = validate_http_flag_config(validator_config)
        stored = _flag_value_for_payload(
            flag_type,
            {"flag": str(flag["value"])} if flag_type in {"static", "regex"} else {},
            validator_config=validator_config,
        )
        CTFFlag.objects.create(
            challenge=challenge,
            flag_type=flag_type,
            value=stored,
            case_sensitive=bool(flag.get("case_sensitive", True)),
            order=int(flag.get("order") or 0),
            validator_config=validator_config,
        )


def _create_shifter_hints(challenge: CTFChallenge, hints: list[Any]) -> None:
    """Recreate exported hint rows."""
    for hint in hints:
        if isinstance(hint, dict) and hint.get("text"):
            CTFHint.objects.create(
                challenge=challenge,
                text=str(hint["text"]),
                penalty=int(hint.get("penalty") or 0),
                order=int(hint.get("order") or 0),
            )


def export_event_results(event_id: UUID) -> dict[str, Any]:
    """Export final rankings, per-participant solves, hint usage, and stats (CTF-1103)."""
    from ctf.models import CTFHintUsage, CTFSubmission
    from ctf.services import get_event_stats
    from ctf.services.scoring import get_scoreboard

    event = _get_event(event_id)
    rankings = [
        {
            "rank": index + 1,
            "participant_id": row["participant_id"],
            "name": row["name"],
            "score": row["score"],
            "solve_count": row["solve_count"],
        }
        for index, row in enumerate(get_scoreboard(event.pk))
    ]
    solves = [
        {
            "participant_id": str(s.participant_id),
            "participant_name": s.participant.name,
            "challenge": s.challenge.name,
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
            "points": s.points_awarded,
        }
        for s in CTFSubmission.objects.filter(participant__event=event, is_correct=True)
        .select_related("participant", "challenge")
        .order_by("submitted_at")
    ]
    hint_usage = [
        {
            "participant_id": str(u.participant_id),
            "participant_name": u.participant.name,
            "challenge": u.hint.challenge.name,
            "hint_order": u.hint.order,
            "used_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in CTFHintUsage.objects.filter(participant__event=event)
        .select_related("participant", "hint__challenge")
        .order_by("created_at")
    ]
    return {
        "event": {"id": str(event.pk), "name": event.name, "status": event.status},
        "rankings": rankings,
        "solves": solves,
        "hint_usage": hint_usage,
        "statistics": get_event_stats(event),
    }


def results_csv(results: dict[str, Any]) -> str:
    """Render the rankings section of a results export as CSV (CTF-1103)."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["rank", "name", "score", "solve_count"])
    for row in results["rankings"]:
        writer.writerow([row["rank"], row["name"], row["score"], row["solve_count"]])
    writer.writerow([])
    writer.writerow(["participant", "challenge", "submitted_at", "points"])
    for solve in results["solves"]:
        writer.writerow([solve["participant_name"], solve["challenge"], solve["submitted_at"], solve["points"]])
    return buffer.getvalue()
