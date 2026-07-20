"""Participant play views for the canonical CTF API (rate, submit, hints, submissions).

These endpoints carry participant permissions but live in the organizer package
alongside the shared resolution helpers they reuse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_PARTICIPANT_PERMISSIONS, _CtfApiError
from ctf.api.organizer._base import (
    _CHALLENGE_ACTION_FAILED,
    _CHALLENGE_OR_PARTICIPANT_NOT_FOUND,
    _NO_MORE_HINTS,
    _PARTICIPANT_NOT_FOUND,
    _PLAY_READ,
    _PLAY_WRITE,
    _raise_bad_request,
    _raise_not_found,
    _resolve_active_participant,
    _resolve_challenge_participant,
)
from ctf.api.serializers import (
    RateChallengeRequestSerializer,
    RateChallengeResultSerializer,
    SubmissionListResponseSerializer,
    SubmitFlagRequestSerializer,
    SubmitFlagResultSerializer,
    UseHintRequestSerializer,
    UseHintResultSerializer,
)

if TYPE_CHECKING:
    from typing import NoReturn
    from uuid import UUID

    from ctf.models import CTFParticipant


class RateChallengeView(APIView):
    """Record a participant's rating for a challenge (1-5)."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_write_scopes = _PLAY_WRITE

    @extend_schema(request=RateChallengeRequestSerializer, responses=RateChallengeResultSerializer)
    def post(self, request: Request, challenge_id: UUID) -> Response:
        """Validate the rating and record it for the resolved participant."""
        from ctf.exceptions import CTFNotFoundError, CTFValidationError
        from ctf.services.submission import rate_challenge

        try:
            participant = _resolve_challenge_participant(request, challenge_id)
            serializer = RateChallengeRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                rating = rate_challenge(participant.id, challenge_id, serializer.validated_data["value"])
            except CTFNotFoundError:
                _raise_not_found(_CHALLENGE_OR_PARTICIPANT_NOT_FOUND)
            except CTFValidationError:
                _raise_bad_request(_CHALLENGE_ACTION_FAILED)
            return Response({"value": rating.value, "challenge_id": str(challenge_id)})
        except _CtfApiError as exc:
            return exc.to_response(request)


