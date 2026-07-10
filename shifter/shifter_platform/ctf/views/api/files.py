"""Challenge file-attachment JSON API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ctf.models import (
        CTFChallengeFile,
    )

from ctf.views import _access
from ctf.views._access import (
    _check_event_ownership,
    _error_tuple,
    _get_user,
    _json_error,
    ctf_organizer_required,
)
from ctf.views.api._common import (
    _delete_via_service_response,
    _resolve_owned_challenge_json,
)

logger = logging.getLogger(__name__)


def _handle_challenge_file_upload(request: HttpRequest, challenge_id: UUID, user: User) -> JsonResponse:
    """Upload a file to a challenge from the POST body, returning a 201 payload or a mapped error."""
    from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
    from ctf.services.attachment import add_challenge_file

    if not request.FILES.get("file"):
        return JsonResponse({"error": "No file provided"}, status=400)

    from django.core.files.uploadedfile import UploadedFile

    uploaded_file = cast(UploadedFile, request.FILES["file"])
    display_name = request.POST.get("display_name", "")

    challenge_file = None
    error: tuple[str, int] | None = None
    try:
        challenge_file = add_challenge_file(
            challenge_id=challenge_id,
            file_obj=uploaded_file,
            filename=uploaded_file.name or "unnamed",
            display_name=display_name,
            content_type=uploaded_file.content_type or "application/octet-stream",
            actor_id=user.pk,
        )
    except CTFPermissionError:
        error = ("Forbidden", 403)
    except CTFNotFoundError as e:
        error = _error_tuple(e, "File or challenge not found.", 404)
    except (CTFStateError, CTFValidationError) as e:
        error = _error_tuple(e, "Invalid file request.", 400)
    if error is not None:
        return JsonResponse({"error": error[0]}, status=error[1])

    assert challenge_file is not None
    return JsonResponse(
        {
            "id": str(challenge_file.id),
            "filename": challenge_file.filename,
            "display_name": challenge_file.display_name,
            "file_size_bytes": challenge_file.file_size_bytes,
            "file_size_display": challenge_file.file_size_display,
        },
        status=201,
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_challenge_files(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: List and upload challenge files.

    GET: List files for a challenge.
    POST: Upload a file to a challenge.
    """
    from ctf.services.attachment import get_challenge_files

    _challenge, error = _resolve_owned_challenge_json(request, challenge_id)
    if error is not None:
        return error

    if request.method == "GET":
        files = get_challenge_files(challenge_id)
        return JsonResponse(
            {
                "files": [
                    {
                        "id": str(f.id),
                        "filename": f.filename,
                        "display_name": f.display_name,
                        "file_size_bytes": f.file_size_bytes,
                        "file_size_display": f.file_size_display,
                        "content_type": f.content_type,
                        "sha256_hash": f.sha256_hash,
                        "order": f.order,
                        "created_at": f.created_at.isoformat(),
                    }
                    for f in files
                ]
            }
        )

    return _handle_challenge_file_upload(request, challenge_id, _get_user(request))


@login_required
@ctf_organizer_required
@require_POST
def api_challenge_file_delete(request: HttpRequest, file_id: UUID) -> JsonResponse:
    """API: Delete a challenge file.

    Args:
        file_id: UUID of the file to delete.
    """
    from ctf.models import CTFChallengeFile
    from ctf.services.attachment import remove_challenge_file

    try:
        challenge_file = CTFChallengeFile.objects.select_related("challenge__event").get(pk=file_id)
    except CTFChallengeFile.DoesNotExist:
        return JsonResponse({"error": "File not found"}, status=404)

    user = _get_user(request)
    forbidden = _check_event_ownership(challenge_file.challenge.event, user)
    if forbidden:
        return forbidden

    return _delete_via_service_response(remove_challenge_file, file_id, user)


def _is_file_download_allowed(request: HttpRequest, challenge_file: CTFChallengeFile) -> bool:
    """Return True if the user may download this challenge file.

    Organizer-owners get full access. Otherwise the user must be a
    non-disqualified participant of the event AND the challenge must be
    available to them (issue #765/#768/#769, codex cycles 2/5): file
    downloads apply the same participant-availability policy as flag
    submission and hint unlock, so a registered participant who knows a file
    UUID cannot fetch attachments for HIDDEN/LOCKED/unreleased challenges or
    events outside the competition window.
    """
    from ctf.exceptions import CTFStateError, CTFValidationError
    from ctf.services.challenge import assert_challenge_available_for_participant
    from ctf.services.participant import get_participant_by_user, is_active_participant

    user = _get_user(request)
    event = challenge_file.challenge.event
    role = _access.get_user_role(user)
    if role.is_ctf_organizer and event.created_by_id == user.pk:
        return True
    if not is_active_participant(user, event=event):
        return False

    participant = get_participant_by_user(user, event_id=event.id)
    allowed = participant is not None
    if participant is not None:
        try:
            assert_challenge_available_for_participant(participant, challenge_file.challenge)
        except (CTFStateError, CTFValidationError):
            allowed = False
    return allowed


def _file_download_url_response(file_id: UUID) -> HttpResponse:
    """Return a JSON presigned download URL for the file, or a 404.

    Returns the presigned URL for client-side navigation instead of a
    server-side redirect. This avoids open-redirect risk (S5146) since the
    server never issues an HTTP 302 to a dynamically constructed URL.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.services.attachment import get_download_url

    try:
        url, filename = get_download_url(file_id)
    except CTFNotFoundError as e:
        return _json_error(e, "File or challenge not found.", 404)
    return JsonResponse({"url": url, "filename": filename})


@login_required
@require_GET
def api_file_download(request: HttpRequest, file_id: UUID) -> HttpResponse:
    """API: Get a presigned download URL for a challenge file.

    Accessible by organizers and participants (for challenges in their event).
    """
    from ctf.models import CTFChallengeFile

    # Verify access: check the file exists and user has access
    try:
        challenge_file = CTFChallengeFile.objects.select_related("challenge__event").get(pk=file_id)
    except CTFChallengeFile.DoesNotExist:
        return JsonResponse({"error": "File not found"}, status=404)

    if not _is_file_download_allowed(request, challenge_file):
        return HttpResponse("Forbidden", status=403)

    return _file_download_url_response(file_id)
