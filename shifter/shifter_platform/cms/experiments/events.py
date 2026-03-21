"""Experiment event publishing.

Publishes events to the experiments SQS queue for processing by the
experiment SQS worker. Used by the CMS range handler to bridge range
provisioning events into the experiment lifecycle.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from shared.cloud import get_queue_publisher
from shared.cloud.exceptions import CloudQueueError

logger = logging.getLogger(__name__)


class ExperimentEventError(Exception):
    """Failed to publish an experiment event."""


def _get_experiments_queue_url() -> str | None:
    """Get the experiments SQS queue URL from settings.

    Experiments use the cms queue since they're part of the cms module.

    Returns:
        Queue URL string, or None if not configured.
    """
    config: dict[str, Any] = getattr(settings, "SQS_QUEUE_CONFIG", {})
    cms_config: dict[str, str] = config.get("cms", {})
    url: str = cms_config.get("url", "")
    return url or None


def publish_experiment_event(event_type: str, payload: dict[str, Any]) -> None:
    """Publish an event to the experiments SQS queue.

    Args:
        event_type: Event type string (e.g., "experiment.run.range_provisioned").
        payload: Event data dict. Must be JSON-serializable.

    Raises:
        ExperimentEventError: If queue message publishing fails.
    """
    queue_url = _get_experiments_queue_url()
    if queue_url is None:
        error_msg = f"Cannot publish experiment event {event_type}: SQS_CMS_URL not configured"
        logger.error(error_msg)
        raise ExperimentEventError(error_msg)

    message_body = {
        "event_type": event_type,
        **payload,
    }

    try:
        publisher = get_queue_publisher()
        publisher.send_message(queue_url, json.dumps(message_body, default=str))
        logger.info(
            "publish_experiment_event: published event_type=%s to experiments queue",
            event_type,
        )
    except CloudQueueError as exc:
        logger.exception(
            "publish_experiment_event: failed to publish event_type=%s",
            event_type,
        )
        raise ExperimentEventError(f"Failed to publish event {event_type} to SQS: {exc}") from exc


def publish_range_provisioned_for_experiment(
    experiment_id: int,
    run_id: int,
    provisioned_instances: dict[str, Any],
) -> None:
    """Publish a range_provisioned event for an experiment run.

    Called by the CMS range handler when a range associated with an
    experiment run transitions to READY status.

    Args:
        experiment_id: Database ID of the Experiment.
        run_id: Database ID of the ExperimentRun.
        provisioned_instances: Dict of instance name -> instance details
            from the range provisioning event.

    Raises:
        ExperimentEventError: If queue message publishing fails.
    """
    publish_experiment_event(
        event_type="experiment.run.range_provisioned",
        payload={
            "experiment_id": experiment_id,
            "run_id": run_id,
            "provisioned_instances": provisioned_instances,
        },
    )
