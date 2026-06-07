"""SQS event handler for experiment lifecycle events.

Follows the same pattern as cms.handlers and engine.handlers.
Routes experiment events to the ExperimentOrchestrator.
Broadcasts status changes to WebSocket consumers via channel layer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from cms.experiments.models import Experiment, ExperimentRun
from cms.experiments.orchestrator import ExperimentOrchestrator
from shared.messages.envelope import parse_sns_message

_TERMINAL_EXPERIMENT_STATUSES = ("completed", "failed")

logger = logging.getLogger(__name__)


def _experiment_recipient_id(experiment_id: int) -> int | None:
    """Return the owning user id for experiment notifications."""
    try:
        return Experiment.objects.only("user_id").get(pk=experiment_id).user_id
    except Experiment.DoesNotExist:
        return None


def _publish_run_status_notification(
    experiment_id: int,
    run_id: int,
    run_number: int,
    status: str,
    error_message: str,
) -> None:
    """Queue a shared notification for run-status changes."""
    recipient_id = _experiment_recipient_id(experiment_id)
    if recipient_id is None:
        return
    try:
        from cms.experiments.notifications import publish_experiment_run_status_notification

        publish_experiment_run_status_notification(
            experiment_id=experiment_id,
            recipient_id=recipient_id,
            run_id=run_id,
            run_number=run_number,
            status=status,
            error_message=error_message,
        )
    except Exception:
        logger.warning(
            "failed to queue experiment run notification: experiment=%s run=%s status=%s",
            experiment_id,
            run_id,
            status,
            exc_info=True,
        )


def _publish_experiment_status_notification(experiment_id: int, status: str) -> None:
    """Queue a shared notification for experiment status changes."""
    recipient_id = _experiment_recipient_id(experiment_id)
    if recipient_id is None:
        return
    try:
        from cms.experiments.notifications import publish_experiment_status_notification

        publish_experiment_status_notification(
            experiment_id=experiment_id,
            recipient_id=recipient_id,
            status=status,
        )
    except Exception:
        logger.warning(
            "failed to queue experiment notification: experiment=%s status=%s",
            experiment_id,
            status,
            exc_info=True,
        )


def _broadcast_run_status(
    experiment_id: int,
    run_id: int,
    run_number: int,
    status: str,
    error_message: str = "",
) -> None:
    """Broadcast run status change to WebSocket consumers."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        from cms.experiments.consumers import experiment_event_group

        channel_layer = get_channel_layer()
        if channel_layer is not None:
            group = experiment_event_group(experiment_id)
            async_to_sync(channel_layer.group_send)(
                group,
                {
                    "type": "experiment.run_status",
                    "run_id": run_id,
                    "run_number": run_number,
                    "status": status,
                    "error_message": error_message,
                },
            )
            logger.debug(
                "broadcast run_status: experiment=%s run=%s status=%s",
                experiment_id,
                run_id,
                status,
            )
    except Exception:
        logger.warning("_broadcast_run_status: channel layer unavailable", exc_info=True)
    _publish_run_status_notification(
        experiment_id,
        run_id,
        run_number,
        status,
        error_message,
    )


def _broadcast_run_status_for(
    experiment_id: int,
    run_id: int,
    error_message: str = "",
) -> None:
    """Look up the run and broadcast its current status. No-op if the row is gone."""
    try:
        run = ExperimentRun.objects.get(pk=run_id)
    except ExperimentRun.DoesNotExist:
        return
    _broadcast_run_status(
        experiment_id,
        run_id,
        run.run_number,
        run.status,
        error_message=error_message,
    )


def _broadcast_experiment_status_if_terminal(experiment_id: int) -> None:
    """Broadcast experiment status only when it has reached a terminal state.
    No-op if the row is gone or the experiment is still running."""
    try:
        exp = Experiment.objects.get(pk=experiment_id)
    except Experiment.DoesNotExist:
        return
    if exp.status in _TERMINAL_EXPERIMENT_STATUSES:
        _broadcast_experiment_status(experiment_id, exp.status)


