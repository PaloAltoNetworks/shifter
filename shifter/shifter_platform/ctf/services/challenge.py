"""CTF Challenge service.

Provides business logic for challenge management and flag operations.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFEvent

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Use bcrypt for flag hashing (secure and includes salt)
try:
    import bcrypt

    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    logger.warning("bcrypt not available, using SHA256 for flag hashing (less secure)")


def hash_flag(flag: str) -> str:
    """Hash a flag for secure storage.

    Uses bcrypt if available, falls back to PBKDF2-SHA256.

    Args:
        flag: The plaintext flag value.

    Returns:
        Hashed flag string for storage.
    """
    if BCRYPT_AVAILABLE:
        return bcrypt.hashpw(flag.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    else:
        salt = secrets.token_hex(16)
        hash_value = hashlib.pbkdf2_hmac("sha256", flag.encode("utf-8"), salt.encode("utf-8"), iterations=600_000).hex()
        return f"pbkdf2:{salt}:{hash_value}"


def verify_flag(challenge: CTFChallenge, submitted_flag: str) -> bool:
    """Verify a submitted flag against the stored hash.

    Args:
        challenge: The challenge to verify against.
        submitted_flag: The flag submitted by the participant.

    Returns:
        True if the flag is correct, False otherwise.
    """
    stored_hash = challenge.flag_hash

    if BCRYPT_AVAILABLE and stored_hash.startswith("$2"):
        # bcrypt hash
        try:
            return bcrypt.checkpw(
                submitted_flag.encode("utf-8"),
                stored_hash.encode("utf-8"),
            )
        except Exception as e:
            logger.error("Flag verification error for challenge %s: %s", challenge.id, e)
            return False
    elif stored_hash.startswith("pbkdf2:"):
        # PBKDF2-SHA256 hash
        parts = stored_hash.split(":", 2)
        if len(parts) != 3:
            logger.error("Invalid hash format for challenge %s", challenge.id)
            return False
        _, salt, expected_hash = parts
        actual_hash = hashlib.pbkdf2_hmac(
            "sha256", submitted_flag.encode("utf-8"), salt.encode("utf-8"), iterations=600_000
        ).hex()
        return secrets.compare_digest(actual_hash, expected_hash)
    elif stored_hash.startswith("sha256:"):
        # Legacy SHA256 fallback hash (backward compat)
        parts = stored_hash.split(":", 2)
        if len(parts) != 3:
            logger.error("Invalid hash format for challenge %s", challenge.id)
            return False
        _, salt, expected_hash = parts
        actual_hash = hashlib.sha256(f"{salt}:{submitted_flag}".encode()).hexdigest()
        return secrets.compare_digest(actual_hash, expected_hash)
    else:
        logger.error("Unknown hash format for challenge %s", challenge.id)
        return False


def create_challenge(event_id: UUID, challenge_data: dict[str, Any]) -> CTFChallenge:
    """Create a new challenge.

    Args:
        event_id: UUID of the event to add the challenge to.
        challenge_data: Dictionary containing challenge fields.
            Must include 'flag' (plaintext) which will be hashed.

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

    # Validate and hash flag
    if "flag" not in challenge_data:
        raise CTFValidationError(
            "Flag is required",
            details={"missing_fields": ["flag"]},
        )

    # Extract flag and hash it
    data = challenge_data.copy()
    plaintext_flag = data.pop("flag")
    data["flag_hash"] = hash_flag(plaintext_flag)

    with transaction.atomic():
        challenge = CTFChallenge.objects.create(
            event=event,
            **data,
        )

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

    # Hash new flag if provided
    if "flag" in data:
        plaintext_flag = data.pop("flag")
        data["flag_hash"] = hash_flag(plaintext_flag)

    with transaction.atomic():
        for key, value in data.items():
            setattr(challenge, key, value)
        challenge.save()

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


def get_available_challenges(event_id: UUID, include_unreleased: bool = False) -> QuerySet[CTFChallenge]:
    """Get challenges available for an event.

    Args:
        event_id: UUID of the event.
        include_unreleased: If True, include challenges with future release times.

    Returns:
        QuerySet of CTFChallenge instances.
    """
    from django.db.models import Q
    from django.utils import timezone

    qs = CTFChallenge.objects.filter(event_id=event_id)

    if not include_unreleased:
        now = timezone.now()
        qs = qs.filter(Q(release_time__isnull=True) | Q(release_time__lte=now))

    return qs.order_by("category", "order", "name")


def list_challenges_for_event(event_id: UUID) -> QuerySet[CTFChallenge]:
    """List all challenges for an event (admin view).

    Args:
        event_id: UUID of the event.

    Returns:
        QuerySet of CTFChallenge instances.
    """
    return CTFChallenge.objects.filter(event_id=event_id).order_by("category", "order", "name")
