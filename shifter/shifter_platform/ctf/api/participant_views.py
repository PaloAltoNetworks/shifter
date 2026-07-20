"""Canonical DRF participant read views for the CTF workspace SPA.

These are the typed participant-self reads (``/api/v1/ctf/me/*``) that the legacy
Django template views never exposed as JSON. Each view resolves the participant
with the same event-scoped policy the legacy participant pages use
(``get_user_role(actor).active_ctf_event`` then ``get_participant_by_user``,
codex #765/#768/#769) so a multi-event user always acts as the correct
participant, then returns a participant-safe projection from
:mod:`ctf.api.projections`. Authorization and token scopes are enforced by the
shared ``ctf.api._base`` participant permission set; these views add no new
authority.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api import projections
from ctf.api._base import CTF_PARTICIPANT_PERMISSIONS, _CtfApiError, ctf_actor_user
from ctf.api.serializers import (
    EventPagesResponseSerializer,
    ParticipantAnnouncementListSerializer,
    ParticipantChallengeDetailSerializer,
    ParticipantChallengeListItemSerializer,
    ParticipantCurrentEventSerializer,
    ParticipantProfileSerializer,
    ParticipantTeamSerializer,
    ProfileUpdateRequestSerializer,
    UsernameChangeRequestSerializer,
)
from shared.api.errors import api_error_response
from shared.api_tokens import scopes

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFParticipant

_NO_ACTIVE_EVENT = "No active CTF event for this participant."
_FORBIDDEN = "Forbidden"
_CHALLENGE_NOT_FOUND = "Challenge not found."
_PLAY_READ = (scopes.CTF_PLAY_READ,)
_PLAY_WRITE = (scopes.CTF_PLAY_WRITE,)


def _resolve_active_participant(request: Request) -> CTFParticipant | None:
    """Resolve the participant for the actor's active event, or ``None``.

    Mirrors ``ctf.views._access._get_active_participant``: the participant is
    scoped to ``get_user_role(actor).active_ctf_event`` rather than an unscoped
    first-row pick, so a user enrolled in several events acts as the right one.
    """
    actor = ctf_actor_user(request)
    if actor is None:
        return None
    from ctf.bridges import get_user_role
    from ctf.services.participant import get_viewing_participant_by_user

    role = get_user_role(actor)
    if role.active_ctf_event is None:
        return None
    # View-predicate resolution (CTF-609): disqualified participants read the
    # me-surface; mutation services re-assert compete eligibility themselves.
    return get_viewing_participant_by_user(actor, event_id=role.active_ctf_event.id)


class ParticipantCurrentEventView(APIView):
    """Return the participant's current event and their own participant state."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_read_scopes = _PLAY_READ

    @extend_schema(responses=ParticipantCurrentEventSerializer)
    def get(self, request: Request) -> Response:
        """Return the current-event projection, or 404 when there is none."""
        participant = _resolve_active_participant(request)
        if participant is None:
            return api_error_response(
                code="not_found",
                message=_NO_ACTIVE_EVENT,
                status_code=status.HTTP_404_NOT_FOUND,
                request=request,
            )
        return Response(ParticipantCurrentEventSerializer(projections.participant_current_event(participant)).data)


class ParticipantChallengeListView(APIView):
    """Return the participant-safe browse list of available challenges."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_read_scopes = _PLAY_READ

    @extend_schema(responses=ParticipantChallengeListItemSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Return available challenges with this participant's solve state."""
        participant = _resolve_active_participant(request)
        if participant is None:
            return api_error_response(
                code="not_found",
                message=_NO_ACTIVE_EVENT,
                status_code=status.HTTP_404_NOT_FOUND,
                request=request,
            )
        data = projections.participant_challenge_list(participant)
        return Response(ParticipantChallengeListItemSerializer(data, many=True).data)


class ParticipantTeamView(APIView):
    """Return the participant's own team and members, or 404 when unteamed."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_read_scopes = _PLAY_READ

    @extend_schema(responses=ParticipantTeamSerializer)
    def get(self, request: Request) -> Response:
        """Return the participant's team projection, or 404 for solo/unteamed."""
        participant = _resolve_active_participant(request)
        if participant is None:
            return api_error_response(
                code="not_found",
                message=_NO_ACTIVE_EVENT,
                status_code=status.HTTP_404_NOT_FOUND,
                request=request,
            )
        team = projections.participant_team(participant)
        if team is None:
            return api_error_response(
                code="not_found",
                message="Participant is not on a team.",
                status_code=status.HTTP_404_NOT_FOUND,
                request=request,
            )
        return Response(ParticipantTeamSerializer(team).data)


