"""Files (script) management views."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from cms.services import (
    ScriptUploadError,
    complete_script_upload,
    delete_script,
    initiate_script_upload,
    list_scripts,
)

from ._common import _get_user, _render_via_pkg

logger = logging.getLogger(__name__)


class _FileError(Exception):
    """Internal exception carrying a JsonResponse for early-return guards."""

    def __init__(self, response: JsonResponse) -> None:
        super().__init__()
        self.response = response


@login_required
@require_GET
def files(request: HttpRequest) -> HttpResponse:
    """File management - upload and manage script files."""
    scripts = list_scripts(_get_user(request))
    context = {
        "page_title": "Files",
        "active_nav": "files",
        "scripts": scripts,
    }
    return _render_via_pkg(request, "mission_control/files.html", context)


def _validate_initiate_fields(data: dict[str, Any]) -> tuple[str, str, int]:
    """Validate the step-1 initiate payload or raise ``_FileError``."""
    name = data.get("name", "").strip()
    filename = data.get("filename", "").strip()
    file_size = data.get("file_size", 0)

    if not name:
        raise _FileError(JsonResponse({"error": "Script name is required"}, status=400))
    if not filename:
        raise _FileError(JsonResponse({"error": "Filename is required"}, status=400))
    if not isinstance(file_size, int) or file_size <= 0:
        raise _FileError(JsonResponse({"error": "Valid file size is required"}, status=400))

    return name, os.path.basename(filename), file_size


def _complete_script(user: User, upload_token: str) -> JsonResponse:
    """Step 2 of file_upload: complete an in-flight script upload."""
    try:
        script = complete_script_upload(user, upload_token)
    except ScriptUploadError as e:
        return JsonResponse({"error": str(e)}, status=400)

    logger.info("Script upload completed: user=%s script_id=%s", user.email, script.pk)
    return JsonResponse(
        {
            "success": True,
            "script_id": script.pk,
            "message": f"Script '{script.name}' uploaded successfully.",
        }
    )


def _initiate_script(user: User, data: dict[str, Any]) -> JsonResponse:
    """Step 1 of file_upload: validate fields and issue a presigned URL."""
    try:
        name, filename, file_size = _validate_initiate_fields(data)
        try:
            result = initiate_script_upload(user, name, filename, file_size)
        except ScriptUploadError as e:
            raise _FileError(JsonResponse({"error": str(e)}, status=400)) from e
    except _FileError as err:
        return err.response

    logger.info(
        "Script upload initiated: user=%s filename=%s size=%d",
        user.email,
        filename,
        file_size,
    )
    return JsonResponse(result)


@login_required
@require_POST
def file_upload(request: HttpRequest) -> JsonResponse:
    """Script file upload — two-step presigned URL flow (JSON API).

    Step 1: POST with {name, filename, file_size} → returns {presigned_url, upload_token}
    Step 2: POST with {upload_token} → returns {success, script_id}
    """
    user = _get_user(request)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    upload_token = data.get("upload_token")
    if upload_token:
        return _complete_script(user, upload_token)
    return _initiate_script(user, data)


@login_required
@require_POST
def file_delete(request: HttpRequest, script_id: int) -> HttpResponse:
    """Delete a script file (soft delete)."""
    user = _get_user(request)
    try:
        delete_script(user, script_id)
        messages.success(request, "Script deleted.")
        logger.info("Script deleted: user=%s script_id=%s", user.email, script_id)
    except ScriptUploadError as e:
        messages.error(request, str(e))
        logger.exception(
            "Script delete error: user=%s script_id=%s",
            user.email,
            script_id,
        )

    return redirect("mission_control:files")


@login_required
@require_GET
def api_list_scripts(request: HttpRequest) -> JsonResponse:
    """JSON endpoint for listing scripts (used by experiment create form)."""
    scripts = list_scripts(_get_user(request))
    return JsonResponse(
        {
            "scripts": [
                {
                    "id": s.pk,
                    "name": s.name,
                    "filename": s.original_filename,
                }
                for s in scripts
            ]
        }
    )
