"""Organizer challenge views for the canonical CTF API (challenges, flags, hints)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._base import (
    _EVENT_READ,
    _EVENT_WRITE,
    _INVALID_CHALLENGE,
    _actor,
    _challenge_detail_payload,
    _delete_via_service,
    _raise_bad_request,
    _raise_forbidden,
    _raise_not_found,
    _resolve_owned_challenge,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    ChallengeHintSerializer,
    ChallengeListResponseSerializer,
    ChallengeMutationResultSerializer,
    ChallengeWriteSerializer,
    DeleteSuccessSerializer,
    FlagCreateResultSerializer,
    FlagWriteSerializer,
    HintListResponseSerializer,
    HintWriteSerializer,
    OrganizerChallengeDetailSerializer,
)

if TYPE_CHECKING:
    from uuid import UUID


class ChallengeListView(APIView):
    """List an event's challenges (GET) or create one (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=ChallengeListResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the challenges belonging to an owned event."""
        from ctf.exceptions import CTFPermissionError
        from ctf.services import list_challenges_for_event

        try:
            _resolve_owned_event(request, event_id)
            try:
                challenges = list_challenges_for_event(event_id, actor_id=_actor(request).pk).prefetch_related(
                    "tags", "topics"
                )
            except CTFPermissionError:
                _raise_forbidden()
            data = [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "category": c.category,
                    "points": c.points,
                    "difficulty": c.difficulty,
                    "order": c.order,
                    "tags": list(c.tags.values_list("name", flat=True)),
                    "topics": list(c.topics.values_list("name", flat=True)),
                }
                for c in challenges
            ]
            return Response({"challenges": data})
        except _CtfApiError as exc:
            return exc.to_response(request)

    @extend_schema(request=ChallengeWriteSerializer, responses={201: ChallengeMutationResultSerializer})
    def post(self, request: Request, event_id: UUID) -> Response:
        """Create a challenge under an owned event."""
        from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
        from ctf.services import create_challenge

        try:
            _resolve_owned_event(request, event_id)
            serializer = ChallengeWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                challenge = create_challenge(event_id, dict(serializer.validated_data), actor_id=_actor(request).pk)
            except CTFPermissionError:
                _raise_forbidden()
            except CTFNotFoundError:
                _raise_not_found("Challenge not found.")
            except (CTFValidationError, CTFStateError):
                _raise_bad_request(_INVALID_CHALLENGE)
            return Response(
                {
                    "id": str(challenge.id),
                    "name": challenge.name,
                    "category": challenge.category,
                    "points": challenge.points,
                },
                status=status.HTTP_201_CREATED,
            )
        except _CtfApiError as exc:
            return exc.to_response(request)


class ChallengeDetailView(APIView):
    """Get, update, or delete a single owned challenge."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=OrganizerChallengeDetailSerializer)
    def get(self, request: Request, challenge_id: UUID) -> Response:
        """Return the full organizer challenge detail projection."""
        try:
            challenge = _resolve_owned_challenge(request, challenge_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        return Response(_challenge_detail_payload(challenge))

    @extend_schema(request=ChallengeWriteSerializer, responses=ChallengeMutationResultSerializer)
    def put(self, request: Request, challenge_id: UUID) -> Response:
        """Update mutable fields of an owned challenge."""
        from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
        from ctf.services import update_challenge

        try:
            _resolve_owned_challenge(request, challenge_id)
            serializer = ChallengeWriteSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            try:
                updated = update_challenge(challenge_id, dict(serializer.validated_data), actor_id=_actor(request).pk)
            except CTFPermissionError:
                _raise_forbidden()
            except (CTFNotFoundError, CTFValidationError, CTFStateError):
                _raise_bad_request(_INVALID_CHALLENGE)
            return Response(
                {
                    "id": str(updated.id),
                    "name": updated.name,
                    "category": updated.category,
                    "points": updated.points,
                }
            )
        except _CtfApiError as exc:
            return exc.to_response(request)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, challenge_id: UUID) -> Response:
        """Delete an owned challenge."""
        from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError
        from ctf.services import delete_challenge

        try:
            _resolve_owned_challenge(request, challenge_id)
            try:
                delete_challenge(challenge_id, actor_id=_actor(request).pk)
            except CTFPermissionError:
                _raise_forbidden()
            except (CTFNotFoundError, CTFStateError):
                _raise_bad_request(_INVALID_CHALLENGE)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except _CtfApiError as exc:
            return exc.to_response(request)


class AddFlagView(APIView):
    """Add a flag to an owned challenge."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=FlagWriteSerializer, responses={201: FlagCreateResultSerializer})
    def post(self, request: Request, challenge_id: UUID) -> Response:
        """Validate the flag body and create the flag record."""
        from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
        from ctf.services.challenge import add_flag

        try:
            _resolve_owned_challenge(request, challenge_id)
            serializer = FlagWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            flag_value = data["flag"].strip()
            flag_type = data["flag_type"]
            # Flag value is only required for static and regex types.
            if flag_type in ("static", "regex") and not flag_value:
                _raise_bad_request("Invalid flag request.")
            flag_data = {
                "flag": flag_value,
                "flag_type": flag_type,
                "case_sensitive": data["case_sensitive"],
                "order": data["order"],
                "validator_config": data["validator_config"],
            }
            try:
                flag_obj = add_flag(challenge_id, flag_data, actor_id=_actor(request).pk)
            except CTFPermissionError:
                _raise_forbidden()
            except CTFNotFoundError:
                _raise_not_found("Flag or challenge not found.")
            except (CTFStateError, CTFValidationError):
                _raise_bad_request("Invalid flag request.")
            response_data: dict[str, object] = {
                "id": str(flag_obj.id),
                "flag_type": flag_obj.flag_type,
                "case_sensitive": flag_obj.case_sensitive,
                "order": flag_obj.order,
            }
            if flag_obj.validator_config:
                response_data["validator_config"] = flag_obj.validator_config
            return Response(response_data, status=status.HTTP_201_CREATED)
        except _CtfApiError as exc:
            return exc.to_response(request)


