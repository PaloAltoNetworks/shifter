"""Shared orchestrator types.

Defines the ``StepResult`` dataclass returned by both orchestrators for each
executed step. The two orchestrators (``SetupOrchestrator``,
``OpsOrchestrator``) depend on distinct executor ports and have distinct plan
and result contracts, so there is deliberately no shared ``Orchestrator``
protocol — a single ``Any``-typed protocol would only hide those two contracts.
"""

from dataclasses import dataclass


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
