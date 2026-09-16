"""Finalization helpers for ``complete_upload``.

Split out of ``_uploads.py`` to keep that module under the per-file size limit.
These are private helpers composed by ``cms.services._uploads.complete_upload``:
token verification, authoritative object-size/cap verification, header
inspection (issue #696), and the immutable staging-to-install copy (issue #1181).
"""

from __future__ import annotations

import logging
from typing import Any

from cms.exceptions import CMSError
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


def _verify_upload_token_or_raise(upload_token: str, user_id: int) -> dict[str, Any]:
    """Verify the signed upload token, re-raising payload errors as CMSError."""
    from cms.assets.upload_token import verify_upload_token

    try:
        return verify_upload_token(upload_token, user_id)
    except ValueError as e:
        logger.exception("complete_upload: token verification failed for user_id=%s", user_id)
        raise CMSError("Invalid upload token") from e


def _verify_upload_object_or_raise(s3_key: str, expected_size: int, user_id: int) -> dict[str, Any]:
    """Verify the S3 object exists and its byte length matches the signed expectation.

    Returns the captured object identity (``content_length`` + provider identity
    fields such as ``etag`` / ``generation``) so completion can bind the later
    immutable copy to the exact version validated here.
    """
    from cms.assets.s3 import S3Error, delete_agent, verify_s3_object_exists
    from cms.assets.validation import ValidationError, agent_max_file_size_bytes, enforce_max_file_size_bytes

    try:
        identity = verify_s3_object_exists(s3_key)
    except S3Error as e:
        logger.exception("complete_upload: S3 verification failed for user_id=%s", user_id)
        raise CMSError("Upload not found in storage") from e

    actual_size = identity["content_length"]

    # Absolute per-file cap against the CURRENT server policy, before the token's
    # declared-size equality check. A stale or crafted token may have been signed
    # under a different cap, so this uses the live limit and the authoritative
    # provider-reported length, never the token's declared file_size. An oversized
    # object is cleaned up (best effort) and rejected even if cleanup fails;
    # nothing downstream (inspection, immutable copy, tag, DB row, creation audit)
    # runs.
    try:
        enforce_max_file_size_bytes(actual_size)
    except ValidationError as e:
        logger.warning(
            "complete_upload: object exceeds per-file limit user_id=%s s3_key=%s actual=%s limit=%s",
            user_id,
            safe_log_value(s3_key),
            actual_size,
            agent_max_file_size_bytes(),
        )
        try:
            delete_agent(s3_key)
        except S3Error:
            logger.exception(
                "complete_upload: cleanup after oversize object failed user_id=%s s3_key=%s",
                user_id,
                safe_log_value(s3_key),
            )
        raise CMSError(str(e)) from e

    if actual_size != expected_size:
        logger.error(
            "complete_upload: size mismatch for user_id=%s - expected=%s, actual=%s",
            user_id,
            safe_log_value(expected_size),
            actual_size,
        )
        raise CMSError(f"File size mismatch: expected {expected_size}, got {actual_size}")

    return identity


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


def _install_validated_upload_or_raise(
    staging_key: str,
    filename: str,
    identity: dict[str, Any],
    user_id: int,
) -> str:
    """Copy the validated staging object to an immutable install key.

    Closes the TOCTOU window (issue #1181): the still-valid presigned PUT can
    overwrite the staging object after validation, so binding the installed
    ``AgentConfig`` to the mutable staging key would let unvalidated bytes ship.
    Instead, conditionally copy the exact validated version to a fresh
    server-controlled install key and persist only that key. A precondition
    failure means the bytes changed between check and use — a security signal, so
    finalize nothing. Deleting the staging object afterwards is best-effort
    hygiene (it removes the object the presigned PUT still targets).

    Returns the install key on success.
    """
    from cms.assets.s3 import S3Error, delete_agent, generate_install_key, install_agent_object

    install_key = generate_install_key(user_id, filename)
    try:
        install_agent_object(staging_key, install_key, identity)
    except S3Error as exc:
        logger.warning(
            "complete_upload: immutable install failed for user_id=%s staging=%s install=%s",
            user_id,
            safe_log_value(staging_key),
            safe_log_value(install_key),
        )
        raise CMSError("Upload could not be finalized; please re-upload") from exc

    try:
        delete_agent(staging_key)
    except S3Error:
        logger.warning(
            "complete_upload: staging cleanup after install failed for user_id=%s staging=%s",
            user_id,
            safe_log_value(staging_key),
        )

    return install_key
