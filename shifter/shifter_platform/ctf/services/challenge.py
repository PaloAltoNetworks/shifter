"""CTF Challenge service.

Provides business logic for challenge management and flag operations.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from collections import deque
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFChallengePrerequisite, CTFEvent, CTFFlag

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Fields that organizers may set when creating or updating challenges.
# All other fields (event, flag_hash, id, timestamps, etc.) are
# controlled internally and must not be overwritten by user input.
_CHALLENGE_MUTABLE_FIELDS = frozenset(
    {
        "name",
        "description",
        "category",
        "points",
        "difficulty",
        "flag_format",
        "hint",
        "hint_penalty",
        "max_attempts",
        "release_time",
        "order",
        "visibility",
    }
)

# Use bcrypt for flag hashing (secure and includes salt)
try:
    import bcrypt

    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    logger.warning("bcrypt not available, using SHA256 for flag hashing (less secure)")


def hash_flag(flag: str, case_sensitive: bool = True) -> str:
    """Hash a flag for secure storage.

    Uses bcrypt if available, falls back to PBKDF2-SHA256.

    Args:
        flag: The plaintext flag value.
        case_sensitive: If False, normalize to lowercase before hashing.

    Returns:
        Hashed flag string for storage.
    """
    value = flag if case_sensitive else flag.lower()
    if BCRYPT_AVAILABLE:
        return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    else:
        salt = secrets.token_hex(16)
        hash_value = hashlib.pbkdf2_hmac(
            "sha256", value.encode("utf-8"), salt.encode("utf-8"), iterations=600_000
        ).hex()
        return f"pbkdf2:{salt}:{hash_value}"


def _verify_hash(submitted_flag: str, stored_hash: str, context_id: UUID) -> bool:
    """Verify a submitted flag against a stored hash.

    Args:
        submitted_flag: The flag value to check (already case-normalized if needed).
        stored_hash: The stored hash to compare against.
        context_id: ID for logging (challenge or flag ID).

    Returns:
        True if the flag matches the hash.
    """
    if BCRYPT_AVAILABLE and stored_hash.startswith("$2"):
        try:
            return bcrypt.checkpw(
                submitted_flag.encode("utf-8"),
                stored_hash.encode("utf-8"),
            )
        except Exception as e:
            logger.error("Flag verification error for %s: %s", context_id, e)
            return False
    elif stored_hash.startswith("pbkdf2:"):
        parts = stored_hash.split(":", 2)
        if len(parts) != 3:
            logger.error("Invalid hash format for %s", context_id)
            return False
        _, salt, expected_hash = parts
        actual_hash = hashlib.pbkdf2_hmac(
            "sha256", submitted_flag.encode("utf-8"), salt.encode("utf-8"), iterations=600_000
        ).hex()
        return secrets.compare_digest(actual_hash, expected_hash)
    elif stored_hash.startswith("sha256:"):
        # Legacy format: single-round salted SHA-256.  Kept for backward
        # compatibility with hashes created before PBKDF2 migration.  New
        # flags always use bcrypt or PBKDF2 (see hash_flag()).
        parts = stored_hash.split(":", 2)
        if len(parts) != 3:
            logger.error("Invalid hash format for %s", context_id)
            return False
        _, salt, expected_hash = parts
        actual_hash = hashlib.sha256(  # NOSONAR — legacy compat, not for new hashes
            f"{salt}:{submitted_flag}".encode()
        ).hexdigest()
        return secrets.compare_digest(actual_hash, expected_hash)
    else:
        logger.error("Unknown hash format for %s", context_id)
        return False


def verify_single_flag(flag_obj: CTFFlag, submitted_flag: str) -> bool:
    """Verify a submitted flag against a single CTFFlag record.

    Args:
        flag_obj: The CTFFlag instance to verify against.
        submitted_flag: The flag submitted by the participant.

    Returns:
        True if the flag matches.
    """
    if flag_obj.flag_type == "regex":
        # Regex flags: pattern stored as plaintext in flag_hash
        regex_flags = 0 if flag_obj.case_sensitive else re.IGNORECASE
        try:
            return bool(re.fullmatch(flag_obj.flag_hash, submitted_flag, flags=regex_flags))
        except re.error as e:
            logger.error("Invalid regex pattern for flag %s: %s", flag_obj.id, e)
            return False
    elif flag_obj.flag_type in ("programmable", "http"):
        from ctf.validators import get_validator, validate_http

        config = flag_obj.validator_config or {}
        if flag_obj.flag_type == "programmable":
            validator_name = config.get("validator_name", "")
            validator_func = get_validator(validator_name)
            if validator_func is None:
                logger.error("Unknown validator %r for flag %s", validator_name, flag_obj.id)
                return False
            try:
                return validator_func(submitted_flag, config.get("params", {}))
            except Exception as e:
                logger.error("Validator %r error for flag %s: %s", validator_name, flag_obj.id, e)
                return False
        else:  # http
            try:
                return validate_http(submitted_flag, config, flag_obj.challenge_id)
            except Exception as e:
                logger.error("HTTP validator error for flag %s: %s", flag_obj.id, e)
                return False
    else:
        # Static flags: hashed comparison
        value = submitted_flag if flag_obj.case_sensitive else submitted_flag.lower()
        return _verify_hash(value, flag_obj.flag_hash, flag_obj.id)


def verify_flag(challenge: CTFChallenge, submitted_flag: str) -> bool:
    """Verify a submitted flag against a challenge.

    Checks CTFFlag records first. If none exist, falls back to the legacy
    flag_hash field on the challenge for backward compatibility.

    Args:
        challenge: The challenge to verify against.
        submitted_flag: The flag submitted by the participant.

    Returns:
        True if the flag is correct, False otherwise.
    """
    # Check CTFFlag records first (single query)
    flags = list(challenge.flags.all())
    if flags:
        return any(verify_single_flag(flag_obj, submitted_flag) for flag_obj in flags)

    # Backward compat: fall back to challenge.flag_hash
    return _verify_hash(submitted_flag, challenge.flag_hash, challenge.id)


def _validate_programmable_config(validator_config: dict[str, Any] | None) -> None:
    """Validate configuration for a programmable flag.

    Args:
        validator_config: The validator configuration dict.

    Raises:
        CTFValidationError: If configuration is invalid.
    """
    from ctf.validators import get_validator

    if validator_config is None or not isinstance(validator_config, dict):
        raise CTFValidationError(
            "validator_config is required for programmable flags",
            details={"missing_fields": ["validator_config"]},
        )
    validator_name = validator_config.get("validator_name", "")
    if not validator_name:
        raise CTFValidationError(
            "validator_config.validator_name is required",
            details={"missing_fields": ["validator_config.validator_name"]},
        )
    if get_validator(validator_name) is None:
        raise CTFValidationError(
            f"Unknown validator: {validator_name}",
            details={"validator_name": validator_name},
        )


def _validate_http_config(validator_config: dict[str, Any] | None) -> None:
    """Validate configuration for an HTTP flag.

    Args:
        validator_config: The validator configuration dict.

    Raises:
        CTFValidationError: If configuration is invalid.
    """
    if validator_config is None or not isinstance(validator_config, dict):
        raise CTFValidationError(
            "validator_config is required for HTTP flags",
            details={"missing_fields": ["validator_config"]},
        )
    url = validator_config.get("url", "")
    if not url:
        raise CTFValidationError(
            "validator_config.url is required",
            details={"missing_fields": ["validator_config.url"]},
        )
    if not url.startswith("https://"):
        raise CTFValidationError(
            "validator_config.url must use HTTPS",
            details={"url": url},
        )

    from ctf.validators import is_blocked_url

    if is_blocked_url(url):
        raise CTFValidationError(
            "validator_config.url must not target private or reserved addresses",
            details={"url": url},
        )

    timeout = validator_config.get("timeout")
    if timeout is not None and (not isinstance(timeout, int) or timeout < 1 or timeout > 30):
        raise CTFValidationError(
            "validator_config.timeout must be an integer between 1 and 30",
            details={"timeout": timeout},
        )


VALID_FLAG_TYPES = ("static", "regex", "programmable", "http")


def add_flag(
    challenge_id: UUID,
    flag_data: dict[str, Any],
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

    Returns:
        The created CTFFlag instance.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
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

    if not challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot modify challenge in event with status {challenge.event.status}",
            details={"challenge_id": str(challenge_id), "event_status": challenge.event.status},
        )

    flag_type = flag_data.get("flag_type", "static")
    case_sensitive = flag_data.get("case_sensitive", True)
    order = flag_data.get("order", 0)
    validator_config = flag_data.get("validator_config")

    if flag_type not in VALID_FLAG_TYPES:
        raise CTFValidationError(
            f"Invalid flag_type: {flag_type}",
            details={"flag_type": flag_type},
        )

    if flag_type in ("static", "regex"):
        plaintext_flag = flag_data.get("flag", "").strip()
        if not plaintext_flag:
            raise CTFValidationError(
                "Flag value is required",
                details={"missing_fields": ["flag"]},
            )

        if flag_type == "regex":
            # Validate regex pattern
            try:
                re.compile(plaintext_flag)
            except re.error as e:
                raise CTFValidationError(
                    f"Invalid regex pattern: {e}",
                    details={"pattern": plaintext_flag},
                ) from None
            # Regex patterns stored as plaintext (can't hash a regex)
            stored_value = plaintext_flag
        else:
            # Static flags: hash for secure storage
            stored_value = hash_flag(plaintext_flag, case_sensitive=case_sensitive)
    elif flag_type == "programmable":
        _validate_programmable_config(validator_config)
        stored_value = "programmable"
    else:  # http
        _validate_http_config(validator_config)
        stored_value = "http"

    flag_obj = CTFFlag.objects.create(
        challenge=challenge,
        flag_hash=stored_value,
        flag_type=flag_type,
        case_sensitive=case_sensitive,
        order=order,
        validator_config=validator_config,
    )

    logger.info("Added flag %s to challenge %s", flag_obj.id, challenge_id)
    return flag_obj


def remove_flag(flag_id: UUID) -> None:
    """Remove a flag from a challenge.

    Args:
        flag_id: UUID of the flag to remove.

    Raises:
        CTFNotFoundError: If flag doesn't exist.
        CTFStateError: If challenge's event is not modifiable.
    """
    try:
        flag_obj = CTFFlag.objects.select_related("challenge__event").get(pk=flag_id)
    except CTFFlag.DoesNotExist:
        raise CTFNotFoundError(
            f"Flag {flag_id} not found",
            details={"flag_id": str(flag_id)},
        ) from None

    if not flag_obj.challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot modify challenge in event with status {flag_obj.challenge.event.status}",
            details={"flag_id": str(flag_id), "event_status": flag_obj.challenge.event.status},
        )

    flag_obj.delete(soft=True)
    logger.info("Removed flag %s", flag_id)


def create_challenge(event_id: UUID, challenge_data: dict[str, Any]) -> CTFChallenge:
    """Create a new challenge.

    Args:
        event_id: UUID of the event to add the challenge to.
        challenge_data: Dictionary containing challenge fields.
            Must include 'flag' (plaintext) which will be hashed.
            May include 'flags' (list of dicts) for multi-flag challenges.

    Returns:
        The created CTFChallenge instance.

    Raises:
        CTFNotFoundError: If event doesn't exist.
        CTFStateError: If event is not modifiable.
        CTFValidationError: If challenge data is invalid.
    """
    logger.info("Creating challenge for event %s", event_id)

    # Get and validate event
    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    if not event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot add challenges to event in {event.status} state",
            details={"event_id": str(event_id), "status": event.status},
        )

    data = challenge_data.copy()
    flags_list = data.pop("flags", None)

    # Validate: need either 'flag' or 'flags'
    if "flag" not in data and not flags_list:
        raise CTFValidationError(
            "Flag is required",
            details={"missing_fields": ["flag"]},
        )

    # Extract flag and hash it for the legacy field
    if "flag" in data:
        plaintext_flag = data.pop("flag")
        data["flag_hash"] = hash_flag(plaintext_flag)
    elif flags_list:
        # Use first static flag for legacy field, or sentinel for other types
        first_flag = flags_list[0]
        first_type = first_flag.get("flag_type", "static")
        if first_type == "static":
            data["flag_hash"] = hash_flag(
                first_flag["flag"],
                case_sensitive=first_flag.get("case_sensitive", True),
            )
        else:
            data["flag_hash"] = first_type if first_type in ("programmable", "http") else "multi-flag"

    # Filter to allowed fields only — prevent mass assignment of event,
    # flag_hash (set internally above), id, timestamps, etc.
    safe_data = {k: v for k, v in data.items() if k in _CHALLENGE_MUTABLE_FIELDS}
    if "flag_hash" in data:
        safe_data["flag_hash"] = data["flag_hash"]

    with transaction.atomic():
        challenge = CTFChallenge.objects.create(
            event=event,
            **safe_data,
        )

        # Create CTFFlag records if flags list provided
        if flags_list:
            for i, fd in enumerate(flags_list):
                add_flag(challenge.id, {**fd, "order": fd.get("order", i)})

        logger.info(
            "Created challenge %s for event %s: %s",
            challenge.id,
            event_id,
            challenge.name,
        )

    return challenge


def update_challenge(challenge_id: UUID, challenge_data: dict[str, Any]) -> CTFChallenge:
    """Update an existing challenge.

    Args:
        challenge_id: UUID of the challenge to update.
        challenge_data: Dictionary containing fields to update.
            If 'flag' is provided, it will be re-hashed.
            If 'flags' is provided, all existing CTFFlag records are replaced.

    Returns:
        The updated CTFChallenge instance.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
        CTFStateError: If challenge's event is not modifiable.
    """
    logger.info("Updating challenge %s", challenge_id)

    try:
        challenge = CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    if not challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot modify challenge in event with status {challenge.event.status}",
            details={
                "challenge_id": str(challenge_id),
                "event_status": challenge.event.status,
            },
        )

    data = challenge_data.copy()
    flags_list = data.pop("flags", None)

    # Hash new flag if provided
    if "flag" in data:
        plaintext_flag = data.pop("flag")
        data["flag_hash"] = hash_flag(plaintext_flag)

    # Filter to allowed fields only — prevent mass assignment of event,
    # id, timestamps, etc.
    safe_data = {k: v for k, v in data.items() if k in _CHALLENGE_MUTABLE_FIELDS}
    if "flag_hash" in data:
        safe_data["flag_hash"] = data["flag_hash"]

    with transaction.atomic():
        for key, value in safe_data.items():
            setattr(challenge, key, value)
        challenge.save()

        # Replace flags if provided
        if flags_list is not None:
            challenge.flags.all().delete()
            for i, fd in enumerate(flags_list):
                add_flag(challenge.id, {**fd, "order": fd.get("order", i)})

        logger.info("Updated challenge %s", challenge_id)

    return challenge


def delete_challenge(challenge_id: UUID) -> None:
    """Soft-delete a challenge.

    Args:
        challenge_id: UUID of the challenge to delete.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
        CTFStateError: If challenge's event is not modifiable.
    """
    logger.info("Deleting challenge %s", challenge_id)

    try:
        challenge = CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None

    if not challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot delete challenge in event with status {challenge.event.status}",
            details={
                "challenge_id": str(challenge_id),
                "event_status": challenge.event.status,
            },
        )

    with transaction.atomic():
        # Soft-delete prerequisite links where this challenge is required
        CTFChallengePrerequisite.objects.filter(required_challenge=challenge).update(deleted_at=timezone.now())
        challenge.delete(soft=True)
    logger.info("Deleted challenge %s", challenge_id)


def get_challenge(challenge_id: UUID) -> CTFChallenge:
    """Get a challenge by ID.

    Args:
        challenge_id: UUID of the challenge.

    Returns:
        The CTFChallenge instance.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
    """
    try:
        return CTFChallenge.objects.select_related("event").get(pk=challenge_id)
    except CTFChallenge.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge {challenge_id} not found",
            details={"challenge_id": str(challenge_id)},
        ) from None


def get_available_challenges(
    event_id: UUID,
    include_unreleased: bool = False,
    participant_id: UUID | None = None,
) -> QuerySet[CTFChallenge]:
    """Get challenges available for an event.

    Args:
        event_id: UUID of the event.
        include_unreleased: If True, include challenges with future release times.
        participant_id: If provided, exclude challenges with unmet prerequisites.

    Returns:
        QuerySet of CTFChallenge instances.
    """
    from django.db.models import Q

    qs = CTFChallenge.objects.filter(event_id=event_id)

    if not include_unreleased:
        now = timezone.now()
        # Exclude hidden challenges and those not yet released
        qs = qs.exclude(visibility="hidden")
        qs = qs.filter(Q(release_time__isnull=True) | Q(release_time__lte=now))

    if participant_id is not None:
        from ctf.models import CTFSubmission

        solved_ids = set(
            CTFSubmission.objects.filter(
                participant_id=participant_id,
                is_correct=True,
            ).values_list("challenge_id", flat=True)
        )
        # Exclude challenges that have active prerequisites not yet solved
        challenges_with_unmet = set()
        prereqs = CTFChallengePrerequisite.objects.filter(
            challenge__event_id=event_id,
        ).values_list("challenge_id", "required_challenge_id")
        for challenge_id, required_id in prereqs:
            if required_id not in solved_ids:
                challenges_with_unmet.add(challenge_id)

        if challenges_with_unmet:
            qs = qs.exclude(id__in=challenges_with_unmet)

    return qs.order_by("category", "order", "name")


def list_challenges_for_event(event_id: UUID) -> QuerySet[CTFChallenge]:
    """List all challenges for an event (admin view).

    Args:
        event_id: UUID of the event.

    Returns:
        QuerySet of CTFChallenge instances.
    """
    return CTFChallenge.objects.filter(event_id=event_id).order_by("category", "order", "name")


# -----------------------------------------------------------------------------
# Prerequisite Operations
# -----------------------------------------------------------------------------


def add_prerequisite(challenge_id: UUID, required_challenge_id: UUID) -> CTFChallengePrerequisite:
    """Add a prerequisite to a challenge.

    Args:
        challenge_id: UUID of the dependent challenge.
        required_challenge_id: UUID of the required challenge.

    Returns:
        The created CTFChallengePrerequisite instance.

    Raises:
        CTFNotFoundError: If either challenge doesn't exist.
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
        challenge_id,
        required_challenge_id,
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


def remove_prerequisite(prerequisite_id: UUID) -> None:
    """Remove a prerequisite.

    Args:
        prerequisite_id: UUID of the prerequisite to remove.

    Raises:
        CTFNotFoundError: If prerequisite doesn't exist.
        CTFStateError: If event is not content-modifiable.
    """
    try:
        prereq = CTFChallengePrerequisite.objects.select_related("challenge__event").get(pk=prerequisite_id)
    except CTFChallengePrerequisite.DoesNotExist:
        raise CTFNotFoundError(
            f"Prerequisite {prerequisite_id} not found",
            details={"prerequisite_id": str(prerequisite_id)},
        ) from None

    if not prereq.challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot modify challenge in event with status {prereq.challenge.event.status}",
            details={"prerequisite_id": str(prerequisite_id), "event_status": prereq.challenge.event.status},
        )

    prereq.delete(soft=True)
    logger.info("Removed prerequisite %s", prerequisite_id)


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
