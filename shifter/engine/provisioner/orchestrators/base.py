"""Base orchestrator protocol and shared types.

Defines the Orchestrator protocol that all orchestrators (Setup, Ops) must implement,
and the StepResult dataclass for returning step execution results.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable, Any, Dict, List


@dataclass
class StepResult:
    """Result of executing a single step.

    Attributes:
        step_name: Name/identifier of the step that was executed.
        success: Whether the step completed successfully.
        stdout: Standard output from the step execution.
        stderr: Standard error output from the step execution.
    """

    step_name: str
    success: bool
    stdout: str = ""
    stderr: str = ""


@runtime_checkable
class Orchestrator(Protocol):
    """Protocol for plan orchestrators.

    All orchestrators (SetupOrchestrator, OpsOrchestrator) should implement
    this protocol to ensure consistent interfaces.

    The protocol defines the minimal interface required:
    - orchestrate: Execute a plan on a target
    """

    def orchestrate(
        self,
        instance_id: str,
        plan: Any,
        context: Dict[str, Any],
        **kwargs,
    ) -> Any:
        """Execute a plan on the target instance.

        Args:
            instance_id: Target instance identifier
            plan: The plan to execute (SetupPlan or similar)
            context: Template variables for script rendering
            **kwargs: Additional orchestrator-specific arguments

        Returns:
            Result object containing step results and success status
        """
        ...
