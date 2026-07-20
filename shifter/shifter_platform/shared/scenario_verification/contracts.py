"""Versioned, provider-neutral contracts for scenario verification plugins.

The public ABI in this module deliberately carries no Django settings, cloud
clients, provider topology, ACES runtime objects, or persistence handles.  An
installed plugin receives only opaque bindings and a bounded command runner.
"""

from __future__ import annotations

import hmac
import math
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from shared.log_sanitize import safe_log_value

ENTRY_POINT_GROUP = "shifter.scenario_verification.adapters"
API_VERSION = "1"
REPORT_SCHEMA_VERSION = "1"

MAX_IDENTIFIER_LENGTH = 64
MAX_SUMMARY_LENGTH = 200
MAX_OUTPUT_BYTES = 65_536
MAX_STDIN_BYTES = 65_536
MAX_ARGV_ITEMS = 128
MAX_ARG_BYTES = 4_096
MAX_COMMAND_TIMEOUT_SECONDS = 300.0
MAX_TARGET_ID_BYTES = 256
_SUCCESS_STATUS_VALUE = "pass"

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,63}$")


def _validate_identifier(value: object, field_name: str, *, namespaced: bool = False) -> str:
    """Return a validated bounded identifier, optionally requiring a namespace."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or len(value) > MAX_IDENTIFIER_LENGTH or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded lowercase identifier")
    if namespaced and "." not in value:
        raise ValueError(f"{field_name} must be namespaced")
    return value


def _validate_version(value: object, field_name: str) -> str:
    """Return a validated bounded version string."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not _VERSION_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded version")
    return value


def _validate_summary(value: object) -> str:
    """Return a validated, log-safe adapter summary."""
    if not isinstance(value, str):
        raise TypeError("summary must be a string")
    if not value or len(value) > MAX_SUMMARY_LENGTH:
        raise ValueError("summary must be non-empty and at most 200 characters")
    if safe_log_value(value, max_len=MAX_SUMMARY_LENGTH) != value:
        raise ValueError("summary contains unsafe control or escape characters")
    return value


def _validate_target_id(value: object) -> str:
    """Return a validated opaque target identifier."""
    if not isinstance(value, str):
        raise TypeError("target_id must be a string")
    if not value or len(value.encode("utf-8")) > MAX_TARGET_ID_BYTES:
        raise ValueError("target_id must be non-empty and bounded")
    if safe_log_value(value, max_len=MAX_TARGET_ID_BYTES) != value:
        raise ValueError("target_id contains unsafe control or escape characters")
    return value


def _validated_command(argv: Sequence[str]) -> tuple[str, ...]:
    """Return a bounded immutable argv sequence after validating each item."""
    if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence):
        raise TypeError("argv must be a sequence of strings, not a shell string")
    command = tuple(argv)
    if not command or len(command) > MAX_ARGV_ITEMS:
        raise ValueError("argv must contain a bounded number of arguments")
    for argument in command:
        if not isinstance(argument, str):
            raise TypeError("argv must contain only strings")
        if not argument or len(argument.encode("utf-8")) > MAX_ARG_BYTES or "\x00" in argument:
            raise ValueError("argv contains an empty or oversized argument")
    return command


def _validate_stdin(stdin: str | None) -> None:
    """Validate optional standard input against the bounded command contract."""
    if stdin is None:
        return
    if not isinstance(stdin, str):
        raise TypeError("stdin must be a string or None")
    if len(stdin.encode("utf-8")) > MAX_STDIN_BYTES:
        raise ValueError("stdin exceeds the bounded input contract")


def _validated_timeout(timeout_seconds: float) -> float:
    """Return a finite positive command timeout within the configured maximum."""
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
        raise TypeError("timeout_seconds must be numeric")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or timeout_seconds > MAX_COMMAND_TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds is outside the command budget")
    return float(timeout_seconds)


class AdapterStatus(StrEnum):
    """The only outcomes an adapter may return directly."""

    PASS = _SUCCESS_STATUS_VALUE
    FAIL = "fail"