class SubmitFlagView(APIView):
    """Submit a flag for a challenge (participant)."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_write_scopes = _PLAY_WRITE

    @extend_schema(request=SubmitFlagRequestSerializer, responses=SubmitFlagResultSerializer)
    def post(self, request: Request, challenge_id: UUID) -> Response:
        """Validate the flag body and submit it for the resolved participant."""
        from shared.audit import get_client_ip

        try:
            participant = _resolve_challenge_participant(request, challenge_id)
            serializer = SubmitFlagRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            flag = (serializer.validated_data.get("flag") or "").strip()
            if not flag:
                _raise_bad_request(_CHALLENGE_ACTION_FAILED)
            return self._submit(request, participant, challenge_id, flag, get_client_ip(request))
        except _CtfApiError as exc:
            return exc.to_response(request)

    def _submit(
        self,
        request: Request,
        participant: CTFParticipant,
        challenge_id: UUID,
        flag: str,
        ip_address: str | None,
    ) -> Response:
        """Call the submission service and render the scored result or raise a mapped error."""
        from ctf.exceptions import CTFNotFoundError, CTFRateLimitError, CTFStateError, CTFValidationError
        from ctf.services.scoring import calculate_score, get_participant_rank
        from ctf.services.submission import submit_flag

        try:
            submission = submit_flag(participant.id, challenge_id, flag, ip_address=ip_address)
        except CTFNotFoundError:
            _raise_not_found(_CHALLENGE_OR_PARTICIPANT_NOT_FOUND)
        except (CTFValidationError, CTFStateError):
            _raise_bad_request(_CHALLENGE_ACTION_FAILED)
        except CTFRateLimitError as exc:
            self._raise_rate_limited(exc)
        score = calculate_score(participant.id)
        rank = get_participant_rank(participant.id)
        return Response(
            {
                "correct": submission.is_correct,
                "points_awarded": submission.points_awarded,
                "attempt_number": submission.attempt_number,
                "score": score,
                "rank": rank,
                "message": "Correct!" if submission.is_correct else "Incorrect flag.",
            }
        )

    @staticmethod
    def _raise_rate_limited(exc: object) -> NoReturn:
        """Raise the 429 envelope, replicating the legacy ``Retry-After`` header."""
        retry_after = getattr(exc, "details", {}).get("retry_after_seconds")
        headers = {"Retry-After": str(int(retry_after))} if retry_after else None
        raise _CtfApiError(
            code="throttled",
            message="Rate limit exceeded.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers=headers,
        )


class UseHintView(APIView):
    """Unlock the next hint (or a specific hint) for a challenge (participant)."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_write_scopes = _PLAY_WRITE

    @extend_schema(request=UseHintRequestSerializer, responses=UseHintResultSerializer)
    def post(self, request: Request, challenge_id: UUID) -> Response:
        """Resolve which hint to unlock, then unlock it for the resolved participant."""
        try:
            participant = _resolve_challenge_participant(request, challenge_id)
            hint_id = self._resolve_hint_to_unlock(request, participant, challenge_id)
            return self._unlock(participant, challenge_id, hint_id)
        except _CtfApiError as exc:
            return exc.to_response(request)

    def _resolve_hint_to_unlock(self, request: Request, participant: CTFParticipant, challenge_id: UUID) -> UUID:
        """Return the hint UUID to unlock, or raise a 400 ``_CtfApiError``.

        Mirrors ``ctf.views.api.play._resolve_hint_to_unlock``: an explicit
        ``hint_id`` (even null/malformed) is parsed to a UUID or 400; an empty
        body falls through to the next not-yet-unlocked hint.
        """
        body = request.data if isinstance(request.data, dict) else None
        if body is None:
            _raise_bad_request(_CHALLENGE_ACTION_FAILED)
        if "hint_id" in body:
            return self._parse_explicit_hint_id(body)
        return self._resolve_next_unlockable_hint(participant, challenge_id)

    @staticmethod
    def _parse_explicit_hint_id(body: dict[str, object]) -> UUID:
        """Parse an explicit ``hint_id`` body field, returning the UUID or raising a 400."""
        from ctf.views._parsing import _BodyUUIDError, _parse_body_uuid

        try:
            return _parse_body_uuid(body.get("hint_id"), "hint_id")
        except _BodyUUIDError:
            _raise_bad_request(_CHALLENGE_ACTION_FAILED)

    @staticmethod
    def _resolve_next_unlockable_hint(participant: CTFParticipant, challenge_id: UUID) -> UUID:
        """Return the first not-yet-unlocked hint's UUID, or raise 400 when none remain."""
        from ctf.services.hint import get_hints, get_unlocked_hints

        unlocked_ids = {h.id for h in get_unlocked_hints(participant.id, challenge_id)}
        next_hint = next((h for h in get_hints(challenge_id) if h.id not in unlocked_ids), None)
        if not next_hint:
            _raise_bad_request(_NO_MORE_HINTS)
        return next_hint.id

    @staticmethod
    def _unlock(participant: CTFParticipant, challenge_id: UUID, hint_id: UUID) -> Response:
        """Unlock the resolved hint, returning the result payload or raising a mapped error."""
        from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
        from ctf.services.hint import use_hint

        try:
            result = use_hint(participant.id, hint_id, expected_challenge_id=challenge_id)
        except CTFNotFoundError:
            _raise_not_found(_CHALLENGE_OR_PARTICIPANT_NOT_FOUND)
        except (CTFValidationError, CTFStateError):
            _raise_bad_request(_CHALLENGE_ACTION_FAILED)
        return Response(result)


class SubmissionListView(APIView):
    """List the requesting participant's own submissions."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_read_scopes = _PLAY_READ

    @extend_schema(responses=SubmissionListResponseSerializer)
    def get(self, request: Request) -> Response:
        """Return the active participant's own submission history."""
        from ctf.services.submission import get_participant_submissions

        try:
            participant = _resolve_active_participant(request)
            if participant is None:
                _raise_not_found(_PARTICIPANT_NOT_FOUND)
            submissions = get_participant_submissions(participant.id)
            data = [
                {
                    "id": str(s.id),
                    "challenge_id": str(s.challenge_id),
                    "challenge_name": s.challenge.name,
                    "is_correct": s.is_correct,
                    "points_awarded": s.points_awarded,
                    "attempt_number": s.attempt_number,
                    "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
                }
                for s in submissions.select_related("challenge")
            ]
            return Response({"submissions": data, "total": len(data)})
        except _CtfApiError as exc:
            return exc.to_response(request)
