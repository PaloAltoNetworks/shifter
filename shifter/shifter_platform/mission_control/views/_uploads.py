"""Presigned-URL upload API views (agent uploads)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from cms.services import cancel_upload as cms_cancel_upload
from cms.services import complete_upload as cms_complete_upload
from cms.services import initiate_upload as cms_initiate_upload
from mission_control.upload_session import (
    check_upload_in_progress,
    set_upload_in_progress,
)
from shared.exceptions import CMSError

from ._common import _get_user

logger = logging.getLogger(__name__)

_VALID_AGENT_TYPES = {"xdr", "xdr_collector", "cloud_identity_engine"}


class _UploadError(Exception):
    """Internal exception carrying a JsonResponse for early-return guards."""

    def __init__(self, response: JsonResponse) -> None:
        super().__init__()
        self.response = response


def _parse_json_body(request: HttpRequest, *, default_on_decode_error: bool = False) -> dict[str, Any]:
    """Parse the request body as JSON.

    Raises ``_UploadError`` on invalid JSON unless ``default_on_decode_error`` is True,
    in which case an empty dict is returned (used by ``cancel_upload`` for sendBeacon).
    """
    try:
        return json.loads(request.body)
    except json.JSONDecodeError as e:
        if default_on_decode_error:
            return {}
        raise _UploadError(JsonResponse({"error": "Invalid JSON"}, status=400)) from e


def _validate_initiate_fields(data: dict[str, Any]) -> tuple[str, str, int, str]:
    """Validate the initiate_upload payload or raise ``_UploadError``."""
    name = data.get("name", "").strip()
    filename = data.get("filename", "").strip()
    file_size = data.get("file_size", 0)
    agent_type = data.get("agent_type", "xdr").strip()

    if not name:
        raise _UploadError(JsonResponse({"error": "Agent name is required"}, status=400))
    if not filename:
        raise _UploadError(JsonResponse({"error": "Filename is required"}, status=400))
    if not isinstance(file_size, int) or file_size <= 0:
        raise _UploadError(JsonResponse({"error": "Valid file size is required"}, status=400))
    if agent_type not in _VALID_AGENT_TYPES:
        err_msg = f"Invalid agent type. Must be one of: {', '.join(_VALID_AGENT_TYPES)}"
        raise _UploadError(JsonResponse({"error": err_msg}, status=400))

    return name, os.path.basename(filename), file_size, agent_type


@login_required
@require_POST
def initiate_upload(request: HttpRequest) -> JsonResponse:
    """
    Step 1: Request presigned URL for direct S3 upload.

    Request body (JSON):
        - name: Agent name (required)
        - filename: Original filename (required)
        - file_size: File size in bytes (required)
        - agent_type: Type of agent (optional, defaults to 'xdr')
            Valid values: 'xdr', 'xdr_collector', 'cloud_identity_engine'

    Response (JSON):
        - presigned_url: URL for PUT request to S3
        - s3_key: Key that will be created
        - upload_token: Signed token for completion verification
    """
    if check_upload_in_progress(request.session):
        return JsonResponse(
            {"error": "An upload is already in progress. Please wait for it to complete."},
            status=409,
        )

    user = _get_user(request)
    try:
        data = _parse_json_body(request)
        name, filename, file_size, agent_type = _validate_initiate_fields(data)
        try:
            result = cms_initiate_upload(user, name, filename, file_size, agent_type)
        except CMSError as e:
            raise _UploadError(JsonResponse({"error": str(e)}, status=400)) from e
    except _UploadError as err:
        return err.response

    set_upload_in_progress(request.session, True)
    logger.info(
        "Upload initiated: user=%s filename=%s size=%d",
        user.email,
        filename,
        file_size,
    )
    return JsonResponse(result)


@login_required
@require_POST
def complete_upload(request: HttpRequest) -> JsonResponse:
    """
    Step 3: Complete upload after file is in S3.

    Request body (JSON):
        - upload_token: Token from initiate response

    Response (JSON):
        - success: true
        - agent_id: Created agent ID
        - message: Success message
    """
    user = _get_user(request)
    try:
        data = _parse_json_body(request)
    except _UploadError as err:
        return err.response

    upload_token = data.get("upload_token", "")
    try:
        agent = cms_complete_upload(user, upload_token)
    except CMSError as e:
        set_upload_in_progress(request.session, False)
        return JsonResponse({"error": str(e)}, status=400)

    set_upload_in_progress(request.session, False)
    logger.info("Upload completed: user=%s agent_id=%s", user.email, agent.id)
    return JsonResponse(
        {
            "success": True,
            "agent_id": agent.id,
            "message": f"Agent '{agent.name}' uploaded successfully.",
        }
    )


# Allow sendBeacon on page unload (no custom headers).
@csrf_exempt
@login_required
@require_POST
def cancel_upload(request: HttpRequest) -> JsonResponse:
    """
    Cancel an in-progress upload.

    Request body (JSON):
        - upload_token: Token from initiate response (optional)

    Cleans up S3 object if it exists and clears upload lock.

    Note: CSRF exempt to support navigator.sendBeacon() on page unload.
    Security maintained via @login_required and HMAC-signed upload_token.
    """
    data = _parse_json_body(request, default_on_decode_error=True)

    upload_token = data.get("upload_token", "")
    user = _get_user(request)

    if upload_token:
        try:
            cms_cancel_upload(user, upload_token)
            logger.info("Cancelled upload cleaned up: user=%s", user.email)
        except CMSError:
            # Invalid token or S3 error, ignore.
            pass

    set_upload_in_progress(request.session, False)
    return JsonResponse({"success": True})
