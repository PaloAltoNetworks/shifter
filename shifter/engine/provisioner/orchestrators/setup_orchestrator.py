"""Setup orchestrator for running setup plans.

SetupOrchestrator takes a SetupPlan and an executor (SSM or SSH), and runs
the plan step by step, handling reboots and verification.

The class is split across three sibling modules to keep this file under
Sonar's file-length ceiling without changing the public surface:

- ``_setup_types``: public dataclasses (`SetupError`, `StepResult`,
  `SetupResult`) plus internal per-attempt types used by the retry loop.
- ``_setup_logging``: `_SetupOrchestratorLoggingMixin` (step-result logging,
  sensitive-value masking, `{{ var }}` template rendering).
- ``_setup_panos``: `_SetupOrchestratorPanOSMixin` (PAN-OS commit detection,
  job-id parsing, job polling, poll-result handling, and the
  `_classify_successful_attempt` post-processing that wires them in).

The public types are re-exported here so existing
``from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator``
imports continue to work.
"""

import logging
import time
from typing import Any

from executors.base import (
    Executor,
    ExecutorConnectionError,
    ExecutorError,
    ExecutorTimeoutError,
)
from log_redact import safe_log_value
from orchestrators._setup_logging import _SetupOrchestratorLoggingMixin
from orchestrators._setup_panos import _SetupOrchestratorPanOSMixin
from orchestrators._setup_types import (
    SetupError,
    SetupResult,
    StepResult,
    _AttemptFailHard,
    _AttemptOutcome,
    _AttemptRetry,
    _AttemptSuccess,
    _StepAttemptContext,
)
from plans.base import SetupPlan, SetupStep

logger = logging.getLogger(__name__)

__all__ = [
    "SetupError",
    "SetupOrchestrator",
    "SetupResult",
    "StepResult",
]


class SetupOrchestrator(_SetupOrchestratorPanOSMixin, _SetupOrchestratorLoggingMixin):
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

    def __init__(self, executor: Executor) -> None:
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
            safe_log_value(instance_id),
            safe_log_value(plan_name),
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
        logger.info("_execute_step: starting step=%s", step.name)
        rendered_script = self._render_script(step.script, context, step.name)
        rendered_stdin = self._render_script(step.stdin_input or "", context, step.name)

        last_result = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.info("_execute_step: retry %d/%d for step=%s", attempt, max_retries, step.name)
                time.sleep(15)

            outcome = self._run_one_attempt(
                _StepAttemptContext(
                    instance_id=instance_id,
                    step=step,
                    rendered_script=rendered_script,
                    rendered_stdin=rendered_stdin,
                    context=context,
                    document_name=document_name,
                    attempt=attempt,
                    max_retries=max_retries,
                )
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

    def _run_one_attempt(self, attempt_ctx: _StepAttemptContext) -> _AttemptOutcome:
        """Execute one attempt and classify the outcome."""
        step = attempt_ctx.step
        try:
            result = self.executor.run_command(
                instance_id=attempt_ctx.instance_id,
                script=attempt_ctx.rendered_script,
                timeout_seconds=step.timeout_seconds,
                document_name=attempt_ctx.document_name,
                stdin_input=attempt_ctx.rendered_stdin if attempt_ctx.rendered_stdin else None,
            )
        except (ExecutorConnectionError, ExecutorTimeoutError) as e:
            logger.warning(
                "_execute_step: transport error step=%s attempt=%d: %s",
                step.name,
                attempt_ctx.attempt + 1,
                e,
            )
            return (
                _AttemptRetry(last_result=None)
                if attempt_ctx.attempt < attempt_ctx.max_retries
                else _AttemptFailHard(
                    SetupError(
                        f"Step '{step.name}' failed: transport error after {attempt_ctx.max_retries + 1} attempts: {e}",
                        step_name=step.name,
                        cause=e,
                    )
                )
            )

        if not result.success:
            self._log_step_failure(step, result, attempt_ctx.attempt, attempt_ctx.max_retries, attempt_ctx.context)
            return _AttemptRetry(last_result=result)

        return self._classify_successful_attempt(
            attempt_ctx.instance_id,
            step,
            result,
            attempt_ctx.context,
            attempt_ctx.document_name,
            attempt_ctx.attempt,
            attempt_ctx.max_retries,
        )