class ParticipantChallengeDetailView(APIView):
    """Return the participant-safe detail projection for one challenge."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_read_scopes = _PLAY_READ

    @extend_schema(responses=ParticipantChallengeDetailSerializer)
    def get(self, request: Request, challenge_id: UUID) -> Response:
        """Return the challenge detail, or 404/403 per the read-availability policy."""
        # Boundary failures raise ``_CtfApiError``, which the single ``except``
        # renders to the exact legacy status code and message.
        from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
        from ctf.services.challenge import assert_challenge_readable_for_participant, get_challenge
        from ctf.services.participant import get_participant_by_user

        try:
            actor = ctf_actor_user(request)
            if actor is None:
                raise _CtfApiError(code="permission_denied", message=_FORBIDDEN, status_code=status.HTTP_403_FORBIDDEN)
            try:
                challenge = get_challenge(challenge_id)
            except CTFNotFoundError as exc:
                raise _CtfApiError(
                    code="not_found", message=_CHALLENGE_NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND
                ) from exc
            # Event-scoped resolution (codex 765/768/769): a multi-event user must be
            # looked up against THIS challenge's event, never an arbitrary first row.
            participant = get_participant_by_user(actor, event_id=challenge.event_id)
            if participant is None:
                raise _CtfApiError(code="permission_denied", message=_FORBIDDEN, status_code=status.HTTP_403_FORBIDDEN)
            # Read-availability policy: blocks hidden/unreleased/prerequisite-gated
            # content while still allowing locked and ended/archived review.
            try:
                assert_challenge_readable_for_participant(participant, challenge)
            except (CTFStateError, CTFValidationError) as exc:
                raise _CtfApiError(
                    code="permission_denied", message=_FORBIDDEN, status_code=status.HTTP_403_FORBIDDEN
                ) from exc
            return Response(
                ParticipantChallengeDetailSerializer(
                    projections.participant_challenge_detail(participant, challenge)
                ).data
            )
        except _CtfApiError as exc:
            return exc.to_response(request)


class ParticipantProfileView(APIView):
    """Read (GET) or partially update (PATCH) the participant's own profile (CTF-610)."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_read_scopes = _PLAY_READ
    required_write_scopes = _PLAY_WRITE

    @extend_schema(responses=ParticipantProfileSerializer)
    def get(self, request: Request) -> Response:
        """Return the event-scoped profile projection."""
        participant = _resolve_active_participant(request)
        if participant is None:
            return _no_active_event_response(request)
        return Response(ParticipantProfileSerializer(projections.participant_profile(participant)).data)

    @extend_schema(request=ProfileUpdateRequestSerializer, responses=ParticipantProfileSerializer)
    def patch(self, request: Request) -> Response:
        """Update display name and/or affiliation; omitted fields stay put."""
        from ctf.exceptions import CTFValidationError
        from ctf.services.participant import update_own_profile

        participant = _resolve_active_participant(request)
        actor = ctf_actor_user(request)
        if participant is None or actor is None:
            return _no_active_event_response(request)
        serializer = ProfileUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = update_own_profile(
                participant.id,
                actor=actor,
                name=serializer.validated_data.get("name"),
                affiliation=serializer.validated_data.get("affiliation"),
            )
        except CTFValidationError as exc:
            return api_error_response(
                code="invalid", message=str(exc), status_code=status.HTTP_400_BAD_REQUEST, request=request
            )
        return Response(ParticipantProfileSerializer(projections.participant_profile(updated)).data)


class ParticipantUsernameSelfView(APIView):
    """Change the participant's own login username (POST, #1593)."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_write_scopes = _PLAY_WRITE

    @extend_schema(request=UsernameChangeRequestSerializer, responses=ParticipantProfileSerializer)
    def post(self, request: Request) -> Response:
        """Validate, apply, and audit the self-rename; return the fresh profile."""
        from ctf.exceptions import CTFValidationError
        from ctf.services.participant import rename_own_participant_username

        participant = _resolve_active_participant(request)
        actor = ctf_actor_user(request)
        if participant is None or actor is None:
            return _no_active_event_response(request)
        serializer = UsernameChangeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = rename_own_participant_username(
                participant.id,
                serializer.validated_data["username"],
                actor=actor,
            )
        except CTFValidationError as exc:
            return api_error_response(
                code="invalid", message=str(exc), status_code=status.HTTP_400_BAD_REQUEST, request=request
            )
        return Response(ParticipantProfileSerializer(projections.participant_profile(updated)).data)


def _no_active_event_response(request: Request) -> Response:
    """Shared 404 envelope for me-surface views without an active participant."""
    return api_error_response(
        code="not_found",
        message=_NO_ACTIVE_EVENT,
        status_code=status.HTTP_404_NOT_FOUND,
        request=request,
    )


class ParticipantAnnouncementsView(APIView):
    """List sent announcements for the participant's active event (GET, CTF-803)."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_read_scopes = _PLAY_READ

    @extend_schema(responses=ParticipantAnnouncementListSerializer)
    def get(self, request: Request) -> Response:
        """Return sent announcements, newest first."""
        from ctf.enums import NotificationStatus, NotificationType
        from ctf.models import CTFNotification

        participant = _resolve_active_participant(request)
        if participant is None:
            return _no_active_event_response(request)
        announcements = CTFNotification.objects.filter(
            event_id=participant.event_id,
            notification_type=NotificationType.ANNOUNCEMENT.value,
            status=NotificationStatus.SENT.value,
        ).order_by("-sent_at")[:50]
        data = [
            {
                "id": str(a.id),
                "subject": a.subject,
                "body": a.body,
                "sent_at": a.sent_at,
            }
            for a in announcements
        ]
        return Response({"announcements": data})


class ParticipantPagesView(APIView):
    """List the event's custom informational pages (GET, CTF-1303)."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_read_scopes = _PLAY_READ

    @extend_schema(responses=EventPagesResponseSerializer)
    def get(self, request: Request) -> Response:
        """Return the active event's pages in display order."""
        from ctf.models import CTFEventPage

        participant = _resolve_active_participant(request)
        if participant is None:
            return _no_active_event_response(request)
        pages = CTFEventPage.objects.filter(event_id=participant.event_id, deleted_at__isnull=True)
        return Response(
            {
                "pages": [
                    {"id": str(p.id), "title": p.title, "slug": p.slug, "body": p.body, "order": p.order} for p in pages
                ]
            }
        )
