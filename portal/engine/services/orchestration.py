"""Range orchestration service.

This module handles the lifecycle operations for ranges:
- launch: Create and provision a new range
- cancel: Cancel a range that's still provisioning
- destroy: Tear down an active or failed range
"""

from django.utils import timezone

from mission_control.models import ActivityLog, Range
from mission_control.services.engine import start_provisioning, start_teardown

from .allocation import allocate_subnet_index
from .scenarios import get_scenario_config, validate_launch


class OrchestrationError(Exception):
    """Error raised when a range orchestration operation fails.

    Includes an HTTP status code for convenient error handling in views.
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def launch(user, agent_id: int, scenario: str) -> Range:
    """Launch a new cyber range.

    Args:
        user: The user launching the range
        agent_id: ID of the agent to use for victim instances
        scenario: Scenario type (basic, ad_attack_lab)

    Returns:
        Range: The newly created range object

    Raises:
        OrchestrationError: If user already has an active range (409)
        ScenarioValidationError: If agent or scenario validation fails
        AllocationError: If no subnet indices are available
    """
    # Check for existing active range
    active_range = Range.get_active_for_user(user)
    if active_range:
        raise OrchestrationError(
            "You already have an active range. Destroy it first.",
            status_code=409,
        )

    # Validate agent and scenario constraints
    # This will raise ScenarioValidationError if validation fails
    agent, dc_agent = validate_launch(user, agent_id, scenario)

    # Allocate subnet index for this range
    # This will raise AllocationError if no indices available
    subnet_index = allocate_subnet_index()

    # Get instance configuration for scenario
    instance_config = get_scenario_config(scenario, agent.os.name)

    # Create range record with allocated subnet index and instance config
    range_obj = Range.objects.create(
        user=user,
        agent=agent,
        dc_agent=dc_agent,
        status=Range.Status.PROVISIONING,
        subnet_index=subnet_index,
        instance_config=instance_config,
    )

    # Log activity
    ActivityLog.log(
        "range_launched",
        user=user,
        range_id=range_obj.id,
        agent_id=agent.id,
        agent_name=agent.name,
        dc_agent_id=dc_agent.id if dc_agent else None,
        dc_agent_name=dc_agent.name if dc_agent else None,
        scenario=scenario,
    )

    # Trigger provisioning via ECS Fargate
    task_arn = start_provisioning(range_obj.id)

    # Store task ARN if returned (None in local dev without ECS)
    if task_arn:
        range_obj.step_function_execution_arn = task_arn
        range_obj.save(update_fields=["step_function_execution_arn"])

    return range_obj


def cancel(user) -> None:
    """Cancel a provisioning range.

    Only works for ranges in PENDING or PROVISIONING status.

    Args:
        user: The user whose range to cancel

    Raises:
        OrchestrationError: If no active range (404) or range not cancellable (400)
    """
    active_range = Range.get_active_for_user(user)
    if not active_range:
        raise OrchestrationError("No active range", status_code=404)

    if active_range.status not in (Range.Status.PENDING, Range.Status.PROVISIONING):
        raise OrchestrationError(
            f"Cannot cancel range in {active_range.status} status",
            status_code=400,
        )

    active_range.status = Range.Status.DESTROYED
    active_range.destroyed_at = timezone.now()
    active_range.save(update_fields=["status", "destroyed_at"])

    ActivityLog.log(
        "range_cancelled",
        user=user,
        range_id=active_range.id,
    )


def destroy(user) -> None:
    """Destroy an active, paused, or failed range.

    Sets status to DESTROYING and triggers async resource cleanup.

    Args:
        user: The user whose range to destroy

    Raises:
        OrchestrationError: If no destroyable range (404)
    """
    # Use get_destroyable_for_user to include FAILED ranges
    range_to_destroy = Range.get_destroyable_for_user(user)
    if not range_to_destroy:
        raise OrchestrationError("No range to destroy", status_code=404)

    # Mark as DESTROYING - user sees it as gone, can launch new range
    # Resource cleanup happens async, provisioner sets DESTROYED when done
    range_to_destroy.status = Range.Status.DESTROYING
    range_to_destroy.save(update_fields=["status"])

    ActivityLog.log(
        "range_destroyed",
        user=user,
        range_id=range_to_destroy.id,
    )

    # Trigger async resource cleanup via ECS Fargate
    task_arn = start_teardown(range_to_destroy.id)

    # Store task ARN if returned (None in local dev without ECS)
    if task_arn:
        range_to_destroy.step_function_execution_arn = task_arn
        range_to_destroy.save(update_fields=["step_function_execution_arn"])
