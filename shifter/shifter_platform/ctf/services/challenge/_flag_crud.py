"""CTF flag CRUD: add, update, and remove ``CTFFlag`` records.

Also houses the flag-modifiability policy (``_is_flag_modifiable``), the
payload-to-``flag_hash`` translation shared by add/update
(``_flag_hash_for_payload``), the legacy-flag-hash computation used by
challenge create (``_compute_legacy_flag_hash``), and the live-event edit
guard applied by challenge update (``_reject_non_flag_live_edits``).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFEvent, CTFFlag
from ctf.services.authorization import assert_actor_owns_event as _assert_actor_owns_event
from shared.log_sanitize import safe_log_value

from ._flag_verify import _validate_http_config, _validate_programmable_config, hash_flag

logger = logging.getLogger(__name__)

VALID_FLAG_TYPES = ("static", "regex", "programmable", "http")


def _is_flag_modifiable(event: CTFEvent) -> bool:
    """Return True when flag rows may be added, updated, or removed."""
    return event.is_content_modifiable or event.is_live_flag_repairable


def _flag_hash_for_static_or_regex(flag_type: str, flag_data: dict[str, Any], *, case_sensitive: bool) -> str:
    """Validate and hash a static/regex flag payload, returning the flag_hash value."""
    plaintext_flag = flag_data.get("flag", "").strip()
    if not plaintext_flag:
        raise CTFValidationError(
            "Flag value is required",
            details={"missing_fields": ["flag"]},
        )
    if flag_type == "regex":
        # Reject unsafe patterns at creation time (over-long or
        # uncompilable) so organizers get immediate feedback and the
        # request-worker verifier never stores a ReDoS-prone pattern
        # (issue #1183). The pattern is not echoed back to avoid leaking it.
        from ctf.services.regex_policy import UnsafeRegexError, validate_pattern

        try:
            validate_pattern(plaintext_flag)
        except UnsafeRegexError as e:
            raise CTFValidationError(
                str(e),
                details={"pattern_length": len(plaintext_flag)},
            ) from None
        return plaintext_flag
    return hash_flag(plaintext_flag, case_sensitive=case_sensitive)


def _flag_hash_for_payload(
    flag_type: str,
    flag_data: dict[str, Any],
    *,
    case_sensitive: bool,
    validator_config: dict[str, Any] | None,
) -> str:
    """Validate flag payload fields and return the value to store in flag_hash."""
    if flag_type not in VALID_FLAG_TYPES:
        raise CTFValidationError(
            f"Invalid flag_type: {flag_type}",
            details={"flag_type": flag_type},
        )

    if flag_type in ("static", "regex"):
        return _flag_hash_for_static_or_regex(flag_type, flag_data, case_sensitive=case_sensitive)

    if flag_type == "programmable":
        _validate_programmable_config(validator_config)
        return "programmable"

    _validate_http_config(validator_config)
    return "http"


def _reject_non_flag_live_edits(challenge: CTFChallenge, challenge_data: dict[str, Any]) -> None:
    """Refuse broad challenge edits during ACTIVE/PAUSED live events."""
    if challenge.event.is_content_modifiable:
        return
    if not challenge.event.is_live_flag_repairable:
        raise CTFStateError(
            f"Cannot modify challenge in event with status {challenge.event.status}",
            details={
                "challenge_id": str(challenge.pk),
                "event_status": challenge.event.status,
            },
        )
    allowed_keys = {"flag", "flags", "visibility"}
    if not allowed_keys.intersection(challenge_data.keys()):
        raise CTFStateError(
            f"Only flag fields may be changed during a live event (status {challenge.event.status})",
            details={
                "challenge_id": str(challenge.pk),
                "event_status": challenge.event.status,
            },
        )
    extra_keys = set(challenge_data.keys()) - allowed_keys
    if extra_keys:
        raise CTFStateError(
            f"Only flag fields may be changed during a live event (status {challenge.event.status})",
            details={
                "challenge_id": str(challenge.pk),
                "event_status": challenge.event.status,
                "disallowed_fields": sorted(extra_keys),
            },
        )


def add_flag(
    challenge_id: UUID,
    flag_data: dict[str, Any],
    *,
    actor_id: int,
) -> CTFFlag:
    """Add a flag to a challenge.

    Args:
        challenge_id: UUID of the challenge.
        flag_data: Dictionary with keys:
            - flag (str): plaintext flag value (required for static/regex types)
            - flag_type (str): "static", "regex", "programmable", or "http"
            - case_sensitive (bool): default True
            - order (int): default 0
            - validator_config (dict): configuration for programmable/http types
        actor_id: User pk of the caller. Required (issue #765 DiD).

    Returns:
        The created CTFFlag instance.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
        CTFPermissionError: If actor does not own the challenge's event.
        CTFStateError: If challenge's event is not modifiable.
        CTFValidationError: If flag data is invalid.
    """
    try:
        challenge = CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    _assert_actor_owns_event(actor_id, challenge.event)

    if not _is_flag_modifiable(challenge.event):
        raise CTFStateError(
            f"Cannot modify challenge in event with status {challenge.event.status}",
            details={"challenge_id": str(challenge_id), "event_status": challenge.event.status},
        )

    flag_type = flag_data.get("flag_type", "static")
    case_sensitive = flag_data.get("case_sensitive", True)
    order = flag_data.get("order", 0)
    validator_config = flag_data.get("validator_config")
    stored_value = _flag_hash_for_payload(
        flag_type,
        flag_data,
        case_sensitive=case_sensitive,
        validator_config=validator_config,
    )

    flag_obj = CTFFlag.objects.create(
        challenge=challenge,
        flag_hash=stored_value,
        flag_type=flag_type,
        case_sensitive=case_sensitive,
        order=order,
        validator_config=validator_config,
    )

    if challenge.event.is_live_flag_repairable:
        from ctf.services.audit import audit_live_flag_repair

        audit_live_flag_repair(
            actor_id=actor_id,
            challenge_id=challenge.pk,
            flag_id=flag_obj.pk,
            event_id=challenge.event_id,
            action="add",
        )

    logger.info("Added flag %s to challenge %s", flag_obj.id, safe_log_value(challenge_id))
    return flag_obj


def update_flag(
    flag_id: UUID,
    flag_data: dict[str, Any],
    *,
    actor_id: int,
) -> CTFFlag:
    """Update an existing challenge flag (including live-event repairs).

    Args:
        flag_id: UUID of the flag to update.
        flag_data: Same shape as ``add_flag`` flag_data (flag, flag_type, etc.).
        actor_id: User pk of the caller.

    Returns:
        The updated CTFFlag instance.
    """
    try:
        flag_obj = CTFFlag.objects.select_related("challenge__event").get(pk=flag_id)
    except CTFFlag.DoesNotExist:
        raise CTFNotFoundError(
            f"Flag {flag_id} not found",
            details={"flag_id": str(flag_id)},
        ) from None

    challenge = flag_obj.challenge
    _assert_actor_owns_event(actor_id, challenge.event)

    if not _is_flag_modifiable(challenge.event):
        raise CTFStateError(
            f"Cannot modify challenge in event with status {challenge.event.status}",
            details={"flag_id": str(flag_id), "event_status": challenge.event.status},
        )

    flag_type = flag_data.get("flag_type", flag_obj.flag_type)
    case_sensitive = flag_data.get("case_sensitive", flag_obj.case_sensitive)
    order = flag_data.get("order", flag_obj.order)
    validator_config = flag_data.get("validator_config", flag_obj.validator_config)
    stored_value = _flag_hash_for_payload(
        flag_type,
        flag_data,
        case_sensitive=case_sensitive,
        validator_config=validator_config,
    )

    flag_obj.flag_hash = stored_value
    flag_obj.flag_type = flag_type
    flag_obj.case_sensitive = case_sensitive
    flag_obj.order = order
    flag_obj.validator_config = validator_config
    flag_obj.save(
        update_fields=[
            "flag_hash",
            "flag_type",
            "case_sensitive",
            "order",
            "validator_config",
            "updated_at",
        ]
    )

    if challenge.event.is_live_flag_repairable:
        from ctf.services.audit import audit_live_flag_repair

        audit_live_flag_repair(
            actor_id=actor_id,
            challenge_id=challenge.pk,
            flag_id=flag_obj.pk,
            event_id=challenge.event_id,
            action="update",
        )

    logger.info("Updated flag %s on challenge %s", flag_obj.id, challenge.pk)
    return flag_obj


def remove_flag(flag_id: UUID, *, actor_id: int) -> None:
    """Remove a flag from a challenge.

    Args:
        flag_id: UUID of the flag to remove.
        actor_id: User pk of the caller. Required (issue #765 DiD).

    Raises:
        CTFNotFoundError: If flag doesn't exist.
        CTFPermissionError: If actor does not own the challenge's event.
        CTFStateError: If challenge's event is not modifiable.
    """
    try:
        flag_obj = CTFFlag.objects.select_related("challenge__event").get(pk=flag_id)
    except CTFFlag.DoesNotExist:
        raise CTFNotFoundError(
            f"Flag {flag_id} not found",
            details={"flag_id": str(flag_id)},
        ) from None

    _assert_actor_owns_event(actor_id, flag_obj.challenge.event)

    if not _is_flag_modifiable(flag_obj.challenge.event):
        raise CTFStateError(
            f"Cannot modify challenge in event with status {flag_obj.challenge.event.status}",
            details={"flag_id": str(flag_id), "event_status": flag_obj.challenge.event.status},
        )

    if flag_obj.challenge.event.is_live_flag_repairable:
        from ctf.services.audit import audit_live_flag_repair

        audit_live_flag_repair(
            actor_id=actor_id,
            challenge_id=flag_obj.challenge_id,
            flag_id=flag_obj.pk,
            event_id=flag_obj.challenge.event_id,
            action="remove",
        )

    flag_obj.delete(soft=True)
    logger.info("Removed flag %s", safe_log_value(flag_id))


def _compute_legacy_flag_hash(data: dict[str, Any], flags_list: list | None) -> None:
    """Populate `data['flag_hash']` from either `data['flag']` or the first
    entry in `flags_list`. Mutates `data` in place. Caller has already
    validated that one of them is present.
    """
    if "flag" in data:
        plaintext_flag = data.pop("flag")
        data["flag_hash"] = hash_flag(plaintext_flag)
        return
    if not flags_list:
        return
    first_flag = flags_list[0]
    first_type = first_flag.get("flag_type", "static")
    if first_type == "static":
        data["flag_hash"] = hash_flag(
            first_flag["flag"],
            case_sensitive=first_flag.get("case_sensitive", True),
        )
    elif first_type in ("programmable", "http"):
        data["flag_hash"] = first_type
    else:
        data["flag_hash"] = "multi-flag"
