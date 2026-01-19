"""Setup orchestrator for running setup plans.

SetupOrchestrator takes a SetupPlan and an executor (SSM or SSH), and runs
the plan step by step, handling reboots and verification.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from executors.base import CommandResult
from executors.ssm_executor import (
    CommandError,
    SSMExecutorError,
    TimeoutError,
)
from plans.base import SetupPlan, SetupStep


class Executor(Protocol):
    """Protocol for command executors (SSM or SSH).

    Both SSMExecutor and SSHExecutor implement this protocol with slightly
    different parameter names (host vs instance_id) but compatible call signatures.
    """

    def run_command(
        self,
        instance_id: str,
        script: str,
        timeout_seconds: int = ...,
        document_name: str = ...,
        stdin_input: str | None = ...,
    ) -> CommandResult: ...

    def reboot_and_wait(
        self,
        instance_id: str,
        timeout_seconds: int = ...,
        document_name: str = ...,
    ) -> bool: ...


logger = logging.getLogger(__name__)


class SetupError(Exception):
    """Raised when setup fails at any step."""

    def __init__(self, message: str, step_name: str | None = None, cause: Exception | None = None):
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
    step_results: list[StepResult] = field(default_factory=list)
    verification_result: StepResult | None = None
    error: str | None = None


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

    def __init__(self, executor: Executor):
        """Initialize orchestrator with an executor.

        Args:
            executor: Executor (SSMExecutor or SSHExecutor) to use for running commands
        """
        logger.debug("__init__: executor=%s", type(executor).__name__)
        self.executor = executor

    def orchestrate(
        self,
        instance_id: str,
        plan: SetupPlan,
        context: dict[str, Any],
        document_name: str = "AWS-RunPowerShellScript",
    ) -> SetupResult:
        """Execute a setup plan on an instance.

        Args:
            instance_id: Target for command execution. The semantic meaning varies
                by executor type:
                - SSMExecutor: AWS EC2 Instance ID (e.g., "i-099ee928142d5f092")
                - SSHExecutor: IP address or hostname (e.g., "10.0.1.5")
                This parameter is named generically; callers must provide the
                appropriate value for their executor.
            plan: SetupPlan defining steps to execute
            context: Template variables for rendering scripts
            document_name: SSM document to use (AWS-RunShellScript for Linux,
                AWS-RunPowerShellScript for Windows)

        Returns:
            SetupResult with success status and step outputs

        Raises:
            SetupError: If any step fails or verification fails
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
            try:
                result = self._execute_step(instance_id, step, context, document_name)
                step_results.append(result)

                # Handle reboot if required
                if step.requires_reboot:
                    reboot_timeout = max(step.timeout_seconds, self.DEFAULT_REBOOT_TIMEOUT)
                    logger.debug("orchestrate: rebooting after step=%s", step.name)
                    try:
                        self.executor.reboot_and_wait(
                            instance_id,
                            timeout_seconds=reboot_timeout,
                            document_name=document_name,
                        )
                        logger.debug("orchestrate: reboot completed")
                    except (TimeoutError, SSMExecutorError) as e:
                        logger.error("orchestrate: reboot failed step=%s", step.name)
                        raise SetupError(
                            f"Reboot failed after step '{step.name}': {e}",
                            step_name=step.name,
                            cause=e,
                        ) from e

            except (CommandError, TimeoutError, SSMExecutorError) as e:
                logger.error("orchestrate: step failed step=%s error=%s", step.name, e)
                raise SetupError(
                    f"Step '{step.name}' failed: {e}",
                    step_name=step.name,
                    cause=e,
                ) from e

        # Run verification if defined
        verify_result = None
        if plan.verify_step is not None:
            logger.debug("orchestrate: running verification step")
            try:
                verify_result = self._execute_step(instance_id, plan.verify_step, context, document_name)
            except (CommandError, TimeoutError, SSMExecutorError) as e:
                logger.error("orchestrate: verification failed error=%s", e)
                raise SetupError(
                    f"Verification failed: {e}",
                    step_name=plan.verify_step.name,
                    cause=e,
                ) from e

        logger.info("orchestrate: completed plan=%s", plan_name)
        return SetupResult(
            success=True,
            step_results=step_results,
            verification_result=verify_result,
        )

    def _execute_step(
        self,
        instance_id: str,
        step: SetupStep,
        context: dict[str, Any],
        document_name: str,
        max_retries: int = 4,
    ) -> StepResult:
        """Execute a single step with retry support.

        Args:
            instance_id: Target instance
            step: Step to execute
            context: Template variables
            document_name: SSM document to use
            max_retries: Number of retry attempts on failure (default 1)

        Returns:
            StepResult with step output

        Raises:
            CommandError, TimeoutError, SetupError: On failure after retries
        """
        import time

        logger.info("_execute_step: starting step=%s", step.name)
        # Render the script and stdin_input with context variables
        rendered_script = self._render_script(step.script, context, step.name)
        rendered_stdin = self._render_script(getattr(step, "stdin_input", "") or "", context, step.name)

        last_result = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.info("_execute_step: retry %d/%d for step=%s", attempt, max_retries, step.name)
                time.sleep(15)  # Pause before retry

            # Execute via executor (SSM or SSH)
            result = self.executor.run_command(
                instance_id=instance_id,
                script=rendered_script,
                timeout_seconds=step.timeout_seconds,
                document_name=document_name,
                stdin_input=rendered_stdin if rendered_stdin else None,
            )
            last_result = result

            # Check for PAN-OS commit success if commit was attempted
            if not self._check_commit_success(result.stdout):
                logger.warning(
                    "_execute_step: PAN-OS commit failed in step=%s, output=%s",
                    step.name,
                    result.stdout[:500] if result.stdout else "(no output)",
                )
                if attempt < max_retries:
                    continue  # Retry
                else:
                    raise SetupError(
                        f"Step '{step.name}' failed: PAN-OS commit did not succeed",
                        step_name=step.name,
                    )

            if result.success:
                # Log success with output summary
                stdout_preview = result.stdout[:500] if result.stdout else "(no output)"
                logger.info(
                    "_execute_step: completed step=%s output=%s",
                    step.name,
                    stdout_preview,
                )
                return StepResult(
                    step_name=step.name,
                    success=True,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            else:
                logger.warning(
                    "_execute_step: failed step=%s attempt=%d stderr=%s",
                    step.name,
                    attempt + 1,
                    result.stderr[:200] if result.stderr else "",
                )
                if attempt < max_retries:
                    continue  # Retry

        # All retries exhausted
        return StepResult(
            step_name=step.name,
            success=False,
            stdout=last_result.stdout if last_result else "",
            stderr=last_result.stderr if last_result else "",
        )

    def _check_commit_success(self, output: str) -> bool:
        """Check if PAN-OS commit succeeded.

        PAN-OS outputs "Configuration committed successfully" on successful commits.
        If the output contains a commit command but not this success message,
        the commit failed.

        Args:
            output: Command output to check

        Returns:
            True if no commit was attempted or commit succeeded, False if commit failed
        """
        if not output:
            return True
        # Check if this was a commit operation
        if "commit" not in output.lower():
            return True
        # If commit was attempted, check for success message
        return "Configuration committed successfully" in output

    def _render_script(
        self,
        script: str,
        context: dict[str, Any],
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
        pattern = r"\{\{\s*(\w+)\s*\}\}"
        matches = re.findall(pattern, script)

        for var_name in matches:
            if var_name not in context:
                logger.error(
                    "_render_script: missing variable=%s step=%s available=%s",
                    var_name,
                    step_name,
                    list(context.keys()),
                )
                raise SetupError(
                    f"Missing template variable '{var_name}' in step '{step_name}'. "
                    f"Available variables: {list(context.keys())}",
                    step_name=step_name,
                )
            # Replace {{ var }} with the value
            result = re.sub(
                r"\{\{\s*" + var_name + r"\s*\}\}",
                str(context[var_name]),
                result,
            )

        return result
