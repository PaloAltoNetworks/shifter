"""Operations Orchestrator for runtime operations.

OpsOrchestrator handles runtime operations like:
- Starting/stopping instances
- Managing routes
- Executing operational plans

This is a stub implementation that follows the Orchestrator protocol.
Full implementation will be added as needed.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable

from orchestrators.base import StepResult


@dataclass
class OpsResult:
    """Result of an operations orchestration.

    Attributes:
        success: True if all steps succeeded.
        step_results: List of results for each executed step.
    """

    success: bool
    step_results: List[StepResult] = field(default_factory=list)


@runtime_checkable
class OpsStep(Protocol):
    """Protocol for operations plan steps."""

    name: str
    action: str
    params: dict


@runtime_checkable
class OpsPlan(Protocol):
    """Protocol for operations plans."""

    steps: List[Any]
    name: str

    def get_context(self, target: Any) -> Dict[str, Any]:
        ...


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
        self.executor = executor

    def orchestrate(
        self,
        instance_id: str,
        plan: Any,
        context: Dict[str, Any],
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
        step_results: List[StepResult] = []

        # Execute each step in order
        for step in plan.steps:
            result = self._execute_step(instance_id, step, context)
            step_results.append(result)

            # Stop on first failure
            if not result.success:
                return OpsResult(success=False, step_results=step_results)

        return OpsResult(success=True, step_results=step_results)

    def _execute_step(
        self,
        target_id: str,
        step: Any,
        context: Dict[str, Any],
    ) -> StepResult:
        """Execute a single operations step.

        Args:
            target_id: Target instance or resource ID.
            step: Step to execute.
            context: Template variables.

        Returns:
            StepResult with step output.
        """
        # Execute via the executor
        # The step's action and params determine what gets executed
        result = self.executor.run_command(
            target=target_id,
            action=getattr(step, "action", ""),
            params=getattr(step, "params", {}),
        )

        return StepResult(
            step_name=step.name,
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
        )
