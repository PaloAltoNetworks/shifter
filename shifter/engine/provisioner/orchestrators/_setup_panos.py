"""PAN-OS-specific helpers for SetupOrchestrator.

Provides `_SetupOrchestratorPanOSMixin`, mixed into `SetupOrchestrator`,
carrying the commit-classification, commit-success detection, job-id
parsing, job polling, and poll-result handling that only apply to steps
running against a PAN-OS NGFW. Split out of `setup_orchestrator.py` to
keep that module under Sonar's file-length ceiling.
"""

import logging
import re
import time
from typing import TYPE_CHECKING, Any

from executors.base import (
    CommandResult,
    ExecutorConnectionError,
    ExecutorTimeoutError,
)
from orchestrators._setup_types import (
    SetupError,
    _AttemptFailHard,
    _AttemptOutcome,
    _AttemptRetry,
    _AttemptSuccess,
)
from plans.base import SetupStep

if TYPE_CHECKING:
    # Mixin contract: composing class provides ``executor`` and the
    # ``_mask_sensitive_output`` method (from _SetupOrchestratorLoggingMixin).
    from executors.base import Executor

# Log under the public module name (`orchestrators.setup_orchestrator`) even
# though this code lives in a split-out helper module. Tests pin caplog /
# callers pin log handlers to that logger name; keeping a single logger name
# across the package preserves that contract and keeps log output on one
# stable channel.
logger = logging.getLogger("orchestrators.setup_orchestrator")


class _SetupOrchestratorPanOSMixin:
    """PAN-OS commit / job-poll helpers used by `_classify_successful_attempt`.

    Mixed into `SetupOrchestrator`. Relies on `self.executor` (set up by the
    main class) for the poll loop's `run_command` calls; no other instance
    state is touched.
    """

    if TYPE_CHECKING:
        executor: "Executor"

        @classmethod
        def _mask_sensitive_output(cls, output: str, context: dict[str, Any] | None = None) -> str: ...

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
            return (
                _AttemptRetry(last_result=result)
                if attempt < max_retries
                else _AttemptFailHard(
                    SetupError(
                        f"Step '{step.name}' failed: PAN-OS commit failed after {max_retries + 1} attempts",
                        step_name=step.name,
                    )
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
            return (
                _AttemptRetry(last_result=result)
                if attempt < max_retries
                else _AttemptFailHard(
                    SetupError(
                        f"Step '{step.name}' failed: PAN-OS job {job_id} did not complete successfully",
                        step_name=step.name,
                    )
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

    @staticmethod
    def _check_commit_success(output: str) -> bool:
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
        # Empty output, or output without a "commit" mention, means no commit was
        # attempted; treat that as success (idempotent no-op). The two literal
        # status strings cover the operative success cases.
        commit_success_markers = (
            "Configuration committed successfully",
            "There are no changes to commit",
        )
        no_commit_attempted = not output or "commit" not in output.lower()
        if no_commit_attempted or any(marker in output for marker in commit_success_markers):
            success = True
        else:
            # If we polled a commit job, the stdout may include job status output
            # with "FIN OK" tokens — accept either-order presence as success.
            output_lower = output.lower()
            success = ("fin" in output_lower) and ("ok" in output_lower)
        return success

    @staticmethod
    def _parse_panos_job_id(output: str) -> str | None:
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
