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

from executors.base import ActionExecutor
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

    @property
    def error(self) -> str | None:
        """Get error message from failed step, if any."""
        for step_result in self.step_results:
            if not step_result.success:
                return step_result.stderr or f"Step '{step_result.step_name}' failed"
        return None


@runtime_checkable
class OpsStep(Protocol):
    """Protocol for operations plan steps.

    A step names a single allowlisted action. Parameter validation is owned by
    the ``ActionExecutor`` allowlist (the single source of truth), so steps do
    not carry a duplicate ``params`` declaration.
    """

    name: str
    action: str


@runtime_checkable
class OpsPlan(Protocol):
    """Protocol for operations plans.

    ``steps`` is a read-only property so implementations may expose it as a
    ``ClassVar`` constant (the ops plans), an instance attribute, or a property
    (``SetupPlan``) and still conform. ``name`` is intentionally not required:
    ``orchestrate`` reads it via ``getattr(plan, "name", type(plan).__name__)``,
    so plans that omit it still work.
    """

    @property
    def steps(self) -> list[Any]: ...

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

    def __init__(self, executor: ActionExecutor) -> None:
        """Initialize OpsOrchestrator.

        Args:
            executor: ActionExecutor used to dispatch allowlisted provider
                actions (e.g. AWSExecutor).
        """
        logger.debug("__init__: executor=%s", type(executor).__name__)
        self.executor = executor

    def orchestrate(
        self,
        instance_id: str,
        plan: OpsPlan,
        context: dict[str, Any],
        **kwargs: Any,
    ) -> OpsResult:
        """Execute an operations plan.

        Args:
            instance_id: Target for the operation. The semantic meaning varies
                by operation type:
                - Start/Stop: AWS EC2 Instance ID (e.g., "i-099ee928142d5f092")
                - Route operations: May be different resource IDs
                Used primarily for logging; actual parameters come from context.
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
            result = self._execute_step(step, context)
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
        step: OpsStep,
        context: dict[str, Any],
    ) -> StepResult:
        """Execute a single operations step.

        Args:
            step: Step to execute with an ``action`` attribute.
            context: Dict containing parameter values for the action.

        Returns:
            StepResult with step output.
        """
        action = getattr(step, "action", "")
        logger.debug("_execute_step: step=%s action=%s", step.name, action)

        # Dispatch against the declared action port. The executor owns the
        # closed action allowlist and validates required parameters from
        # ``context`` before any provider mutation.
        result = self.executor.execute_action(action, context)

        if result.success:
            logger.debug("_execute_step: completed step=%s", step.name)
        else:
            # Log stable identifiers only; provider stderr/payloads may carry
            # unbounded or sensitive detail and must not enter provisioner logs.
            logger.warning("_execute_step: failed step=%s action=%s", step.name, action)

        return StepResult(
            step_name=step.name,
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
        )
