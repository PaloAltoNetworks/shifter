"""Shared types for the SetupOrchestrator package.

Holds the public result/error types (`SetupError`, `StepResult`,
`SetupResult`) and the internal per-attempt outcome / context types used by
`SetupOrchestrator`'s retry loop. Split out of `setup_orchestrator.py` to
keep that module under Sonar's file-length ceiling; the public surface is
re-exported from `setup_orchestrator` so existing call sites are unaffected.
"""

from dataclasses import dataclass, field
from typing import Any

from executors.base import CommandResult
from plans.base import SetupStep


class SetupError(Exception):
    """Raised when setup fails at any step."""

    def __init__(self, message: str, step_name: str | None = None, cause: Exception | None = None) -> None:
        """Store the step name and underlying cause for the failure summary."""
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
class _AttemptOutcomeBase:
    """Sealed base for the three `_execute_step` per-attempt outcomes."""


@dataclass(frozen=True)
class _AttemptSuccess(_AttemptOutcomeBase):
    """Attempt succeeded; the carried `CommandResult` flows back to the caller."""

    result: CommandResult


@dataclass(frozen=True)
class _AttemptRetry(_AttemptOutcomeBase):
    """Attempt should be retried (or, if retries exhausted, fall through to
    a failed StepResult). `last_result` carries the most recent CommandResult
    if one was produced (None for pre-execution transport errors)."""

    last_result: CommandResult | None


@dataclass(frozen=True)
class _AttemptFailHard(_AttemptOutcomeBase):
    """Attempt failure that must propagate as `SetupError` (no fallthrough)."""

    error: SetupError


_AttemptOutcome = _AttemptSuccess | _AttemptRetry | _AttemptFailHard


@dataclass(frozen=True)
class _StepAttemptContext:
    """Bundle of the eight parameters _run_one_attempt would otherwise take.

    Carries the per-attempt inputs that the retry loop passes through to the
    single-attempt executor, so the retry loop's call site stays readable and
    the executor function fits inside Sonar's S107 7-parameter ceiling.
    """

    instance_id: str
    step: SetupStep
    rendered_script: str
    rendered_stdin: str
    context: dict[str, Any]
    document_name: str
    attempt: int
    max_retries: int
