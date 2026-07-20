"""Organizer event-lifecycle and scheduler-control views (CTF-007, #526, CTF-1003).

Lifecycle transitions delegate to the authoritative ``ctf.services.event``
state machine; these views own only HTTP shape and ownership resolution.
Lifecycle, task, and cleanup control are owner-only (never staff-delegated).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._base import (
    _EVENT_READ,
    _EVENT_WRITE,
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

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFEvent, CTFScheduledTask

logger = logging.getLogger(__name__)


def _lifecycle_actions() -> dict[str, object]:
    """Map lifecycle action names to their service transitions."""
    from ctf.services.event import (
        activate_event,
        cancel_event,
        complete_event,
        open_registration,
        pause_event,
        resume_event,
    )

    return {
        "open_registration": open_registration,
        "activate": activate_event,
        "pause": pause_event,
        "resume": resume_event,
        "end": complete_event,
        "cancel": cancel_event,
    }


class EventLifecycleView(APIView):
    """Apply one lifecycle transition to an owned event (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=EventLifecycleRequestSerializer, responses=EventMutationResultSerializer)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Validate the action, run the state machine, and return the new status."""
        try:
            event = _resolve_owned_event(request, event_id)
            serializer = EventLifecycleRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            action = serializer.validated_data["action"]
            self._apply(event, action)
            event.refresh_from_db()
            return Response({"id": str(event.id), "name": event.name, "status": event.status})
        except _CtfApiError as exc:
            return exc.to_response(request)

    @staticmethod
    def _apply(event: CTFEvent, action: str) -> None:
        """Run the transition; a refused transition is a 409, not a 500."""
        transition = _lifecycle_actions()[action]
        if not transition(event):  # type: ignore[operator]
            _raise_conflict(f"Event cannot {action.replace('_', ' ')} from status {event.status}")


def _task_payload(task: CTFScheduledTask) -> dict[str, object]:
    """Render one scheduler row for the organizer listing."""
    return {
        "id": str(task.id),
        "task_type": task.task_type,
        "status": task.status,
        "scheduled_for": task.scheduled_for,
        "executed_at": task.executed_at,
        "error_message": task.error_message,
        "retry_count": task.retry_count,
    }


class EventTasksView(APIView):
    """List an owned event's scheduled tasks (GET, #526 monitoring surface)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ

    @extend_schema(responses=ScheduledTaskListResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the event's task history, soonest first."""
        from ctf.services.event.scheduling import list_event_tasks

        try:
            _resolve_owned_event(request, event_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        return Response({"tasks": [_task_payload(t) for t in list_event_tasks(event_id)]})


class TaskRunNowView(APIView):
    """Make one pending task due immediately (POST, #526 manual trigger)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses=ScheduledTaskSerializer)
    def post(self, request: Request, event_id: UUID, task_id: UUID) -> Response:
        """Reschedule the task to now; the scheduler executes it on its next poll."""
        from ctf.exceptions import CTFNotFoundError, CTFStateError
        from ctf.services.event.scheduling import run_task_now

        try:
            _resolve_owned_event(request, event_id)
            try:
                task = run_task_now(event_id, task_id)
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
            list_event_tasks,
        )

        try:
            _resolve_owned_event(request, event_id)
            serializer = CleanupControlRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            action = serializer.validated_data["action"]
            try:
                if action == "defer":
                    hours = serializer.validated_data.get("hours")
                    if hours is None:
                        _raise_bad_request("Deferral needs a number of hours")
                    defer_event_cleanup(event_id, hours)
                else:
                    cancel_event_cleanup(event_id)
            except CTFValidationError:
                _raise_bad_request("Deferral must be between 1 and 168 hours.")
            except CTFStateError:
                _raise_conflict("No pending cleanup for this event.")
            return Response({"tasks": [_task_payload(t) for t in list_event_tasks(event_id)]})
        except _CtfApiError as exc:
            return exc.to_response(request)
