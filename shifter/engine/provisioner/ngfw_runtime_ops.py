"""NGFW runtime operations (start/stop) for the Shifter Engine provisioner.

Extracted from ``main.py`` (Sonar S104). Public entry point is
``run_ngfw_operation``; the AWS/GCP-specific helpers and the shared
status-publication helpers live here too.
"""

from __future__ import annotations

import logging
from typing import Any

from config import resolve_ngfw_attachment_config
from events import STATUS_FAILED, publish_ngfw_event
from executors.aws_executor import AWSExecutor
from ngfw_runtime import update_instance_state
from orchestrators.ops_orchestrator import OpsOrchestrator
from plans.base import SetupPlan
from provisioner_db_ngfw import get_ngfw_data_by_request_id

logger = logging.getLogger(__name__)


def _validate_ngfw_operation(operation: str) -> tuple[str, str]:
    """Map an NGFW operation name to its (in-progress, success) status pair."""
    status_map = {
        "start": ("resuming", "ready"),
        "stop": ("pausing", "paused"),
    }
    if operation not in status_map:
        raise ValueError(f"Unknown operation: {operation}")
    return status_map[operation]


def _publish_ngfw_runtime_status(request_id: str, instance_uuid: str, app_id: str, status: str) -> None:
    """Persist the new NGFW runtime status and emit the corresponding lifecycle event."""
    update_instance_state(request_id, status)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_uuid,
        app_id=app_id,
        status=status,
    )


def _run_gcp_ngfw_operation(
    operation: str,
    request_id: str,
    instance_uuid: str,
    app_id: str,
    state: dict[str, Any],
) -> None:
    """Drive a start/stop power operation against a GCP VM-Series NGFW."""
    import gdc_vmseries_ngfw

    in_progress_status, success_status = _validate_ngfw_operation(operation)
    _publish_ngfw_runtime_status(request_id, instance_uuid, app_id, in_progress_status)
    try:
        gdc_vmseries_ngfw.run_power_operation(operation, state)
    except Exception as e:
        logger.exception("GDC VM-Series NGFW operation failed")
        update_instance_state(request_id, STATUS_FAILED, error_message=str(e))
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_uuid,
            app_id=app_id,
            status=STATUS_FAILED,
        )
        raise
    _publish_ngfw_runtime_status(request_id, instance_uuid, app_id, success_status)


def _load_ngfw_ops_plan(operation: str) -> SetupPlan:
    """Lazily import and instantiate the SetupPlan for the requested NGFW operation."""
    import importlib

    plan_map = {
        "start": "plans.ngfw_start.NGFWStartPlan",
        "stop": "plans.ngfw_stop.NGFWStopPlan",
    }
    module_path, class_name = plan_map[operation].rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def _run_aws_ngfw_operation(
    operation: str,
    request_id: str,
    instance_uuid: str,
    app_id: str,
    ec2_instance_id: str,
    **kwargs: str,
) -> None:
    """Drive a start/stop power operation against an AWS-attached NGFW EC2 instance."""
    in_progress_status, success_status = _validate_ngfw_operation(operation)
    _publish_ngfw_runtime_status(request_id, instance_uuid, app_id, in_progress_status)

    try:
        executor = AWSExecutor()
        orchestrator = OpsOrchestrator(executor)
        plan = _load_ngfw_ops_plan(operation)
        context = {"instance_id": ec2_instance_id, **kwargs}
        result = orchestrator.orchestrate(ec2_instance_id, plan, context)
        if not result.success:
            for step_result in result.step_results:
                if not step_result.success:
                    logger.error(
                        "NGFW %s step %s failed: %s",
                        operation,
                        step_result.step_name,
                        step_result.stderr,
                    )
            raise RuntimeError(f"Operation {operation} failed")
    except Exception as e:
        error_msg = str(e)[:1000]
        update_instance_state(request_id, STATUS_FAILED, error_message=error_msg)
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_uuid,
            app_id=app_id,
            status=STATUS_FAILED,
        )
        raise

    _publish_ngfw_runtime_status(request_id, instance_uuid, app_id, success_status)


def run_ngfw_operation(operation: str, request_id: str, **kwargs: str) -> None:
    """Run NGFW runtime operation (start/stop).

    Retrieves EC2 instance ID from the Instance.state (populated during
    provisioning), executes the operation plan, and publishes events for status
    updates.

    Args:
        operation: Operation name (start, stop).
        request_id: UUID string of the Request.
        **kwargs: Operation-specific parameters (overrides for context).

    Raises:
        ValueError: If unknown operation or EC2 instance ID not found.
        Exception: If operation fails.
    """
    logger.info("run_ngfw_operation: starting operation=%s request_id=%s", operation, request_id)
    if kwargs:
        logger.debug("run_ngfw_operation: kwargs=%s", list(kwargs.keys()))

    _validate_ngfw_operation(operation)

    # Get NGFW data from database including state with EC2 instance ID
    ngfw_data = get_ngfw_data_by_request_id(request_id)
    # Our UUID, not AWS instance ID
    instance_uuid = ngfw_data["instance_id"]
    app_id = ngfw_data["app_id"]
    state = ngfw_data.get("state", {})
    provider = resolve_ngfw_attachment_config(state).cloud_provider

    if provider == "gcp":
        _run_gcp_ngfw_operation(operation, request_id, instance_uuid, app_id, state)
        return
    if provider != "aws":
        raise RuntimeError(f"NGFW runtime operation {operation!r} is not implemented for cloud_provider={provider!r}")

    # EC2 instance ID is stored in state after Terraform provisioning
    ec2_instance_id = state.get("ec2_instance_id")
    if not ec2_instance_id:
        raise ValueError(f"EC2 instance ID not found in state for request: {request_id}")
    _run_aws_ngfw_operation(operation, request_id, instance_uuid, app_id, ec2_instance_id, **kwargs)
