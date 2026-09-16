"""Organizer attachment views for the canonical CTF API (challenge files + prerequisites)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, CTF_ROLE_PERMISSIONS, _CtfApiError
from ctf.api.organizer._audit import (
    admin_external_audit,
    audit_admin_event_mutation,
)
from ctf.api.organizer._base import (
    _EVENT_OR_PLAY_READ,
    _EVENT_READ,
    _EVENT_WRITE,
    _actor,
    _actor_may_manage,
    _delete_via_service,
    _raise_bad_request,
    _raise_forbidden,
    _raise_not_found,
    _resolve_owned_challenge,
)
from ctf.api.serializers import (
    ChallengeFileListResponseSerializer,
    ChallengeFileUploadResultSerializer,
    ChallengeFileUploadSerializer,
    DeleteSuccessSerializer,
    FileDownloadResponseSerializer,
    PrerequisiteCreateResultSerializer,
    PrerequisiteListResponseSerializer,
    PrerequisiteWriteSerializer,
)
from shared.audit import AuditAction

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFChallengeFile


def _is_file_download_allowed(request: Request, challenge_file: CTFChallengeFile) -> bool:
    """Return True if the actor may download this challenge file.

    Mirrors ``ctf.views.api.files._is_file_download_allowed``: organizer-owners
    get full access; otherwise the actor must be a non-disqualified participant
    of the event AND the challenge must be available to them.
    """
    from ctf.bridges import get_user_role
    from ctf.exceptions import CTFStateError, CTFValidationError
    from ctf.services.authorization import resolve_event_authority
    from ctf.services.challenge import assert_challenge_available_for_participant
    from ctf.services.participant import get_participant_by_user, is_active_participant

    user = _actor(request)
    event = challenge_file.challenge.event
    role = get_user_role(user)
    # Owner-organizer or platform administrator may download for inspection; the
    # participant availability rules below still gate every other actor.
    if (role.is_ctf_organizer and event.created_by_id == user.pk) or resolve_event_authority(user, event) is not None:
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


class ChallengeFilesView(APIView):
    """List an owned challenge's files (GET) or upload one (POST, multipart)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    parser_classes = [MultiPartParser, FormParser]
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=ChallengeFileListResponseSerializer)
    def get(self, request: Request, challenge_id: UUID) -> Response:
        """Return the file attachments for an owned challenge."""
        from ctf.services.attachment import get_challenge_files

        try:
            _resolve_owned_challenge(request, challenge_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        data = [
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
            for f in get_challenge_files(challenge_id)
        ]
        return Response({"files": data})

    @extend_schema(request=ChallengeFileUploadSerializer, responses={201: ChallengeFileUploadResultSerializer})
    def post(self, request: Request, challenge_id: UUID) -> Response:
        """Upload a multipart file attachment to an owned challenge."""
        from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
        from ctf.services.attachment import add_challenge_file

        try:
            _resolve_owned_challenge(request, challenge_id)
            uploaded_file = request.FILES.get("file")
            if not uploaded_file:
                _raise_bad_request("No file provided")
            display_name = request.data.get("display_name", "")
            try:
                # Non-rollbackable object-storage upload: override intent then outcome.
                with admin_external_audit(request, "file.upload", action=AuditAction.CREATE):
                    challenge_file = add_challenge_file(
                        challenge_id=challenge_id,
                        file_obj=uploaded_file,
                        filename=uploaded_file.name or "unnamed",
                        display_name=display_name,
                        content_type=uploaded_file.content_type or "application/octet-stream",
                        actor_id=_actor(request).pk,
                    )
            except CTFPermissionError:
                _raise_forbidden()
            except CTFNotFoundError:
                _raise_not_found("File or challenge not found.")
            except (CTFStateError, CTFValidationError):
                _raise_bad_request("Invalid file request.")
            return Response(
                {
                    "id": str(challenge_file.id),
                    "filename": challenge_file.filename,
                    "display_name": challenge_file.display_name,
                    "file_size_bytes": challenge_file.file_size_bytes,
                    "file_size_display": challenge_file.file_size_display,
                },
                status=status.HTTP_201_CREATED,
            )
        except _CtfApiError as exc:
            return exc.to_response(request)


class ChallengeFileDeleteView(APIView):
    """Delete a challenge file attachment."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses=DeleteSuccessSerializer)
    def post(self, request: Request, file_id: UUID) -> Response:
        """Resolve the file, enforce ownership, and delete via the service."""
        from ctf.models import CTFChallengeFile
        from ctf.services.attachment import remove_challenge_file

        try:
            try:
                challenge_file = CTFChallengeFile.objects.select_related("challenge__event").get(pk=file_id)
            except CTFChallengeFile.DoesNotExist:
                _raise_not_found("File not found")
            if not _actor_may_manage(request, challenge_file.challenge.event, None):
                _raise_forbidden()
            return _delete_via_service(request, remove_challenge_file, file_id, operation="file.delete")
        except _CtfApiError as exc:
            return exc.to_response(request)


class FileDownloadView(APIView):
    """Return a presigned download URL for a challenge file (role-based access)."""

    permission_classes = CTF_ROLE_PERMISSIONS
    required_read_scopes = _EVENT_OR_PLAY_READ

    @extend_schema(responses=FileDownloadResponseSerializer)
    def get(self, request: Request, file_id: UUID) -> Response:
        """Resolve the file, apply the fine-grained access policy, and issue a URL."""
        from ctf.exceptions import CTFNotFoundError
        from ctf.models import CTFChallengeFile
        from ctf.services.attachment import get_download_url

        try:
            try:
                challenge_file = CTFChallengeFile.objects.select_related("challenge__event").get(pk=file_id)
            except CTFChallengeFile.DoesNotExist:
                _raise_not_found("File not found")
            if not _is_file_download_allowed(request, challenge_file):
                _raise_forbidden()
            try:
                url, filename = get_download_url(file_id)
            except CTFNotFoundError:
                _raise_not_found("File or challenge not found.")
            return Response({"url": url, "filename": filename})
        except _CtfApiError as exc:
            return exc.to_response(request)


class ChallengePrerequisitesView(APIView):
    """List an owned challenge's prerequisites (GET) or add one (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=PrerequisiteListResponseSerializer)
    def get(self, request: Request, challenge_id: UUID) -> Response:
        """Return the prerequisites for an owned challenge."""
        from ctf.services.challenge import get_prerequisites

        try:
            _resolve_owned_challenge(request, challenge_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        data = [
            {
                "id": str(p.id),
                "required_challenge_id": str(p.required_challenge_id),
                "required_challenge_name": p.required_challenge.name,
                "required_challenge_category": p.required_challenge.category,
                "required_challenge_points": p.required_challenge.points,
            }
            for p in get_prerequisites(challenge_id)
        ]
        return Response({"prerequisites": data})

    @extend_schema(request=PrerequisiteWriteSerializer, responses={201: PrerequisiteCreateResultSerializer})
    @audit_admin_event_mutation("prerequisite.create", action=AuditAction.CREATE)
    def post(self, request: Request, challenge_id: UUID) -> Response:
        """Add a prerequisite to an owned challenge."""
        from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
        from ctf.services.challenge import add_prerequisite

        try:
            _resolve_owned_challenge(request, challenge_id)
            serializer = PrerequisiteWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                prereq = add_prerequisite(
                    challenge_id, serializer.validated_data["required_challenge_id"], actor_id=_actor(request).pk
                )
            except CTFPermissionError:
                _raise_forbidden()
            except CTFNotFoundError:
                _raise_not_found("Challenge not found.")
            except (CTFStateError, CTFValidationError):
                _raise_bad_request("Invalid prerequisite request.")
            return Response(
                {
                    "id": str(prereq.id),
                    "required_challenge_id": str(prereq.required_challenge_id),
                    "required_challenge_name": prereq.required_challenge.name,
                },
                status=status.HTTP_201_CREATED,
            )
        except _CtfApiError as exc:
            return exc.to_response(request)


class PrerequisiteDeleteView(APIView):
    """Remove a challenge prerequisite."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses=DeleteSuccessSerializer)
    def post(self, request: Request, prerequisite_id: UUID) -> Response:
        """Resolve the prerequisite, enforce ownership, and delete via the service."""
        from ctf.models import CTFChallengePrerequisite
        from ctf.services.challenge import remove_prerequisite

        try:
            try:
                prereq = CTFChallengePrerequisite.objects.select_related("challenge__event").get(pk=prerequisite_id)
            except CTFChallengePrerequisite.DoesNotExist:
                _raise_not_found("Prerequisite not found")
            if not _actor_may_manage(request, prereq.challenge.event, None):
                _raise_forbidden()
            return _delete_via_service(request, remove_prerequisite, prerequisite_id, operation="prerequisite.delete")
        except _CtfApiError as exc:
            return exc.to_response(request)
