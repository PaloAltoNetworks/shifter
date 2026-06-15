"""Experiment notification registrations and publishers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from cms.experiments.models import Experiment
from shared.notifications import publish_notification, register_notification_type

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser, AnonymousUser, User

EXPERIMENT_TOPIC_PREFIX = "experiment:"
NOTIFICATION_EXPERIMENT_RUN_STATUS = "experiment.run_status"
NOTIFICATION_EXPERIMENT_STATUS = "experiment.status"


def experiment_topic(experiment_id: int | str) -> str:
    """Return the logical notification topic for an experiment."""
    return f"{EXPERIMENT_TOPIC_PREFIX}{int(experiment_id)}"


def _experiment_id_from_topic(topic: str) -> int | None:
    """Parse the positive experiment id from a topic, or None if it does not match."""
    if not topic.startswith(EXPERIMENT_TOPIC_PREFIX):
        return None
    raw_id = topic.removeprefix(EXPERIMENT_TOPIC_PREFIX)
    try:
        experiment_id = int(raw_id)
    except ValueError:
        return None
    return experiment_id if experiment_id > 0 else None


def _can_subscribe_to_experiment(user: AbstractBaseUser | AnonymousUser, topic: str) -> bool:
    """Authorize experiment notification subscriptions."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_staff", False):
        return False
    experiment_id = _experiment_id_from_topic(topic)
    if experiment_id is None:
        return False
    # Narrowed to a concrete User by the is_authenticated/is_staff guard above.
    return Experiment.objects.filter(pk=experiment_id, user=cast("User", user)).exists()


def _run_status_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project a run-status notification to browser-safe fields."""
    return {
        "experiment_id": payload["experiment_id"],
        "run_id": payload["run_id"],
        "run_number": payload["run_number"],
        "status": payload["status"],
        "error_message": payload.get("error_message", ""),
    }


def _experiment_status_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project an experiment-status notification to browser-safe fields."""
    return {
        "experiment_id": payload["experiment_id"],
        "status": payload["status"],
    }


def register_experiment_notifications() -> None:
    """Register experiment notification types with the shared infrastructure."""
    register_notification_type(
        name=NOTIFICATION_EXPERIMENT_RUN_STATUS,
        topic_prefix=EXPERIMENT_TOPIC_PREFIX,
        can_subscribe=_can_subscribe_to_experiment,
        payload_handler=_run_status_payload,
        replace=True,
    )
    register_notification_type(
        name=NOTIFICATION_EXPERIMENT_STATUS,
        topic_prefix=EXPERIMENT_TOPIC_PREFIX,
        can_subscribe=_can_subscribe_to_experiment,
        payload_handler=_experiment_status_payload,
        replace=True,
    )


def publish_experiment_run_status_notification(
    *,
    experiment_id: int,
    recipient_id: int,
    run_id: int,
    run_number: int,
    status: str,
    error_message: str = "",
    event_id: UUID | str | None = None,
) -> None:
    """Queue and fan out an experiment run-status browser notification."""
    publish_notification(
        NOTIFICATION_EXPERIMENT_RUN_STATUS,
        topic=experiment_topic(experiment_id),
        payload={
            "experiment_id": experiment_id,
            "run_id": run_id,
            "run_number": run_number,
            "status": status,
            "error_message": error_message,
        },
        recipient_ids=[recipient_id],
        event_id=event_id,
    )


def publish_experiment_status_notification(
    *,
    experiment_id: int,
    recipient_id: int,
    status: str,
    event_id: UUID | str | None = None,
) -> None:
    """Queue and fan out an experiment status browser notification."""
    publish_notification(
        NOTIFICATION_EXPERIMENT_STATUS,
        topic=experiment_topic(experiment_id),
        payload={
            "experiment_id": experiment_id,
            "status": status,
        },
        recipient_ids=[recipient_id],
        event_id=event_id,
    )
