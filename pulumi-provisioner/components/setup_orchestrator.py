"""Setup orchestrator for running setup plans.

SetupOrchestrator takes a SetupPlan and an SSMExecutor, and runs the plan
step by step, handling reboots and verification.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from .ssm_executor import (
    SSMExecutor,
    CommandResult,
    CommandError,
    TimeoutError,
    SSMExecutorError,
)
from .setup_plan import SetupPlan, SetupStep


class SetupError(Exception):
    """Raised when setup fails at any step."""

    def __init__(self, message: str, step_name: Optional[str] = None, cause: Optional[Exception] = None):
        self.step_name = step_name
        self.cause = cause
        super().__init__(message)


@dataclass
class StepResult:
    """Result of executing a single step."""
    step_name: str
    success: bool
    stdout: str = ""
    stderr: str = ""


@dataclass
class SetupResult:
    """Result of a complete setup orchestration."""
    success: bool
    step_results: List[StepResult] = field(default_factory=list)
    verification_result: Optional[StepResult] = None


class SetupOrchestrator:
    """Orchestrates setup plan execution.

    Runs setup plans using an SSMExecutor, handling:
    - Step sequencing
    - Template rendering
    - Reboot handling
    - Verification
    - Error propagation
    """

    # Default reboot timeout (5 minutes)
    DEFAULT_REBOOT_TIMEOUT = 300

    def __init__(self, executor: SSMExecutor):
        """Initialize orchestrator with an executor.

        Args:
            executor: SSMExecutor to use for running commands
        """
        self.executor = executor

    def orchestrate(
        self,
        instance_id: str,
        plan: SetupPlan,
        context: Dict[str, Any],
    ) -> SetupResult:
        """Execute a setup plan on an instance.

        Args:
            instance_id: Target EC2 instance ID
            plan: SetupPlan defining steps to execute
            context: Template variables for rendering scripts

        Returns:
            SetupResult with success status and step outputs

        Raises:
            SetupError: If any step fails or verification fails
        """
        step_results: List[StepResult] = []

        # Execute each step in order
        for step in plan.steps:
            try:
                result = self._execute_step(instance_id, step, context)
                step_results.append(result)

                # Handle reboot if required
                if step.requires_reboot:
                    reboot_timeout = max(step.timeout_seconds, self.DEFAULT_REBOOT_TIMEOUT)
                    try:
                        self.executor.reboot_and_wait(instance_id, timeout=reboot_timeout)
                    except (TimeoutError, SSMExecutorError) as e:
                        raise SetupError(
                            f"Reboot failed after step '{step.name}': {e}",
                            step_name=step.name,
                            cause=e,
                        )

            except (CommandError, TimeoutError, SSMExecutorError) as e:
                raise SetupError(
                    f"Step '{step.name}' failed: {e}",
                    step_name=step.name,
                    cause=e,
                )

        # Run verification if defined
        verify_result = None
        if plan.verify_step is not None:
            try:
                verify_result = self._execute_step(instance_id, plan.verify_step, context)
            except (CommandError, TimeoutError, SSMExecutorError) as e:
                raise SetupError(
                    f"Verification failed: {e}",
                    step_name=plan.verify_step.name,
                    cause=e,
                )

        return SetupResult(
            success=True,
            step_results=step_results,
            verification_result=verify_result,
        )

    def _execute_step(
        self,
        instance_id: str,
        step: SetupStep,
        context: Dict[str, Any],
    ) -> StepResult:
        """Execute a single step.

        Args:
            instance_id: Target instance
            step: Step to execute
            context: Template variables

        Returns:
            StepResult with step output

        Raises:
            CommandError, TimeoutError, SetupError: On failure
        """
        # Render the script with context variables
        rendered_script = self._render_script(step.script, context, step.name)

        # Execute via SSM
        result = self.executor.run_command(
            instance_id=instance_id,
            script=rendered_script,
            timeout_seconds=step.timeout_seconds,
        )

        return StepResult(
            step_name=step.name,
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _render_script(
        self,
        script: str,
        context: Dict[str, Any],
        step_name: str,
    ) -> str:
        """Render a script template with context variables.

        Uses simple {{ variable }} syntax compatible with Jinja2.
        PowerShell $variables are preserved.

        Args:
            script: Script template
            context: Variables to substitute
            step_name: Step name for error messages

        Returns:
            Rendered script

        Raises:
            SetupError: If a required variable is missing
        """
        result = script

        # Find all {{ variable }} patterns
        pattern = r'\{\{\s*(\w+)\s*\}\}'
        matches = re.findall(pattern, script)

        for var_name in matches:
            if var_name not in context:
                raise SetupError(
                    f"Missing template variable '{var_name}' in step '{step_name}'. "
                    f"Available variables: {list(context.keys())}",
                    step_name=step_name,
                )
            # Replace {{ var }} with the value
            result = re.sub(
                r'\{\{\s*' + var_name + r'\s*\}\}',
                str(context[var_name]),
                result,
            )

        return result
