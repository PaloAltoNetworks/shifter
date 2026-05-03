"""Experiment bridge: notify the experiments subsystem when a range is READY."""

from __future__ import annotations

import logging
from typing import Any

from cms.experiments.events import publish_range_provisioned_for_experiment
from cms.models import RangeInstance

logger = logging.getLogger(__name__)


def notify_experiment_on_range_ready(
    range_instance: RangeInstance,
    provisioned_instances: dict[str, Any],
) -> None:
    """Bridge range provisioned events to the experiment lifecycle.

    Checks if the given RangeInstance is linked to an ExperimentRun
    (via request_id correlation). If so, publishes an
    experiment.run.range_provisioned event to the experiments SQS queue.

    Args:
        range_instance: The RangeInstance that just became READY.
        provisioned_instances: Dict of instance name -> instance details
            from the provisioning event payload.
    """
    from cms.experiments.models import ExperimentRun

    request_id = range_instance.request.request_id if range_instance.request else None
    if request_id is None:
        return

    try:
        run = ExperimentRun.objects.select_related("experiment").get(
            request_id=request_id,
        )
    except ExperimentRun.DoesNotExist:
        # Range is not linked to an experiment — normal interactive range
        return

    logger.info(
        "notify_experiment_on_range_ready: range for experiment=%d run=%d is READY, publishing event (request_id=%s)",
        run.experiment_id,
        run.pk,
        request_id,
    )

    try:
        publish_range_provisioned_for_experiment(
            experiment_id=run.experiment_id,
            run_id=run.pk,
            provisioned_instances=provisioned_instances,
        )
    except Exception:
        # Experiments require deterministic outcomes. If we cannot notify the
        # experiment that its range is ready, the run cannot proceed and must
        # be marked as FAILED to avoid silent orphaning.
        logger.exception(
            "notify_experiment_on_range_ready: failed to publish event for "
            "experiment=%d run=%d (request_id=%s) — marking run as FAILED",
            run.experiment_id,
            run.pk,
            request_id,
        )
        from cms.experiments.schemas import RunStatus

        run.error_message = "Failed to publish range provisioning notification"
        run.save(update_fields=["error_message"])
        run.transition_to(RunStatus.FAILED)
