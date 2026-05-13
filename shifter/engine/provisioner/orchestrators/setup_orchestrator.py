"""Setup orchestrator for running setup plans.

SetupOrchestrator takes a SetupPlan and an executor (SSM or SSH), and runs
the plan step by step, handling reboots and verification.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from executors.base import (
    CommandResult,
    Executor,
    ExecutorConnectionError,
    ExecutorError,
    ExecutorTimeoutError,
)
from plans.base import SetupPlan, SetupStep

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


# Internal discriminated outcome of a single attempt inside `_execute_step`.
# The retry loop dispatches on these; this keeps per-attempt control flow
# out of the loop body so the loop itself stays trivially readable.
@dataclass(frozen=True)
class _AttemptSuccess:
    result: CommandResult


@dataclass(frozen=True)
class _AttemptRetry:
    """Attempt should be retried (or, if retries exhausted, fall through to
    a failed StepResult). `last_result` carries the most recent CommandResult
    if one was produced (None for pre-execution transport errors)."""

    last_result: CommandResult | None


@dataclass(frozen=True)
class _AttemptFailHard:
    """Attempt failure that must propagate as `SetupError` (no fallthrough)."""

    error: "SetupError"


_AttemptOutcome = _AttemptSuccess | _AttemptRetry | _AttemptFailHard


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
    SENSITIVE_ENV_VARS = (
        "DC_DOMAIN_PASSWORD",
        # Defense in depth (#762): if a per-instance RDP password is ever
        # forwarded into setup orchestration as an env var (e.g., a future
        # plan that needs to chpasswd through SSM), keep the value out of
        # captured stdout/stderr.
        "RDP_PASSWORD",
        "GUEST_PASSWORD",
    )
    SENSITIVE_CONTEXT_KEY_PARTS = ("password", "secret", "token")

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

                # Check if step failed (returned success=False after retries)
                if not result.success:
                    logger.error(
                        "orchestrate: step '%s' failed after retries",
                        step.name,
                    )
                    raise SetupError(
                        f"Step '{step.name}' failed after all retry attempts",
                        step_name=step.name,
                    )

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
                    except ExecutorError as e:
                        logger.error("orchestrate: reboot failed step=%s", step.name)
                        raise SetupError(
                            f"Reboot failed after step '{step.name}': {e}",
                            step_name=step.name,
                            cause=e,
                        ) from e

            except ExecutorError as e:
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
            except ExecutorError as e:
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

        Per-attempt logic lives in `_run_one_attempt`, which returns an
        `_AttemptOutcome` so this loop only has to dispatch on three cases:
        success (return), hard failure (raise), retry (loop or fall through).

        Raises:
            SetupError: transport-error / PAN-OS poll-fail / silent-commit-fail
                after retries are exhausted.
        """
        import time

        logger.info("_execute_step: starting step=%s", step.name)
        rendered_script = self._render_script(step.script, context, step.name)
        rendered_stdin = self._render_script(step.stdin_input or "", context, step.name)

        last_result: CommandResult | None = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.info("_execute_step: retry %d/%d for step=%s", attempt, max_retries, step.name)
                time.sleep(15)

            outcome = self._run_one_attempt(
                instance_id,
                step,
                rendered_script,
                rendered_stdin,
                context,
                document_name,
                attempt,
                max_retries,
            )
            if isinstance(outcome, _AttemptSuccess):
                self._log_step_success(step, outcome.result, context)
                return StepResult(
                    step_name=step.name,
                    success=True,
                    stdout=outcome.result.stdout,
                    stderr=outcome.result.stderr,
                )
            if isinstance(outcome, _AttemptFailHard):
                raise outcome.error
            # _AttemptRetry: remember last result, loop again
            last_result = outcome.last_result

        # All retries exhausted on the soft-failure path (exit-nonzero).
        # Asymmetry preserved: this path RETURNS a failed StepResult; the
        # hard-failure paths above RAISE via _AttemptFailHard.
        return StepResult(
            step_name=step.name,
            success=False,
            stdout=last_result.stdout if last_result else "",
            stderr=last_result.stderr if last_result else "",
        )

    def _run_one_attempt(
        self,
        instance_id: str,
        step: SetupStep,
        rendered_script: str,
        rendered_stdin: str,
        context: dict[str, Any],
        document_name: str,
        attempt: int,
        max_retries: int,
    ) -> _AttemptOutcome:
        """Execute one attempt and classify the outcome."""
        try:
            result = self.executor.run_command(
                instance_id=instance_id,
                script=rendered_script,
                timeout_seconds=step.timeout_seconds,
                document_name=document_name,
                stdin_input=rendered_stdin if rendered_stdin else None,
            )
        except (ExecutorConnectionError, ExecutorTimeoutError) as e:
            logger.warning(
                "_execute_step: transport error step=%s attempt=%d: %s",
                step.name,
                attempt + 1,
                e,
            )
            if attempt < max_retries:
                return _AttemptRetry(last_result=None)
            return _AttemptFailHard(
                SetupError(
                    f"Step '{step.name}' failed: transport error after {max_retries + 1} attempts: {e}",
                    step_name=step.name,
                    cause=e,
                )
            )

        if not result.success:
            self._log_step_failure(step, result, attempt, max_retries, context)
            return _AttemptRetry(last_result=result)

        return self._classify_successful_attempt(
            instance_id,
            step,
            result,
            context,
            document_name,
            attempt,
            max_retries,
        )

    def _classify_successful_attempt(
        self,
        instance_id: str,
        step: SetupStep,
        result: CommandResult,
        context: dict[str, Any],
        document_name: str,
        attempt: int,
        max_retries: int,
    ) -> _AttemptOutcome:
        """Post-process an exit-0 CommandResult with PAN-OS-specific checks."""
        self._log_panos_commit_outcome(step.name, result.stdout)

        if step.poll_for_job:
            poll_outcome = self._handle_panos_poll(
                instance_id,
                step,
                result,
                document_name,
                attempt,
                max_retries,
            )
            if not isinstance(poll_outcome, _AttemptSuccess):
                return poll_outcome
            result = poll_outcome.result

        if not self._check_commit_success(result.stdout):
            logger.warning(
                "_execute_step: PAN-OS commit failed step=%s attempt=%d/%d",
                step.name,
                attempt + 1,
                max_retries + 1,
            )
            if result.stdout:
                logger.warning(
                    "_execute_step: step=%s COMMIT FAILED STDOUT:\n%s",
                    step.name,
                    self._mask_sensitive_output(result.stdout, context),
                )
            if attempt < max_retries:
                return _AttemptRetry(last_result=result)
            return _AttemptFailHard(
                SetupError(
                    f"Step '{step.name}' failed: PAN-OS commit failed after {max_retries + 1} attempts",
                    step_name=step.name,
                )
            )

        return _AttemptSuccess(result=result)

    def _handle_panos_poll(
        self,
        instance_id: str,
        step: SetupStep,
        result: CommandResult,
        document_name: str,
        attempt: int,
        max_retries: int,
    ) -> _AttemptOutcome:
        """Resolve a `poll_for_job` step: parse job id, poll, augment result."""
        job_id = self._parse_panos_job_id(result.stdout)
        if not job_id:
            logger.warning("_execute_step: poll_for_job enabled but no job ID found in output")
            return _AttemptSuccess(result=result)

        logger.info("_execute_step: polling for job %s completion", job_id)
        poll_success, poll_output = self._poll_panos_job(
            instance_id,
            job_id,
            step.timeout_seconds,
            document_name,
        )
        if not poll_success:
            if attempt < max_retries:
                return _AttemptRetry(last_result=result)
            return _AttemptFailHard(
                SetupError(
                    f"Step '{step.name}' failed: PAN-OS job {job_id} did not complete successfully",
                    step_name=step.name,
                )
            )

        return _AttemptSuccess(
            result=CommandResult(
                success=True,
                exit_code=0,
                stdout=result.stdout + "\n" + poll_output,
                stderr=result.stderr,
            )
        )

    @staticmethod
    def _log_panos_commit_outcome(step_name: str, stdout: str) -> None:
        """Classify and log a PAN-OS commit line if present in stdout."""
        if not stdout or "commit" not in stdout.lower():
            return
        output_lower = stdout.lower()
        if "configuration committed successfully" in output_lower:
            outcome = "immediate_success"
        elif "there are no changes to commit" in output_lower:
            outcome = "no_changes"
        elif "jobid" in output_lower:
            outcome = "job_enqueued"
        else:
            outcome = "unknown_output"
        logger.info("_execute_step: step=%s commit=%s", step_name, outcome)

    def _log_step_success(
        self,
        step: SetupStep,
        result: CommandResult,
        context: dict[str, Any],
    ) -> None:
        logger.info(
            "_execute_step: completed step=%s exit_code=%d",
            step.name,
            result.exit_code,
        )
        if result.stdout:
            logger.info(
                "_execute_step: step=%s STDOUT:\n%s",
                step.name,
                self._mask_sensitive_output(result.stdout, context),
            )
        if result.stderr:
            logger.info(
                "_execute_step: step=%s STDERR:\n%s",
                step.name,
                self._mask_sensitive_output(result.stderr, context),
            )

    def _log_step_failure(
        self,
        step: SetupStep,
        result: CommandResult,
        attempt: int,
        max_retries: int,
        context: dict[str, Any],
    ) -> None:
        logger.warning(
            "_execute_step: FAILED step=%s attempt=%d/%d exit_code=%d",
            step.name,
            attempt + 1,
            max_retries + 1,
            result.exit_code,
        )
        if result.stdout:
            logger.warning(
                "_execute_step: step=%s FAILED STDOUT:\n%s",
                step.name,
                self._mask_sensitive_output(result.stdout, context),
            )
        if result.stderr:
            logger.warning(
                "_execute_step: step=%s FAILED STDERR:\n%s",
                step.name,
                self._mask_sensitive_output(result.stderr, context),
            )

    @classmethod
    def _mask_sensitive_output(cls, output: str, context: dict[str, Any] | None = None) -> str:
        """Mask known secret values before writing command output to logs."""
        if not output:
            return output

        masked_output = output
        for sensitive_value in cls._sensitive_values(context):
            masked_output = masked_output.replace(sensitive_value, "[REDACTED]")
        return masked_output

    @classmethod
    def _sensitive_values(cls, context: dict[str, Any] | None = None) -> list[str]:
        values = {value for env_var in cls.SENSITIVE_ENV_VARS if (value := os.environ.get(env_var))}

        if context:
            for key, value in context.items():
                if value is not None and cls._is_sensitive_context_key(key):
                    values.add(str(value))

        return sorted((value for value in values if value), key=len, reverse=True)

    @classmethod
    def _is_sensitive_context_key(cls, key: str) -> bool:
        normalized_key = key.lower()
        return any(part in normalized_key for part in cls.SENSITIVE_CONTEXT_KEY_PARTS)

    def _check_commit_success(self, output: str) -> bool:
        """Check if PAN-OS commit succeeded.

        PAN-OS outputs "Configuration committed successfully" on successful commits.
        If there are no changes to commit, PAN-OS outputs "There are no changes to commit"
        which is also considered success (idempotent behavior).
        If the output contains a commit command but neither success message,
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
        # If commit was attempted, check for success messages
        if "Configuration committed successfully" in output:
            return True
        if "There are no changes to commit" in output:
            return True
        # If we polled a commit job, the stdout may include job status output
        output_lower = output.lower()
        return ("fin" in output_lower) and ("ok" in output_lower)

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
                    "_render_script: missing variable=%s step=%s context_keys=%d",
                    var_name,
                    step_name,
                    len(context),
                )
                raise SetupError(
                    f"Missing template variable '{var_name}' in step '{step_name}'. "
                    "Required variables are missing from the supplied context.",
                    step_name=step_name,
                )
            # Replace {{ var }} with the value
            result = re.sub(
                r"\{\{\s*" + var_name + r"\s*\}\}",
                str(context[var_name]),
                result,
            )

        return result

    def _parse_panos_job_id(self, output: str) -> str | None:
        """Parse PAN-OS job ID from command output.

        Looks for patterns like "job enqueued with jobid 19" in the output.

        Args:
            output: Command output to parse

        Returns:
            Job ID string if found, None otherwise
        """
        if not output:
            return None
        # Match patterns like "job enqueued with jobid 19" or "jobid 19"
        match = re.search(r"jobid\s+(\d+)", output, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _poll_panos_job(
        self,
        instance_id: str,
        job_id: str,
        timeout_seconds: int,
        document_name: str,
        poll_interval: int = 10,
    ) -> tuple[bool, str]:
        """Poll PAN-OS job until completion.

        Args:
            instance_id: Target instance (IP for SSH)
            job_id: PAN-OS job ID to poll
            timeout_seconds: Maximum time to wait for job completion
            document_name: SSM document name
            poll_interval: Seconds between poll attempts

        Returns:
            Tuple of (success, final_output)
        """
        import time

        start_time = time.time()
        last_output = ""

        while time.time() - start_time < timeout_seconds:
            # Run show jobs id <job_id>
            try:
                result = self.executor.run_command(
                    instance_id=instance_id,
                    script="",
                    timeout_seconds=60,
                    document_name=document_name,
                    stdin_input=f"show jobs id {job_id}\n",
                )
            except (ExecutorConnectionError, ExecutorTimeoutError) as e:
                logger.warning("_poll_panos_job: transport error, retrying: %s", e)
                time.sleep(poll_interval)
                continue
            last_output = result.stdout

            if not result.success:
                logger.warning("_poll_panos_job: poll command failed, retrying")
                time.sleep(poll_interval)
                continue

            # Check for job completion - look for "FIN" in Status column
            # Output format: "... Status Result ..." with "FIN" and "OK" when done
            if "FIN" in result.stdout:
                # Check if result is OK
                if "OK" in result.stdout:
                    logger.info("_poll_panos_job: job %s completed successfully", job_id)
                    return True, result.stdout
                else:
                    logger.error("_poll_panos_job: job %s finished with error", job_id)
                    return False, result.stdout

            logger.debug("_poll_panos_job: job %s still running", job_id)
            time.sleep(poll_interval)

        logger.error("_poll_panos_job: timeout waiting for job %s", job_id)
        return False, last_output
