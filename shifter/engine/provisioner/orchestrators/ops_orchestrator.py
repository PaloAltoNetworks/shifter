"""Operations Orchestrator for runtime operations.

OpsOrchestrator handles runtime operations like:
- Starting/stopping instances
- Managing routes
- Executing operational plans

This is a stub implementation that follows the Orchestrator protocol.
Full implementation will be added as needed.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from orchestrators.base import StepResult

logger = logging.getLogger(__name__)


@dataclass
class OpsResult:
    """Result of an operations orchestration.

    Attributes:
        success: True if all steps succeeded.
        step_results: List of results for each executed step.
    """

    success: bool
    step_results: list[StepResult] = field(default_factory=list)


@runtime_checkable
class OpsStep(Protocol):
    """Protocol for operations plan steps."""

    name: str
    action: str
    params: dict


@runtime_checkable
class OpsPlan(Protocol):
    """Protocol for operations plans."""

    steps: list[Any]
    name: str

    def get_context(self, target: Any) -> dict[str, Any]: ...


class OpsOrchestrator:
    """Orchestrates runtime operations.

    Executes operational plans using an executor, handling:
    - Step sequencing
    - Error propagation
    - Result collection

    This is the counterpart to SetupOrchestrator for runtime operations
    rather than initial setup.

    Attributes:
        executor: The executor used for running operations.
    """

    def __init__(self, executor: Any):
        """Initialize OpsOrchestrator.

        Args:
            executor: Executor to use for running operations
                     (AWSExecutor, SSMExecutor, etc.)
        """
        logger.debug("__init__: executor=%s", type(executor).__name__)
        self.executor = executor

    def orchestrate(
        self,
        instance_id: str,
        plan: Any,
        context: dict[str, Any],
        **kwargs: Any,
    ) -> OpsResult:
        """Execute an operations plan.

        Args:
            instance_id: Target instance or resource ID.
            plan: OpsPlan defining steps to execute.
            context: Template variables for the plan.
            **kwargs: Additional arguments for specific executors.

        Returns:
            OpsResult with success status and step outputs.
        """
        plan_name = getattr(plan, "name", type(plan).__name__)
        logger.debug(
            "orchestrate: instance_id=%s plan=%s steps=%d",
            instance_id,
            plan_name,
            len(plan.steps),
        )
        step_results: list[StepResult] = []

        # Execute each step in order
        for step in plan.steps:
            result = self._execute_step(instance_id, step, context)
            step_results.append(result)

            # Stop on first failure
            if not result.success:
                logger.warning(
                    "orchestrate: failed plan=%s step=%s",
                    plan_name,
                    step.name,
                )
                return OpsResult(success=False, step_results=step_results)

        logger.info("orchestrate: completed plan=%s", plan_name)
        return OpsResult(success=True, step_results=step_results)

    def _execute_step(
        self,
        target_id: str,
        step: Any,
        context: dict[str, Any],
    ) -> StepResult:
        """Execute a single operations step.

        Args:
            target_id: Target instance or resource ID (for logging/reference).
            step: Step to execute with action and params attributes.
            context: Dict containing parameter values for the action.

        Returns:
            StepResult with step output.
        """
        action = getattr(step, "action", "")
        logger.debug("_execute_step: step=%s action=%s", step.name, action)

        # Use execute_action() for AWSExecutor to dispatch to specific methods
        if hasattr(self.executor, "execute_action"):
            result = self.executor.execute_action(action, context)
        else:
            # Fallback for other executors (SSMExecutor, etc.)
            result = self.executor.run_command(
                target=target_id,
                action=action,
                params=getattr(step, "params", {}),
            )

        if result.success:
            logger.debug("_execute_step: completed step=%s", step.name)
        else:
            stderr_preview = result.stderr[:200] if result.stderr else ""
            logger.warning("_execute_step: failed step=%s stderr=%s", step.name, stderr_preview)

        return StepResult(
            step_name=step.name,
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
        )
