"""Script asset service entrypoints.

All names that tests mock via ``patch("cms.experiments.services.<name>")``
(for example ``verify_upload_token``, ``verify_s3_object``,
``read_script_header``, ``delete_s3_object``, ``audit_log``,
``ScriptAsset``, ``transaction``) are looked up through the package at
call time, not bound here at import time. That keeps the package-split
backward-compatible with the existing test patches.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from cms.assets.s3 import S3Error
from cms.experiments import services as _pkg
from cms.experiments.exceptions import ExperimentError, ScriptUploadError
from cms.experiments.schemas import ScriptUploadInput
from risk_register.models import AuditLog
from shared.log_sanitize import safe_log_value
from shared.uploads.inspection import (
    InspectionError as _ScriptInspectionError,
)
from shared.uploads.inspection import (
    validate_text_header as _validate_script_text_header,
)

from ._common import _validate_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import QuerySet

    from cms.experiments.models import ScriptAsset

logger = logging.getLogger(__name__)


def list_scripts(user: User) -> QuerySet[ScriptAsset]:
    """List active (non-deleted) scripts for a user.

    Args:
        user: The authenticated user.

    Returns:
        QuerySet of active ScriptAsset objects.
    """
    _validate_user(user, "list_scripts")
    logger.debug("list_scripts called for user_id=%s", user.id)
    try:
        return _pkg.ScriptAsset.objects.filter(user=user).order_by("-created_at")
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in list_scripts for user_id=%s", user.id)
        raise


def initiate_script_upload(user: User, name: str, filename: str, file_size: int) -> dict[str, str]:
    """Start the script upload flow: validate, generate presigned URL, return token.

    Args:
        user: The authenticated user.
        name: User-provided script name.
        filename: Original filename.
        file_size: Expected file size in bytes.

    Returns:
        Dict with presigned_url, s3_key, upload_token.

    Raises:
        ScriptUploadError: If validation or URL generation fails.
    """
    _validate_user(user, "initiate_script_upload")
    logger.debug("initiate_script_upload called for user_id=%s filename=%s", user.id, safe_log_value(filename))
    try:
        try:
            validated = ScriptUploadInput(name=name, filename=filename, file_size=file_size)
        except Exception as e:
            logger.warning("initiate_script_upload: validation failed user_id=%s: %s", user.pk, e)
            raise ScriptUploadError(f"Validation failed: {e}") from e

        try:
            presigned_url, s3_key = _pkg.generate_script_upload_url(user.pk, validated.filename)
        except S3Error as e:
            logger.exception("initiate_script_upload: S3 error user_id=%s", user.pk)
            raise ScriptUploadError(f"Failed to generate upload URL: {e}") from e

        upload_token = _pkg.generate_upload_token(
            user_id=user.pk,
            s3_key=s3_key,
            name=validated.name,
            filename=validated.filename,
            file_size=validated.file_size,
        )

        logger.info("initiate_script_upload: success user_id=%s s3_key=%s", user.pk, s3_key)
        return {
            "presigned_url": presigned_url,
            "s3_key": s3_key,
            "upload_token": upload_token,
        }
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in initiate_script_upload for user_id=%s", user.id)
        raise


def _inspect_uploaded_script_body(user: User, s3_key: str, max_size: int) -> None:
    """Read the full S3 object and reject if it isn't valid UTF-8 / has a binary signature.

    Scripts are capped at 1 MB, so we inspect the entire body, not just a header,
    which blocks the "valid text prefix + binary tail" bypass. Cleans up the
    rejected object on failure (best-effort).
    """
    try:
        body = _pkg.read_script_header(s3_key, max_size)
    except S3Error as e:
        logger.exception(
            "complete_script_upload: body read failed s3_key=%s",
            safe_log_value(s3_key),
        )
        raise ScriptUploadError("Upload content inspection failed") from e

    try:
        _validate_script_text_header(body, complete=True)
    except _ScriptInspectionError as e:
        logger.warning(
            "complete_script_upload: header inspection rejected upload user_id=%s s3_key=%s reason=%s",
            user.pk,
            safe_log_value(s3_key),
            safe_log_value(e),
        )
        try:
            _pkg.delete_s3_object(s3_key)
        except S3Error:
            logger.exception(
                "complete_script_upload: delete after inspection failure also failed s3_key=%s",
                safe_log_value(s3_key),
            )
        raise ScriptUploadError("Uploaded content is not a valid script (binary or non-UTF-8 header)") from e


def complete_script_upload(user: User, upload_token: str) -> ScriptAsset:
    """Finalize script upload: verify token, verify S3 object, create DB record.

    Args:
        user: The authenticated user.
        upload_token: HMAC-signed upload token from initiate step.

    Returns:
        Created ScriptAsset instance.

    Raises:
        ScriptUploadError: If verification fails.
    """
    _validate_user(user, "complete_script_upload")
    logger.debug("complete_script_upload called for user_id=%s", user.id)
    try:
        try:
            payload = _pkg.verify_upload_token(upload_token, user.pk)
        except ValueError as e:
            logger.warning("complete_script_upload: token invalid user_id=%s: %s", user.pk, e)
            raise ScriptUploadError(f"Invalid upload token: {e}") from e

        # Narrow JSON-decoded payload values to their concrete types at the
        # boundary so downstream str/int helpers don't have to re-validate.
        s3_key = str(payload["s3_key"])
        expected_size = int(payload["file_size"])

        try:
            actual_size, etag = _pkg.verify_s3_object(s3_key)
        except S3Error as e:
            logger.exception(
                "complete_script_upload: S3 verify failed s3_key=%s",
                safe_log_value(s3_key),
            )
            raise ScriptUploadError(f"Upload verification failed: {e}") from e

        max_size = settings.SCRIPT_MAX_FILE_SIZE_BYTES
        if actual_size > max_size:
            logger.warning(
                "complete_script_upload: file too large s3_key=%s size=%d max=%d",
                safe_log_value(s3_key),
                actual_size,
                max_size,
            )
            _pkg.delete_s3_object(s3_key)
            raise ScriptUploadError(f"File size {actual_size} exceeds maximum {max_size} bytes")

        # Enforce the signed upload contract: actual object size must match
        # the size signed into the upload token. Matches the agent
        # `complete_upload` invariant; without it a caller could initiate a
        # small-size upload and PUT a different-size object to the same key.
        if actual_size != expected_size:
            # Inline CR/LF stripping at the call site so CodeQL's
            # ``py/log-injection`` taint tracker recognises the sanitization.
            safe_s3_key = str(s3_key).replace("\r", " ").replace("\n", " ").replace("\t", " ")[:200]
            logger.warning(
                "complete_script_upload: size mismatch s3_key=%s expected=%d actual=%d",
                safe_s3_key,
                int(expected_size),
                int(actual_size),
            )
            _pkg.delete_s3_object(s3_key)
            raise ScriptUploadError(f"File size mismatch: expected {expected_size}, got {actual_size}")

        # Server-side full-body content inspection (issue #696). Scripts are
        # capped at 1 MB, so we read the entire body — not just a header — and
        # require it to be valid UTF-8 with no binary signature anywhere in
        # the stream. This blocks the "valid text prefix + binary tail" bypass
        # the bounded-header check by itself cannot detect.
        _inspect_uploaded_script_body(user, s3_key, max_size)

        script = _pkg.ScriptAsset(
            user=user,
            name=str(payload["name"]),
            s3_key=s3_key,
            original_filename=str(payload["filename"]),
            file_size_bytes=actual_size,
            sha256_hash=etag,
        )
        try:
            script.full_clean()
        except DjangoValidationError as e:
            raise ScriptUploadError(f"Validation failed: {e}") from e
        script.save()

        _pkg.audit_log(
            entity_type=AuditLog.EntityType.SCRIPT,
            entity_id=script.pk,
            action=AuditLog.Action.CREATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state={"name": payload["name"], "filename": payload["filename"], "s3_key": s3_key},
        )
        logger.info(
            "complete_script_upload: created script_id=%s user_id=%s s3_key=%s",
            script.pk,
            user.pk,
            safe_log_value(s3_key),
        )
        return script
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in complete_script_upload for user_id=%s", user.id)
        raise


def delete_script(user: User, script_id: int) -> None:
    """Soft-delete a script asset.

    Args:
        user: The authenticated user.
        script_id: ID of the script to delete.

    Raises:
        ScriptUploadError: If script not found or not owned by user.
    """
    _validate_user(user, "delete_script")
    # Coerce script_id through int() at the boundary so CodeQL sees a
    # primitive-int barrier between user input and the log statements below.
    script_id = int(script_id)
    logger.debug("delete_script called for user_id=%s script_id=%d", user.id, script_id)
    try:
        try:
            script = _pkg.ScriptAsset.objects.get(pk=script_id, user=user)
        except _pkg.ScriptAsset.DoesNotExist:
            logger.warning("delete_script: not found script_id=%d user_id=%s", script_id, user.pk)
            raise ScriptUploadError("Script not found or you don't have access") from None
        _pkg._check_result_type(script, _pkg.ScriptAsset, "delete_script")

        script.deleted_at = timezone.now()
        script.save(update_fields=["deleted_at"])
        _pkg.audit_log(
            entity_type=AuditLog.EntityType.SCRIPT,
            entity_id=script_id,
            action=AuditLog.Action.DELETE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            previous_state={"name": script.name},
        )
        logger.info("delete_script: soft-deleted script_id=%d user_id=%s", script_id, user.pk)
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in delete_script for user_id=%s", user.id)
        raise
