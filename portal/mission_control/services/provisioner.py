"""Range provisioner service using AWS Step Functions.

This module triggers Step Functions state machines to provision and teardown
range infrastructure. The Lambda functions (v1) or Pulumi ECS tasks (v2) write
directly to RDS, so no callback endpoint is needed.
"""

import json
import logging

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_sfn_client():
    """Get boto3 Step Functions client."""
    return boto3.client("stepfunctions", region_name=settings.AWS_REGION)


def start_provisioning(range_id: int) -> str | None:
    """Start provisioning a range via Step Functions.

    Routes to v1 (Lambda) or v2 (Pulumi) based on Range.provisioner_version.

    Args:
        range_id: Database ID of the Range to provision

    Returns:
        Execution ARN if successful, None if Step Functions is not configured
        (falls back to stub behavior for local dev)

    Raises:
        ClientError: If Step Functions execution fails to start
    """
    from mission_control.models import Range

    range_obj = Range.objects.get(id=range_id)

    if range_obj.provisioner_version == "v2":
        return _start_pulumi_provisioning(range_id)
    else:
        return _start_lambda_provisioning(range_id)


def _start_lambda_provisioning(range_id: int) -> str | None:
    """Start provisioning via Lambda-based Step Functions (v1).

    Args:
        range_id: Database ID of the Range to provision

    Returns:
        Execution ARN if successful, None if not configured
    """
    provision_arn = getattr(settings, "PROVISION_STATE_MACHINE_ARN", None)

    if not provision_arn:
        logger.warning(
            "PROVISION_STATE_MACHINE_ARN not configured, skipping Step Functions. Set this in settings for production."
        )
        return None

    logger.info(f"Starting Lambda provisioning (v1) for range_id={range_id}")

    sfn = _get_sfn_client()

    try:
        response = sfn.start_execution(
            stateMachineArn=provision_arn,
            input=json.dumps({"range_id": range_id}),
        )
        execution_arn = response["executionArn"]
        logger.info(f"Started Lambda provisioning execution: range_id={range_id} execution_arn={execution_arn}")
        return execution_arn

    except ClientError as e:
        logger.error(f"Failed to start Lambda provisioning for range_id={range_id}: {e}")
        raise


def _start_pulumi_provisioning(range_id: int) -> str | None:
    """Start provisioning via Pulumi-based Step Functions (v2).

    Args:
        range_id: Database ID of the Range to provision

    Returns:
        Execution ARN if successful, None if not configured
    """
    provision_arn = getattr(settings, "PULUMI_PROVISION_STATE_MACHINE_ARN", None)

    if not provision_arn:
        logger.warning(
            "PULUMI_PROVISION_STATE_MACHINE_ARN not configured, skipping Step Functions. "
            "Set this in settings for production."
        )
        return None

    logger.info(f"Starting Pulumi provisioning (v2) for range_id={range_id}")

    sfn = _get_sfn_client()

    try:
        response = sfn.start_execution(
            stateMachineArn=provision_arn,
            input=json.dumps({"range_id": range_id}),
        )
        execution_arn = response["executionArn"]
        logger.info(f"Started Pulumi provisioning execution: range_id={range_id} execution_arn={execution_arn}")
        return execution_arn

    except ClientError as e:
        logger.error(f"Failed to start Pulumi provisioning for range_id={range_id}: {e}")
        raise


def start_teardown(range_id: int) -> str | None:
    """Start teardown of a range via Step Functions.

    Routes to v1 (Lambda) or v2 (Pulumi) based on Range.provisioner_version.

    Args:
        range_id: Database ID of the Range to teardown

    Returns:
        Execution ARN if successful, None if Step Functions is not configured
        (falls back to stub behavior for local dev)

    Raises:
        ClientError: If Step Functions execution fails to start
    """
    from mission_control.models import Range

    range_obj = Range.objects.get(id=range_id)

    if range_obj.provisioner_version == "v2":
        return _start_pulumi_teardown(range_id)
    else:
        return _start_lambda_teardown(range_id)


def _start_lambda_teardown(range_id: int) -> str | None:
    """Start teardown via Lambda-based Step Functions (v1).

    Args:
        range_id: Database ID of the Range to teardown

    Returns:
        Execution ARN if successful, None if not configured
    """
    teardown_arn = getattr(settings, "TEARDOWN_STATE_MACHINE_ARN", None)

    if not teardown_arn:
        logger.warning(
            "TEARDOWN_STATE_MACHINE_ARN not configured, skipping Step Functions. Set this in settings for production."
        )
        return None

    logger.info(f"Starting Lambda teardown (v1) for range_id={range_id}")

    sfn = _get_sfn_client()

    try:
        response = sfn.start_execution(
            stateMachineArn=teardown_arn,
            input=json.dumps({"range_id": range_id}),
        )
        execution_arn = response["executionArn"]
        logger.info(f"Started Lambda teardown execution: range_id={range_id} execution_arn={execution_arn}")
        return execution_arn

    except ClientError as e:
        logger.error(f"Failed to start Lambda teardown for range_id={range_id}: {e}")
        raise


def _start_pulumi_teardown(range_id: int) -> str | None:
    """Start teardown via Pulumi-based Step Functions (v2).

    Args:
        range_id: Database ID of the Range to teardown

    Returns:
        Execution ARN if successful, None if not configured
    """
    teardown_arn = getattr(settings, "PULUMI_DESTROY_STATE_MACHINE_ARN", None)

    if not teardown_arn:
        logger.warning(
            "PULUMI_DESTROY_STATE_MACHINE_ARN not configured, skipping Step Functions. "
            "Set this in settings for production."
        )
        return None

    logger.info(f"Starting Pulumi teardown (v2) for range_id={range_id}")

    sfn = _get_sfn_client()

    try:
        response = sfn.start_execution(
            stateMachineArn=teardown_arn,
            input=json.dumps({"range_id": range_id}),
        )
        execution_arn = response["executionArn"]
        logger.info(f"Started Pulumi teardown execution: range_id={range_id} execution_arn={execution_arn}")
        return execution_arn

    except ClientError as e:
        logger.error(f"Failed to start Pulumi teardown for range_id={range_id}: {e}")
        raise


def get_execution_status(execution_arn: str) -> dict | None:
    """Get the status of a Step Functions execution.

    Args:
        execution_arn: ARN of the execution to check

    Returns:
        Dict with status info, or None if not configured
    """
    if not execution_arn:
        return None

    sfn = _get_sfn_client()

    try:
        response = sfn.describe_execution(executionArn=execution_arn)
        return {
            "status": response["status"],
            "start_date": response.get("startDate"),
            "stop_date": response.get("stopDate"),
        }
    except ClientError as e:
        logger.error(f"Failed to get execution status: {e}")
        return None