class CheckStatus(StrEnum):
    """Closed per-check statuses produced by the framework."""

    PASS = _SUCCESS_STATUS_VALUE
    FAIL = "fail"
    BLOCKED = "blocked"
    ERROR = "error"


class CheckReason(StrEnum):
    """Bounded reason vocabulary safe to expose in reports."""

    VERIFIED = "verified"
    MISMATCH = "mismatch"
    PREREQUISITE_UNSATISFIED = "prerequisite_unsatisfied"
    PREREQUISITE_ERROR = "prerequisite_error"
    ADAPTER_ERROR = "adapter_error"
    RUNNER_ERROR = "runner_error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    INVALID_RESULT = "invalid_result"


@dataclass(frozen=True)
class ExecResult:
    """Bounded transport result available to plugin code, never to reports."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int

    def __post_init__(self) -> None:
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
            raise TypeError("exit_code must be an integer")
        if not isinstance(self.stdout, str) or len(self.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise ValueError("stdout exceeds the bounded output contract")
        if not isinstance(self.stderr, str) or len(self.stderr.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise ValueError("stderr exceeds the bounded output contract")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int):
            raise TypeError("duration_ms must be an integer")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")


@runtime_checkable
class Runner(Protocol):
    """Injected, transport-neutral bounded command execution port."""

    def run(
        self,
        target_id: str,
        argv: tuple[str, ...],
        *,
        stdin: str | None = None,
        timeout_seconds: float,
    ) -> ExecResult:
        """Execute one argv-only command against an opaque target."""
        ...


@runtime_checkable
class CancellationToken(Protocol):
    """Minimal cancellation signal shared by the whole verification run."""

    @property
    def cancelled(self) -> bool:
        """Whether the caller has cancelled the run."""
        ...


class VerificationCancelled(RuntimeError):
    """Raised at the runner boundary when cancellation is requested."""


class VerificationDeadlineExceeded(TimeoutError):
    """Raised at the runner boundary when the whole-run budget is exhausted."""


class RunnerExecutionError(RuntimeError):
    """Redaction-safe wrapper for an injected runner fault."""


@dataclass(frozen=True)
class Binding:
    """A namespaced logical binding to an opaque runner target id."""

    name: str
    target_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.name, "binding name", namespaced=True)
        _validate_target_id(self.target_id)


@dataclass(frozen=True)
class AdapterOutcome:
    """A plugin's deliberately narrow no-evidence verdict."""

    status: AdapterStatus
    reason: CheckReason

    def __post_init__(self) -> None:
        if not isinstance(self.status, AdapterStatus):
            raise TypeError("status must be AdapterStatus")
        if not isinstance(self.reason, CheckReason):
            raise TypeError("reason must be CheckReason")
        valid = {
            AdapterStatus.PASS: {CheckReason.VERIFIED},
            AdapterStatus.FAIL: {CheckReason.MISMATCH},
        }
        if self.reason not in valid[self.status]:
            raise ValueError("adapter outcome status and reason disagree")


AdapterCallable = Callable[["AdapterContext"], AdapterOutcome]


@dataclass(frozen=True)
class AdapterDeclaration:
    """One synthetic or out-of-tree verification adapter declaration."""

    adapter_id: str
    summary: str
    execute: AdapterCallable
    prerequisites: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identifier(self.adapter_id, "adapter_id", namespaced=True)
        _validate_summary(self.summary)
        if not callable(self.execute):
            raise TypeError("execute must be callable")
        if not isinstance(self.prerequisites, tuple):
            raise TypeError("prerequisites must be a tuple")
        for prerequisite in self.prerequisites:
            _validate_identifier(prerequisite, "prerequisite", namespaced=True)
        if len(set(self.prerequisites)) != len(self.prerequisites):
            raise ValueError("prerequisites must be unique")
        if self.adapter_id in self.prerequisites:
            raise ValueError("adapter cannot depend on itself")


