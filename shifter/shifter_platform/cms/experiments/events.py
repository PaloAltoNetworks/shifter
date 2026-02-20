"""Experiment event publishing.

Publishes events to the experiments SQS queue for processing by the
experiment SQS worker. Used by the CMS range handler to bridge range
provisioning events into the experiment lifecycle.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from django.conf import settings

logger = logging.getLogger(__name__)


class ExperimentEventError(Exception):
    """Failed to publish an experiment event."""


def _get_experiments_queue_url() -> str | None:
    """Get the experiments SQS queue URL from settings.

    Returns:
        Queue URL string, or None if not configured.
    """
    config: dict[str, Any] = getattr(settings, "SQS_QUEUE_CONFIG", {})
    experiments_config: dict[str, str] = config.get("experiments", {})
    url: str = experiments_config.get("url", "")
    return url or None


def _get_sqs_client() -> Any:
    """Get boto3 SQS client for the configured region.

    Returns:
        Boto3 SQS client.

    Raises:
        ValueError: If AWS_REGION is not configured.
    """
    region: str = getattr(settings, "AWS_REGION", "")
    if not region:
        raise ValueError("AWS_REGION is required for SQS operations")

    endpoint_url: str = getattr(settings, "AWS_ENDPOINT_URL", "") or None
    return boto3.client("sqs", region_name=region, endpoint_url=endpoint_url)


def publish_experiment_event(event_type: str, payload: dict[str, Any]) -> bool:
    """Publish an event to the experiments SQS queue.

    Args:
        event_type: Event type string (e.g., "experiment.run.range_provisioned").
        payload: Event data dict. Must be JSON-serializable.

    Returns:
        True if the event was published successfully, False if SQS is
        not configured or publication failed.
    """
    queue_url = _get_experiments_queue_url()
    if queue_url is None:
        logger.warning(
            "publish_experiment_event: SQS_EXPERIMENTS_URL not configured, "
            "cannot publish event_type=%s",
            event_type,
        )
        return False

    message_body = {
        "event_type": event_type,
        **payload,
    }

    try:
        sqs = _get_sqs_client()
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message_body, default=str),
        )
        logger.info(
            "publish_experiment_event: published event_type=%s to experiments queue",
            event_type,
        )
        return True
    except Exception:
        logger.exception(
            "publish_experiment_event: failed to publish event_type=%s",
            event_type,
        )
        return False


def publish_range_provisioned_for_experiment(
    experiment_id: int,
    run_id: int,
    provisioned_instances: dict[str, Any],
) -> bool:
    """Publish a range_provisioned event for an experiment run.

    Called by the CMS range handler when a range associated with an
    experiment run transitions to READY status.

    Args:
        experiment_id: Database ID of the Experiment.
        run_id: Database ID of the ExperimentRun.
        provisioned_instances: Dict of instance name -> instance details
            from the range provisioning event.

    Returns:
        True if published successfully, False otherwise.
    """
    return publish_experiment_event(
        event_type="experiment.run.range_provisioned",
        payload={
            "experiment_id": experiment_id,
            "run_id": run_id,
            "provisioned_instances": provisioned_instances,
        },
    )