class RemoveFlagView(APIView):
    """Remove a flag from an owned challenge."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses=DeleteSuccessSerializer)
    def post(self, request: Request, flag_id: UUID) -> Response:
        """Resolve the flag, enforce ownership, and delete via the service."""
        from ctf.models import CTFFlag
        from ctf.services.challenge import remove_flag

        try:
            try:
                flag_obj = CTFFlag.objects.select_related("challenge__event").get(pk=flag_id)
            except CTFFlag.DoesNotExist:
                _raise_not_found("Flag not found")
            if flag_obj.challenge.event.created_by_id != _actor(request).pk:
                _raise_forbidden()
            return _delete_via_service(request, remove_flag, flag_id)
        except _CtfApiError as exc:
            return exc.to_response(request)


class ChallengeHintsView(APIView):
    """List an owned challenge's hints (GET) or add one (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=HintListResponseSerializer)
    def get(self, request: Request, challenge_id: UUID) -> Response:
        """Return the hints for an owned challenge."""
        from ctf.services.hint import get_hints

        try:
            _resolve_owned_challenge(request, challenge_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        data = [
            {"id": str(h.id), "text": h.text, "penalty": h.penalty, "order": h.order} for h in get_hints(challenge_id)
        ]
        return Response({"hints": data})

    @extend_schema(request=HintWriteSerializer, responses={201: ChallengeHintSerializer})
    def post(self, request: Request, challenge_id: UUID) -> Response:
        """Add a hint to an owned challenge."""
        from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
        from ctf.services.hint import add_hint

        try:
            _resolve_owned_challenge(request, challenge_id)
            serializer = HintWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                hint = add_hint(challenge_id, dict(serializer.validated_data), actor_id=_actor(request).pk)
            except CTFPermissionError:
                _raise_forbidden()
            except (CTFNotFoundError, CTFStateError, CTFValidationError):
                _raise_bad_request("Could not process hint request.")
            return Response(
                {"id": str(hint.id), "text": hint.text, "penalty": hint.penalty, "order": hint.order},
                status=status.HTTP_201_CREATED,
            )
        except _CtfApiError as exc:
            return exc.to_response(request)


class HintDeleteView(APIView):
    """Delete a hint from an owned challenge."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, hint_id: UUID) -> Response:
        """Delete a hint, mapping service exceptions to the shared envelope."""
        from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError
        from ctf.services.hint import remove_hint

        try:
            try:
                remove_hint(hint_id, actor_id=_actor(request).pk)
            except CTFPermissionError:
                _raise_forbidden()
            except CTFNotFoundError:
                _raise_not_found("Hint or challenge not found.")
            except CTFStateError:
                _raise_bad_request("Could not process hint request.")
            return Response(status=status.HTTP_204_NO_CONTENT)
        except _CtfApiError as exc:
            return exc.to_response(request)
