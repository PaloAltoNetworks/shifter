"""Organizer event-lifecycle and scheduler-control views (CTF-007, #526, CTF-1003).

Lifecycle transitions delegate to the authoritative ``ctf.services.event``
state machine; these views own only HTTP shape and ownership resolution.
Lifecycle, task, and cleanup control require the ``lifecycle`` capability: the
owner and full co-organizers hold it; moderators and judges do not (#1922).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._audit import (
    _audit_admin_mutation,
)
from ctf.api.organizer._base import (
    _EVENT_READ,
    _EVENT_WRITE,
    _actor,
    _event_authority,
    _raise_bad_request,
    _raise_conflict,
    _raise_not_found,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    CleanupControlRequestSerializer,
    EventLifecycleRequestSerializer,
    EventMutationResultSerializer,
    ScheduledTaskListResponseSerializer,
    ScheduledTaskSerializer,
)
from ctf.enums import EventCapability
from ctf.models import CTFScheduledTask

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFEvent, CTFScheduledTask

logger = logging.getLogger(__name__)


class EventLifecycleView(APIView):
    """Apply one lifecycle transition to an owned event (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=EventLifecycleRequestSerializer, responses=EventMutationResultSerializer)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Validate the action, run the state machine, and return the new status."""
        from django.db import transaction

        try:
            event = _resolve_owned_event(request, event_id, capability=EventCapability.LIFECYCLE)
            source = _event_authority(request, event, EventCapability.LIFECYCLE)
            serializer = EventLifecycleRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            action = serializer.validated_data["action"]
            # Database-only state-machine transition: transition and override
            # audit share one transaction (ADR-052-R4). The service asserts the
            # lifecycle capability again (defense in depth, #1922).
            with transaction.atomic():
                self._apply(event, action, actor_id=_actor(request).pk)
                _audit_admin_mutation(request, event, source, f"event.lifecycle.{action}")
            event.refresh_from_db()
            return Response({"id": str(event.id), "name": event.name, "status": event.status})
        except _CtfApiError as exc:
            return exc.to_response(request)

    @staticmethod
    def _apply(event: CTFEvent, action: str, *, actor_id: int) -> None:
        """Run the transition via the service (asserts lifecycle capability); refusal is a 409."""
        from ctf.services.event import apply_event_lifecycle_transition

        if not apply_event_lifecycle_transition(event, action, actor_id=actor_id):
            _raise_conflict(f"Event cannot {action.replace('_', ' ')} from status {event.status}")


def _task_payload(task: CTFScheduledTask) -> dict[str, object]:
    """Render one scheduler row for the organizer listing."""
    return {
        "id": str(task.id),
        "task_type": task.task_type,
        "status": task.status,
        "scheduled_for": task.scheduled_for,
        "executed_at": task.executed_at,
        "error_message": "Task execution failed." if task.error_message else "",
        "retry_count": task.retry_count,
    }


def _visible_tasks(request: Request, event_id: UUID) -> Iterator[dict[str, object]]:
    """Communication task visibility includes every campaign target's authority."""
    from uuid import UUID

    from django.db import transaction

    from ctf.api.organizer.communication import request_actor
    from ctf.exceptions import CTFCommunicationError
    from ctf.models import CommunicationIntent
    from ctf.services.communication.admission import reauthorize
    from ctf.services.event.scheduling import list_event_tasks
    from shared.api_tokens.scopes import CTF_COMMUNICATION_READ

    for task in list_event_tasks(event_id)[:100]:
        if task.task_type == "release_communication":
            try:
                intent_id = UUID((task.metadata or {}).get("intent_id", ""))
            except (ValueError, TypeError, AttributeError):
                continue
            intent = CommunicationIntent.objects.select_related("campaign").filter(pk=intent_id).first()
            if intent is None:
                continue
            try:
                with transaction.atomic():
                    reauthorize(
                        intent.campaign,
                        list(intent.campaign.target_events.all()),
                        request_actor(request),
                        required_scope=CTF_COMMUNICATION_READ,
                        audit_authority=False,
                    )
            except CTFCommunicationError:
                continue
        yield _task_payload(task)


class EventTasksView(APIView):
    """List an owned event's scheduled tasks (GET, #526 monitoring surface)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ

    @extend_schema(responses=ScheduledTaskListResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the event's task history, soonest first."""
        try:
            _resolve_owned_event(request, event_id, capability=EventCapability.LIFECYCLE)
        except _CtfApiError as exc:
            return exc.to_response(request)
        return Response({"tasks": list(_visible_tasks(request, event_id))})


class TaskRunNowView(APIView):
    """Make one pending task due immediately (POST, #526 manual trigger)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses=ScheduledTaskSerializer)
    def post(self, request: Request, event_id: UUID, task_id: UUID) -> Response:
        """Reschedule the task to now; the scheduler executes it on its next poll."""
        from ctf.exceptions import CTFNotFoundError, CTFStateError
        from ctf.services.event.scheduling import run_task_now
        from shared.api_tokens.models import ApiToken

        try:
            _resolve_owned_event(request, event_id, capability=EventCapability.LIFECYCLE)
            # Preserve the authentication mode across the controller->service call so a
            # token-authenticated run-now cannot enter the session-only communication
            # early-release path; the admission owner denies a token actor (#2099).
            auth = getattr(request, "auth", None)
            actor_token_id = auth.pk if isinstance(auth, ApiToken) else None
            try:
                task = run_task_now(event_id, task_id, actor_id=_actor(request).pk, actor_token_id=actor_token_id)
            except CTFNotFoundError:
                _raise_not_found("Scheduled task not found.")
            except CTFStateError:
                _raise_conflict("Only pending tasks can be run now.")
            return Response(_task_payload(task))
        except _CtfApiError as exc:
            return exc.to_response(request)


class EventCleanupControlView(APIView):
    """Defer or cancel the pending automated range cleanup (POST, CTF-1003)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=CleanupControlRequestSerializer, responses=ScheduledTaskListResponseSerializer)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Apply the control and return the refreshed task listing."""
        from ctf.exceptions import CTFStateError, CTFValidationError
        from ctf.services.event.scheduling import (
            cancel_event_cleanup,
            defer_event_cleanup,
        )

        try:
            _resolve_owned_event(request, event_id, capability=EventCapability.LIFECYCLE)
            serializer = CleanupControlRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            action = serializer.validated_data["action"]
            actor_id = _actor(request).pk
            try:
                if action == "defer":
                    hours = serializer.validated_data.get("hours")
                    if hours is None:
                        _raise_bad_request("Deferral needs a number of hours")
                    defer_event_cleanup(event_id, hours, actor_id=actor_id)
                else:
                    cancel_event_cleanup(event_id, actor_id=actor_id)
            except CTFValidationError:
                _raise_bad_request("Deferral must be between 1 and 168 hours.")
            except CTFStateError:
                _raise_conflict("No pending cleanup for this event.")
            return Response({"tasks": list(_visible_tasks(request, event_id))})
        except _CtfApiError as exc:
            return exc.to_response(request)
