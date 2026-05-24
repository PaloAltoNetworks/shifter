"""Upload service entrypoints (initiate / complete / cancel / storage quota)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cms.exceptions import CMSError
from cms.models import AgentConfig
from shared.log_sanitize import safe_log_value

from ._common import _validate_caller_user, _validate_nonempty_str, _validate_positive_int

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def _validate_initiate_upload_inputs(
    user: User,
    name: str,
    filename: str,
    file_size: int,
) -> tuple[str, str]:
    """Validate inputs for `initiate_upload` and return normalized (name, filename)."""
    _validate_caller_user(user, "initiate_upload")
    name = _validate_nonempty_str(name, "name", "initiate_upload", user.id)
    filename = _validate_nonempty_str(filename, "filename", "initiate_upload", user.id)
    _validate_positive_int(file_size, "file_size", "initiate_upload", user.id)
    return name, filename


def _initiate_upload_inner(
    user: User,
    name: str,
    filename: str,
    file_size: int,
    agent_type: str,
) -> dict[str, Any]:
    """Quota check, extension validation, presigned-URL + upload-token issuance.

    Split out of `initiate_upload` so that function carries only input
    validation and exception-translation, keeping each below the per-function
    complexity ceiling.
    """
    from django.conf import settings

    from cms.assets.s3 import S3Error, generate_presigned_upload_url
    from cms.assets.services import get_storage_used
    from cms.assets.upload_token import generate_upload_token
    from cms.assets.validation import ValidationError, validate_file_extension

    current_usage = get_storage_used(user)
    quota_bytes = settings.AGENT_USER_STORAGE_QUOTA_MB * 1024 * 1024
    if current_usage + file_size > quota_bytes:
        available_mb = (quota_bytes - current_usage) / 1024 / 1024
        logger.error(
            "initiate_upload: quota exceeded for user_id=%s - current=%s, requested=%s, quota=%s",
            user.id,
            current_usage,
            safe_log_value(file_size),
            quota_bytes,
        )
        msg = (
            f"Storage quota exceeded. You have {available_mb:.1f} MB "
            f"available of {settings.AGENT_USER_STORAGE_QUOTA_MB} "
            f"MB total."
        )
        raise CMSError(msg)

    try:
        file_format = validate_file_extension(filename)
    except ValidationError as e:
        logger.exception("initiate_upload: validation error for user_id=%s", user.id)
        raise CMSError(str(e)) from e

    try:
        presigned_url, s3_key = generate_presigned_upload_url(
            user_id=user.id,
            filename=filename,
        )
    except S3Error as e:
        logger.exception("initiate_upload: S3 error for user_id=%s", user.id)
        raise CMSError("Failed to initiate upload") from e

    # Agent installer formats always carry an os_slug — the shared FileFormat
    # dataclass makes the field Optional for non-installer consumers (CTF),
    # so narrow here.
    os_slug = file_format.os_slug
    if os_slug is None:
        logger.error(
            "initiate_upload: installer format missing os_slug for filename=%s",
            safe_log_value(filename),
        )
        raise CMSError("Internal error: installer format misconfigured")

    upload_token = generate_upload_token(
        user_id=user.id,
        s3_key=s3_key,
        name=name,
        filename=filename,
        os_slug=os_slug,
        file_size=file_size,
        agent_type=agent_type,
    )

    logger.debug(
        "initiate_upload completed for user_id=%s, filename=%s, s3_key=%s",
        user.id,
        safe_log_value(filename),
        safe_log_value(s3_key),
    )

    return {
        "presigned_url": presigned_url,
        "s3_key": s3_key,
        "upload_token": upload_token,
        "expected_os": file_format.os_slug,
    }


def initiate_upload(
    user: User,
    name: str,
    filename: str,
    file_size: int,
    agent_type: str = "xdr",
) -> dict[str, Any]:
    """Validate and generate presigned URL for direct S3 upload.

    Validates user quota, file extension, and generates all components needed
    for the client to upload directly to S3.

    Args:
        user: User initiating the upload
        name: Display name for the agent
        filename: Original filename (used for extension validation)
        file_size: Expected file size in bytes
        agent_type: Type of agent (xdr, xdr_collector, cloud_identity_engine)

    Returns:
        Dict containing:
            - presigned_url: URL for PUT request to S3
            - s3_key: S3 key where file will be uploaded
            - upload_token: Signed token for completion verification
            - expected_os: Operating system slug from file extension

    Raises:
        TypeError: If user is None, invalid type, or file_size is
            invalid type
        ValueError: If user is unsaved, name/filename is empty, or
            file_size is invalid
        CMSError: If quota exceeded, invalid extension, or S3 error
    """
    name, filename = _validate_initiate_upload_inputs(user, name, filename, file_size)

    logger.debug(
        "initiate_upload called for user_id=%s, filename=%s, file_size=%s",
        user.id,
        safe_log_value(filename),
        safe_log_value(file_size),
    )

    try:
        return _initiate_upload_inner(user, name, filename, file_size, agent_type)
    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception("Error in initiate_upload for user_id=%s", user.id)
        raise


def _verify_upload_token_or_raise(upload_token: str, user_id: int) -> dict[str, Any]:
    """Verify the signed upload token, re-raising payload errors as CMSError."""
    from cms.assets.upload_token import verify_upload_token

    try:
        return verify_upload_token(upload_token, user_id)
    except ValueError as e:
        logger.exception("complete_upload: token verification failed for user_id=%s", user_id)
        raise CMSError("Invalid upload token") from e


def _verify_upload_object_or_raise(s3_key: str, expected_size: int, user_id: int) -> None:
    """Verify the S3 object exists and its byte length matches the signed expectation."""
    from cms.assets.s3 import S3Error, verify_s3_object_exists

    try:
        actual_size, _etag = verify_s3_object_exists(s3_key)
    except S3Error as e:
        logger.exception("complete_upload: S3 verification failed for user_id=%s", user_id)
        raise CMSError("Upload not found in storage") from e

    if actual_size != expected_size:
        logger.error(
            "complete_upload: size mismatch for user_id=%s - expected=%s, actual=%s",
            user_id,
            safe_log_value(expected_size),
            actual_size,
        )
        raise CMSError(f"File size mismatch: expected {expected_size}, got {actual_size}")


def _inspect_upload_header_or_raise(payload: dict[str, Any], s3_key: str, user_id: int) -> None:
    """Header-inspect the uploaded object (issue #696); delete + raise on mismatch."""
    from django.conf import settings as _settings

    from cms.assets import s3 as _s3
    from cms.assets.s3 import S3Error
    from cms.assets.validation import ValidationError as _AssetValidationError
    from cms.assets.validation import validate_file_extension
    from shared.uploads.inspection import InspectionError as _InspectionError
    from shared.uploads.inspection import validate_magic_bytes as _validate_magic_bytes

    try:
        expected_format = validate_file_extension(payload["filename"])
    except _AssetValidationError as exc:
        logger.exception("complete_upload: filename failed extension check user_id=%s", user_id)
        _s3.delete_agent(s3_key)
        raise CMSError(f"Invalid upload filename: {exc}") from exc

    try:
        header = _s3.read_agent_header(s3_key, _settings.UPLOAD_INSPECTION_MAX_HEADER_BYTES)
    except S3Error as exc:
        logger.exception("complete_upload: header read failed user_id=%s s3_key=%s", user_id, safe_log_value(s3_key))
        raise CMSError("Upload content inspection failed") from exc

    try:
        _validate_magic_bytes(header, expected_format)
    except _InspectionError as exc:
        logger.warning(
            "complete_upload: header inspection rejected upload user_id=%s s3_key=%s expected=%s reason=%s",
            user_id,
            safe_log_value(s3_key),
            expected_format.description,
            exc,
        )
        try:
            _s3.delete_agent(s3_key)
        except S3Error:
            logger.exception(
                "complete_upload: delete after inspection failure also failed user_id=%s s3_key=%s",
                user_id,
                safe_log_value(s3_key),
            )
        raise CMSError("Uploaded content does not match the declared installer format") from exc


def complete_upload(user: User, upload_token: str) -> AgentConfig:
    """Verify and finalize upload after file has been uploaded to S3.

    Verifies the upload token, checks the S3 object exists with correct size,
    runs server-side header inspection (issue #696), tags it as completed,
    and creates the agent record.

    Raises:
        TypeError: If user is None or invalid type.
        ValueError: If user is unsaved or upload_token is empty.
        CMSError: If token is invalid/expired, S3 verification fails, size
            mismatch, or header inspection rejects the upload.
    """
    from cms.assets.s3 import tag_s3_object
    from cms.assets.services import create_agent

    _validate_caller_user(user, "complete_upload")
    upload_token = _validate_nonempty_str(upload_token, "upload_token", "complete_upload", user.id)
    logger.debug("complete_upload called for user_id=%s", user.id)

    try:
        payload = _verify_upload_token_or_raise(upload_token, user.id)
        s3_key = payload["s3_key"]
        expected_size = payload["file_size"]
        _verify_upload_object_or_raise(s3_key, expected_size, user.id)
        _inspect_upload_header_or_raise(payload, s3_key, user.id)

        tag_s3_object(s3_key, {"status": "completed"})
        agent = create_agent(
            user=user,
            name=payload["name"],
            s3_key=s3_key,
            filename=payload["filename"],
            os_slug=payload["os_slug"],
            file_size=expected_size,
            upload_method="presigned",
            agent_type=payload.get("agent_type", "xdr"),
        )
        logger.debug("complete_upload completed for user_id=%s, agent_id=%s", user.id, agent.id)
        return agent

    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception("Error in complete_upload for user_id=%s", user.id)
        raise


def cancel_upload(user: User, upload_token: str) -> None:
    """Cancel an upload and clean up the S3 object.

    Verifies the upload token and attempts to delete the S3 object.
    S3 delete failures are logged but don't cause the operation to fail
    (best effort cleanup).

    Args:
        user: User who initiated the upload
        upload_token: Signed token from initiate_upload

    Returns:
        None

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user is unsaved or upload_token is empty
        CMSError: If token is invalid/expired
    """
    from cms.assets.s3 import S3Error, delete_agent
    from cms.assets.upload_token import verify_upload_token

    _validate_caller_user(user, "cancel_upload")

    if upload_token is None:
        logger.error(
            "cancel_upload called with None upload_token for user_id=%s",
            user.id,
        )
        raise ValueError("upload_token cannot be None")

    upload_token = upload_token.strip()
    if not upload_token:
        logger.error(
            "cancel_upload called with empty upload_token for user_id=%s",
            user.id,
        )
        raise ValueError("upload_token cannot be empty")

    logger.debug("cancel_upload called for user_id=%s", user.id)

    try:
        try:
            payload = verify_upload_token(upload_token, user.id)
        except ValueError as e:
            logger.exception(
                "cancel_upload: token verification failed for user_id=%s - %s",
                user.id,
                str(e),
            )
            raise CMSError("Invalid upload token") from e

        s3_key = payload["s3_key"]

        try:
            delete_agent(s3_key)
        except S3Error as e:
            logger.warning(
                "cancel_upload: S3 delete failed for user_id=%s, s3_key=%s - %s",
                user.id,
                safe_log_value(s3_key),
                safe_log_value(e),
            )

        logger.debug(
            "cancel_upload completed for user_id=%s, s3_key=%s",
            user.id,
            safe_log_value(s3_key),
        )

    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception("Error in cancel_upload for user_id=%s", user.id)
        raise


def get_storage_used(user: User) -> int:
    """Get total bytes used by a user's active agents.

    Args:
        user: The user to check storage for

    Returns:
        int: Total bytes used by active agents (0 if none)

    Raises:
        TypeError: If user is None or not a User instance
        ValueError: If user is not saved (no ID)
    """
    from cms.assets.services import get_storage_used as assets_get_storage_used

    _validate_caller_user(user, "get_storage_used")

    logger.debug("get_storage_used called for user_id=%s", user.id)

    try:
        result = assets_get_storage_used(user)

        logger.debug(
            "get_storage_used returning %d bytes for user_id=%s",
            result,
            user.id,
        )
        return result

    except Exception:
        logger.exception(
            "Error in get_storage_used for user_id=%s",
            user.id,
        )
        raise