def _broadcast_experiment_status(experiment_id: int, status: str) -> None:
    """Broadcast experiment-level status change to WebSocket consumers."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        from cms.experiments.consumers import experiment_event_group

        channel_layer = get_channel_layer()
        if channel_layer is not None:
            group = experiment_event_group(experiment_id)
            async_to_sync(channel_layer.group_send)(
                group,
                {
                    "type": "experiment.status",
                    "experiment_id": experiment_id,
                    "status": status,
                },
            )
            logger.debug(
                "broadcast experiment_status: experiment=%s status=%s",
                experiment_id,
                status,
            )
    except Exception:
        logger.warning("_broadcast_experiment_status: channel layer unavailable", exc_info=True)
    _publish_experiment_status_notification(experiment_id, status)


def process_event(message: str | dict) -> None:
    """Route experiment event to appropriate handler.

    This is the main entry point for the experiments SQS worker.

    Args:
        message: SNS-wrapped message containing experiment event data.
    """
    event = parse_sns_message(message)
    event_type = event.get("event_type", "")
    event_id = event.get("event_id", "unknown")

    handler = _HANDLERS.get(event_type)
    if handler is None:
        logger.debug("Ignoring unknown event_type=%s event_id=%s", event_type, event_id)
        return

    logger.info("Processing event_type=%s event_id=%s", event_type, event_id)
    try:
        handler(event)
    except Exception:
        logger.exception(
            "Error processing event_type=%s event_id=%s",
            event_type,
            event_id,
        )


# ---------------------------------------------------------------------------
# Event ID validation helper
# ---------------------------------------------------------------------------


def _validate_event_ids(event: dict[str, Any], handler_name: str, *fields: str) -> dict[str, Any] | None:
    """Extract and validate required integer fields from event dict.

    Returns dict of field->value if valid, or None if validation fails.
    """
    result = {}
    for fld in fields:
        value = event.get(fld)
        if not value:
            logger.warning("%s: missing %s", handler_name, fld)
            return None
        if not isinstance(value, int):
            logger.warning("%s: %s is not int: %s", handler_name, fld, type(value).__name__)
            return None
        result[fld] = value
    return result


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def _handle_experiment_start(event: dict[str, Any]) -> None:
    """Handle experiment.start — begin scheduling runs."""
    ids = _validate_event_ids(event, "experiment.start", "experiment_id")
    if ids is None:
        return

    orchestrator = ExperimentOrchestrator(ids["experiment_id"])
    orchestrator.schedule_runs()

    # Broadcast that experiment is now running
    _broadcast_experiment_status(ids["experiment_id"], "running")


def _handle_range_provisioned(event: dict[str, Any]) -> None:
    """Handle experiment.run.range_provisioned — range is ready, start scripts."""
    ids = _validate_event_ids(event, "range_provisioned", "experiment_id", "run_id")
    if ids is None:
        return

    provisioned_instances = event.get("provisioned_instances", {})

    orchestrator = ExperimentOrchestrator(ids["experiment_id"])
    orchestrator.handle_range_provisioned(ids["run_id"], provisioned_instances)

    _broadcast_run_status_for(ids["experiment_id"], ids["run_id"])


def _handle_victim_scripts_completed(event: dict[str, Any]) -> None:
    """Handle experiment.run.victims_completed — victims done, start attacker."""
    ids = _validate_event_ids(event, "victims_completed", "experiment_id", "run_id")
    if ids is None:
        return

    orchestrator = ExperimentOrchestrator(ids["experiment_id"])
    orchestrator.handle_victim_scripts_completed(ids["run_id"])

    _broadcast_run_status_for(ids["experiment_id"], ids["run_id"])


def _handle_attacker_scripts_completed(event: dict[str, Any]) -> None:
    """Handle experiment.run.attacker_completed — attacker done, collect artifacts."""
    ids = _validate_event_ids(event, "attacker_completed", "experiment_id", "run_id")
    if ids is None:
        return

    orchestrator = ExperimentOrchestrator(ids["experiment_id"])
    orchestrator.handle_attacker_scripts_completed(ids["run_id"])

    _broadcast_run_status_for(ids["experiment_id"], ids["run_id"])


def _handle_artifacts_collected(event: dict[str, Any]) -> None:
    """Handle experiment.run.artifacts_collected — mark run complete."""
    ids = _validate_event_ids(event, "artifacts_collected", "experiment_id", "run_id")
    if ids is None:
        return

    orchestrator = ExperimentOrchestrator(ids["experiment_id"])
    orchestrator.handle_artifacts_collected(ids["run_id"])

    _broadcast_run_status_for(ids["experiment_id"], ids["run_id"])
    _broadcast_experiment_status_if_terminal(ids["experiment_id"])


def _handle_run_failed(event: dict[str, Any]) -> None:
    """Handle experiment.run.failed — record failure, schedule next."""
    ids = _validate_event_ids(event, "run_failed", "experiment_id", "run_id")
    if ids is None:
        return

    error_message = event.get("error_message", "Unknown error")

    orchestrator = ExperimentOrchestrator(ids["experiment_id"])
    orchestrator.handle_run_failed(ids["run_id"], error_message)

    _broadcast_run_status_for(ids["experiment_id"], ids["run_id"], error_message=error_message)
    _broadcast_experiment_status_if_terminal(ids["experiment_id"])


# ---------------------------------------------------------------------------
# Event type -> handler mapping
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable] = {
    "experiment.start": _handle_experiment_start,
    "experiment.run.range_provisioned": _handle_range_provisioned,
    "experiment.run.victims_completed": _handle_victim_scripts_completed,
    "experiment.run.attacker_completed": _handle_attacker_scripts_completed,
    "experiment.run.artifacts_collected": _handle_artifacts_collected,
    "experiment.run.failed": _handle_run_failed,
}
