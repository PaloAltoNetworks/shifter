"""Organizer managed-content refresh view (issue #1971).

A refresh reconciles a bundle-managed event to the currently configured,
digest-pinned revision of its own scenario. It is a *content* operation, not an
event-lifecycle transition, so it lives apart from ``lifecycle.py`` and never
shares the ``EventLifecycleRequestSerializer``.

The view resolves and validates the configured bundle before delegating to the
CTF-owned reconciler; no object download or parse happens under a database lock.
Server-side reason codes distinguish operator actions; content coordinates,
flag material, and provider text never enter the response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._audit import (
    admin_external_audit,
)
from ctf.api.organizer._base import (
    _EVENT_WRITE,
    _actor,
    _raise_bad_request,
    _raise_forbidden,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    EventContentRefreshRequestSerializer,
    EventContentRefreshResultSerializer,
)
from ctf.enums import EventCapability

if TYPE_CHECKING:
    from typing import NoReturn
    from uuid import UUID

    from ctf.models import CTFEvent
    from ctf.services.content_refresh import ContentRefreshResult

# Bounded, value-free operator hints per stable server reason code. Field
# categories may explain an unsafe diff; content values never do.
_REFRESH_CONFLICT_MESSAGES = {
    "CTF_CONTENT_REFRESH_CONFLICT": "Event content revision changed; reload the event and retry.",
    "CTF_CONTENT_REFRESH_STATE": "This event's state does not permit a content refresh.",
    "CTF_CONTENT_SCENARIO_MISMATCH": "The configured content does not match this event's scenario.",
}


class EventContentRefreshView(APIView):
    """Refresh an owned managed event to its configured content revision (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(
        request=EventContentRefreshRequestSerializer,
        responses=EventContentRefreshResultSerializer,
    )
    def post(self, request: Request, event_id: UUID) -> Response:
        """Validate the fence, reconcile to the configured revision, return the outcome."""
        try:
            event = _resolve_owned_event(request, event_id, capability=EventCapability.CONTENT)
            serializer = EventContentRefreshRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            expected = serializer.validated_data["expected_current_digest"]
            # Non-rollbackable content reconciliation: record override intent
            # before the first side effect, then the correlated outcome.
            with admin_external_audit(request, "content.refresh"):
                result = self._refresh(event, expected, actor_id=_actor(request).pk)
            return Response(
                {
                    "event_id": str(event.id),
                    "outcome": result.outcome,
                    "changed_categories": list(result.changed_categories),
                    "challenge_count": result.challenge_count,
                    "flag_count": result.flag_count,
                    "hint_count": result.hint_count,
                    "prerequisite_count": result.prerequisite_count,
                }
            )
        except _CtfApiError as exc:
            return exc.to_response(request)

    @staticmethod
    def _refresh(event: CTFEvent, expected_current_digest: str, *, actor_id: int) -> ContentRefreshResult:
        """Resolve configured content and run the reconciler, mapping errors to envelopes."""
        from ctf.exceptions import CTFPermissionError, CTFStateError, CTFValidationError
        from ctf.services import refresh_event_ctf_content, resolve_scenario_ctf_content

        try:
            resolved = resolve_scenario_ctf_content(event.scenario_id)
        except CTFValidationError:
            _raise_conflict_code(
                "CTF_CONTENT_REFRESH_STATE",
                "This event's configured content could not be resolved.",
            )
        if resolved is None:
            _raise_conflict_code(
                "CTF_CONTENT_REFRESH_STATE",
                "This event's scenario has no configured content to refresh.",
            )

        try:
            return refresh_event_ctf_content(
                event.pk,
                resolved,
                actor_id=actor_id,
                expected_current_digest=expected_current_digest,
            )
        except CTFPermissionError:
            _raise_forbidden()
        except CTFStateError as exc:
            if exc.code == "CTF_CONTENT_REFRESH_UNSAFE":
                categories = ", ".join(exc.details.get("unsafe_categories", [])) or "structure or scoring"
                _raise_conflict_code(
                    exc.code,
                    f"A live event refresh cannot change: {categories}. Pause is not enough; create a new event.",
                )
            _raise_conflict_code(
                exc.code,
                _REFRESH_CONFLICT_MESSAGES.get(exc.code, "The content refresh could not be applied."),
            )
        except CTFValidationError:
            _raise_bad_request("Invalid content refresh request.")


def _raise_conflict_code(code: str, message: str) -> NoReturn:
    """Raise a 409 envelope carrying a stable server reason code."""
    raise _CtfApiError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)
