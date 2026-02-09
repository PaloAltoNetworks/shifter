"""SQS event handler for experiment lifecycle events.

Follows the same pattern as cms.handlers and engine.handlers.
Routes experiment events to the ExperimentOrchestrator.
Broadcasts status changes to WebSocket consumers via channel layer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from cms.experiments.orchestrator import ExperimentOrchestrator

logger = logging.getLogger(__name__)


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
        if channel_layer is None:
            return

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
        logger.debug("_broadcast_run_status: channel layer unavailable", exc_info=True)


def _broadcast_experiment_status(experiment_id: int, status: str) -> None:
    """Broadcast experiment-level status change to WebSocket consumers."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        from cms.experiments.consumers import experiment_event_group

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

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
        logger.debug("_broadcast_experiment_status: channel layer unavailable", exc_info=True)


def process_event(message: str | dict) -> None:
    """Route experiment event to appropriate handler.

    This is the main entry point for the experiments SQS worker.

    Args:
        message: SNS-wrapped message containing experiment event data.
    """
    event = _parse_message(message)
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


def _parse_message(message: str | dict) -> dict:
    """Unwrap SNS envelope to get event payload."""
    body = json.loads(message) if isinstance(message, str) else message
    if "Message" in body:
        return json.loads(body["Message"])
    return body


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def _handle_experiment_start(event: dict) -> None:
    """Handle experiment.start — begin scheduling runs."""
    experiment_id = event.get("experiment_id")
    if not experiment_id:
        logger.warning("experiment.start: missing experiment_id")
        return

    orchestrator = ExperimentOrchestrator(experiment_id)
    orchestrator.schedule_runs()

    # Broadcast that experiment is now running
    _broadcast_experiment_status(experiment_id, "running")


def _handle_range_provisioned(event: dict) -> None:
    """Handle experiment.run.range_provisioned — range is ready, start scripts."""
    experiment_id = event.get("experiment_id")
    run_id = event.get("run_id")
    provisioned_instances = event.get("provisioned_instances", {})

    if not experiment_id or not run_id:
        logger.warning("range_provisioned: missing experiment_id or run_id")
        return

    orchestrator = ExperimentOrchestrator(experiment_id)
    orchestrator.handle_range_provisioned(run_id, provisioned_instances)

    # Broadcast updated run status
    from cms.experiments.models import ExperimentRun

    try:
        run = ExperimentRun.objects.get(pk=run_id)
        _broadcast_run_status(experiment_id, run_id, run.run_number, run.status)
    except ExperimentRun.DoesNotExist:
        pass


def _handle_victim_scripts_completed(event: dict) -> None:
    """Handle experiment.run.victims_completed — victims done, start attacker."""
    experiment_id = event.get("experiment_id")
    run_id = event.get("run_id")

    if not experiment_id or not run_id:
        logger.warning("victims_completed: missing experiment_id or run_id")
        return

    orchestrator = ExperimentOrchestrator(experiment_id)
    orchestrator.handle_victim_scripts_completed(run_id)

    from cms.experiments.models import ExperimentRun

    try:
        run = ExperimentRun.objects.get(pk=run_id)
        _broadcast_run_status(experiment_id, run_id, run.run_number, run.status)
    except ExperimentRun.DoesNotExist:
        pass


def _handle_attacker_scripts_completed(event: dict) -> None:
    """Handle experiment.run.attacker_completed — attacker done, collect artifacts."""
    experiment_id = event.get("experiment_id")
    run_id = event.get("run_id")

    if not experiment_id or not run_id:
        logger.warning("attacker_completed: missing experiment_id or run_id")
        return

    orchestrator = ExperimentOrchestrator(experiment_id)
    orchestrator.handle_attacker_scripts_completed(run_id)

    from cms.experiments.models import ExperimentRun

    try:
        run = ExperimentRun.objects.get(pk=run_id)
        _broadcast_run_status(experiment_id, run_id, run.run_number, run.status)
    except ExperimentRun.DoesNotExist:
        pass


def _handle_artifacts_collected(event: dict) -> None:
    """Handle experiment.run.artifacts_collected — mark run complete."""
    experiment_id = event.get("experiment_id")
    run_id = event.get("run_id")

    if not experiment_id or not run_id:
        logger.warning("artifacts_collected: missing experiment_id or run_id")
        return

    orchestrator = ExperimentOrchestrator(experiment_id)
    orchestrator.handle_artifacts_collected(run_id)

    from cms.experiments.models import Experiment, ExperimentRun

    try:
        run = ExperimentRun.objects.get(pk=run_id)
        _broadcast_run_status(experiment_id, run_id, run.run_number, run.status)
    except ExperimentRun.DoesNotExist:
        pass

    # Check if experiment completed and broadcast
    try:
        exp = Experiment.objects.get(pk=experiment_id)
        if exp.status in ("completed", "failed"):
            _broadcast_experiment_status(experiment_id, exp.status)
    except Experiment.DoesNotExist:
        pass


def _handle_run_failed(event: dict) -> None:
    """Handle experiment.run.failed — record failure, schedule next."""
    experiment_id = event.get("experiment_id")
    run_id = event.get("run_id")
    error_message = event.get("error_message", "Unknown error")

    if not experiment_id or not run_id:
        logger.warning("run_failed: missing experiment_id or run_id")
        return

    orchestrator = ExperimentOrchestrator(experiment_id)
    orchestrator.handle_run_failed(run_id, error_message)

    from cms.experiments.models import Experiment, ExperimentRun

    try:
        run = ExperimentRun.objects.get(pk=run_id)
        _broadcast_run_status(experiment_id, run_id, run.run_number, run.status, error_message)
    except ExperimentRun.DoesNotExist:
        pass

    # Check if experiment completed and broadcast
    try:
        exp = Experiment.objects.get(pk=experiment_id)
        if exp.status in ("completed", "failed"):
            _broadcast_experiment_status(experiment_id, exp.status)
    except Experiment.DoesNotExist:
        pass


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
