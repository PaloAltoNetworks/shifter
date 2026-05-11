"""CTF Attachment service.

Provides business logic for challenge file attachments.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import QuerySet

from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFChallengeFile
from ctf.s3 import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    MAX_FILES_PER_CHALLENGE,
    CTFFileError,
    delete_challenge_file,
    generate_download_url,
    upload_challenge_file,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def add_challenge_file(
    challenge_id: UUID,
    file_obj,
    filename: str,
    display_name: str = "",
    content_type: str = "application/octet-stream",
    *,
    actor_id: int,
) -> CTFChallengeFile:
    """Add a file attachment to a challenge.

    Args:
        challenge_id: UUID of the challenge.
        file_obj: File-like object to upload.
        filename: Original filename.
        display_name: Optional friendly display name.
        content_type: MIME type of the file.
        actor_id: User pk of the caller. Required (issue #765 DiD).

    Returns:
        The created CTFChallengeFile instance.

    Raises:
        CTFNotFoundError: If challenge doesn't exist.
        CTFPermissionError: If actor does not own the challenge's event.
        CTFStateError: If event is not content-modifiable.
        CTFValidationError: If file fails validation.
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
            f"Cannot modify challenge in event with status {challenge.event.status}",
            details={"challenge_id": str(challenge_id), "event_status": challenge.event.status},
        )

    # Validate file extension
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise CTFValidationError(
            f"File extension '{ext}' is not allowed",
            details={"filename": filename, "allowed": sorted(ALLOWED_EXTENSIONS)},
        )

    # Validate file size
    file_obj.seek(0, 2)  # Seek to end
    file_size = file_obj.tell()
    file_obj.seek(0)
    if file_size > MAX_FILE_SIZE:
        raise CTFValidationError(
            f"File size ({file_size} bytes) exceeds maximum ({MAX_FILE_SIZE} bytes)",
            details={"file_size": file_size, "max_size": MAX_FILE_SIZE},
        )
    if file_size == 0:
        raise CTFValidationError(
            "File is empty",
            details={"filename": filename},
        )

    # Check file count limit
    current_count = CTFChallengeFile.objects.filter(challenge=challenge).count()
    if current_count >= MAX_FILES_PER_CHALLENGE:
        raise CTFValidationError(
            f"Maximum files per challenge ({MAX_FILES_PER_CHALLENGE}) reached",
            details={"current_count": current_count, "max_files": MAX_FILES_PER_CHALLENGE},
        )

    # Determine next order value
    max_order = (
        CTFChallengeFile.objects.filter(challenge=challenge).order_by("-order").values_list("order", flat=True).first()
    )
    next_order = (max_order or 0) + 1

    # Upload to S3
    try:
        s3_key, sha256_hash, actual_size = upload_challenge_file(
            file_obj,
            str(challenge.event_id),
            str(challenge_id),
            filename,
        )
    except CTFFileError as e:
        raise CTFValidationError(
            f"File upload failed: {e}",
            details={"filename": filename},
        ) from e

    # Create record
    challenge_file = CTFChallengeFile.objects.create(
        challenge=challenge,
        filename=os.path.basename(filename),
        s3_key=s3_key,
        file_size_bytes=actual_size,
        content_type=content_type,
        sha256_hash=sha256_hash,
        display_name=display_name,
        order=next_order,
    )

    logger.info("Added file %s to challenge %s", challenge_file.id, challenge_id)
    return challenge_file


def remove_challenge_file(file_id: UUID, *, actor_id: int) -> None:
    """Remove a file attachment from a challenge.

    Deletes from S3 and soft-deletes the database record.

    Args:
        file_id: UUID of the file to remove.
        actor_id: User pk of the caller. Required (issue #765 DiD).

    Raises:
        CTFNotFoundError: If file doesn't exist.
        CTFPermissionError: If actor does not own the file's event.
        CTFStateError: If event is not content-modifiable.
    """
    from ctf.services.authorization import assert_actor_owns_event

    try:
        challenge_file = CTFChallengeFile.objects.select_related("challenge__event").get(pk=file_id)
    except CTFChallengeFile.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge file {file_id} not found",
            details={"file_id": str(file_id)},
        ) from None

    assert_actor_owns_event(actor_id, challenge_file.challenge.event)

    if not challenge_file.challenge.event.is_content_modifiable:
        raise CTFStateError(
            f"Cannot modify challenge in event with status {challenge_file.challenge.event.status}",
            details={"file_id": str(file_id), "event_status": challenge_file.challenge.event.status},
        )

    # Delete from S3 (best effort — don't fail the soft-delete if S3 errors)
    try:
        delete_challenge_file(challenge_file.s3_key)
    except CTFFileError:
        logger.warning("Failed to delete S3 object %s, proceeding with soft delete", challenge_file.s3_key)

    challenge_file.delete(soft=True)
    logger.info("Removed file %s", file_id)


def get_challenge_files(challenge_id: UUID) -> QuerySet[CTFChallengeFile]:
    """Get active files for a challenge.

    Args:
        challenge_id: UUID of the challenge.

    Returns:
        QuerySet of CTFChallengeFile instances.
    """
    return CTFChallengeFile.objects.filter(challenge_id=challenge_id).order_by("order", "created_at")


def get_download_url(file_id: UUID) -> tuple[str, str]:
    """Get a presigned download URL for a challenge file.

    Args:
        file_id: UUID of the file.

    Returns:
        Tuple of (presigned_url, filename).

    Raises:
        CTFNotFoundError: If file doesn't exist.
    """
    try:
        challenge_file = CTFChallengeFile.objects.get(pk=file_id)
    except CTFChallengeFile.DoesNotExist:
        raise CTFNotFoundError(
            f"Challenge file {file_id} not found",
            details={"file_id": str(file_id)},
        ) from None

    try:
        url = generate_download_url(challenge_file.s3_key, challenge_file.filename)
    except CTFFileError as e:
        raise CTFNotFoundError(
            f"Failed to generate download URL: {e}",
            details={"file_id": str(file_id)},
        ) from e

    return url, challenge_file.filename