@dataclass(frozen=True)
class PluginDeclaration:
    """Factory-produced declaration loaded from the fixed entry-point group."""

    api_version: str
    plugin_id: str
    plugin_version: str
    adapters: tuple[AdapterDeclaration, ...]

    def __post_init__(self) -> None:
        _validate_version(self.api_version, "api_version")
        _validate_identifier(self.plugin_id, "plugin_id", namespaced=True)
        _validate_version(self.plugin_version, "plugin_version")
        if not isinstance(self.adapters, tuple):
            raise TypeError("adapters must be a tuple")
        if not all(isinstance(adapter, AdapterDeclaration) for adapter in self.adapters):
            raise TypeError("adapters must contain AdapterDeclaration values")


@dataclass(frozen=True)
class AdapterContext:
    """The complete capability surface exposed to a selected adapter."""

    runner: Runner
    bindings: tuple[Binding, ...]
    deadline: float
    cancellation: CancellationToken
    monotonic: Callable[[], float] = field(default=time.monotonic, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.runner, Runner):
            raise TypeError("runner must implement Runner")
        if not isinstance(self.bindings, tuple) or not all(isinstance(binding, Binding) for binding in self.bindings):
            raise TypeError("bindings must be a tuple of Binding values")
        names = [binding.name for binding in self.bindings]
        if len(set(names)) != len(names):
            raise ValueError("binding names must be unique")
        if not isinstance(self.deadline, (int, float)) or isinstance(self.deadline, bool):
            raise TypeError("deadline must be a monotonic timestamp")
        if not math.isfinite(self.deadline):
            raise ValueError("deadline must be finite")
        if not isinstance(self.cancellation, CancellationToken):
            raise TypeError("cancellation must implement CancellationToken")
        if not callable(self.monotonic):
            raise TypeError("monotonic must be callable")

    @property
    def remaining_seconds(self) -> float:
        """Return the non-negative whole-run time budget."""
        return max(0.0, float(self.deadline) - float(self.monotonic()))

    def run(
        self,
        binding_name: str,
        argv: Sequence[str],
        *,
        stdin: str | None = None,
        timeout_seconds: float,
    ) -> ExecResult:
        """Validate and execute one command within command and run budgets."""
        if self.cancellation.cancelled:
            raise VerificationCancelled("verification cancelled")
        remaining = self.remaining_seconds
        if remaining <= 0:
            raise VerificationDeadlineExceeded("verification deadline exceeded")
        command = _validated_command(argv)
        _validate_stdin(stdin)
        command_timeout = _validated_timeout(timeout_seconds)
        targets = {binding.name: binding.target_id for binding in self.bindings}
        try:
            target_id = targets[binding_name]
        except KeyError as exc:
            raise ValueError("binding is not declared") from exc
        effective_timeout = min(command_timeout, remaining)
        try:
            result = self.runner.run(
                target_id,
                command,
                stdin=stdin,
                timeout_seconds=effective_timeout,
            )
        except (TimeoutError, VerificationCancelled):
            raise
        except Exception as exc:
            raise RunnerExecutionError("runner execution failed") from exc
        if not isinstance(result, ExecResult):
            raise RunnerExecutionError("runner returned an invalid result")
        return result


def equal_without_disclosure(produced: str | bytes, expected: str | bytes) -> bool:
    """Return only a constant-time equality verdict; never an answer fingerprint."""
    if isinstance(produced, str) and isinstance(expected, str):
        return hmac.compare_digest(produced.encode("utf-8"), expected.encode("utf-8"))
    if isinstance(produced, bytes) and isinstance(expected, bytes):
        return hmac.compare_digest(produced, expected)
    return False


__all__ = [
    "API_VERSION",
    "ENTRY_POINT_GROUP",
    "MAX_OUTPUT_BYTES",
    "REPORT_SCHEMA_VERSION",
    "AdapterCallable",
    "AdapterContext",
    "AdapterDeclaration",
    "AdapterOutcome",
    "AdapterStatus",
    "Binding",
    "CancellationToken",
    "CheckReason",
    "CheckStatus",
    "ExecResult",
    "PluginDeclaration",
    "Runner",
    "RunnerExecutionError",
    "VerificationCancelled",
    "VerificationDeadlineExceeded",
    "equal_without_disclosure",
]
