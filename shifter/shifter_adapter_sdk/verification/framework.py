"""Deterministic orchestration for validated scenario-verification plugins."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from .contracts import (
    API_VERSION,
    REPORT_SCHEMA_VERSION,
    AdapterContext,
    AdapterDeclaration,
    AdapterOutcome,
    AdapterStatus,
    CheckReason,
    CheckStatus,
    RunnerExecutionError,
    VerificationCancelled,
    VerificationDeadlineExceeded,
    _validate_identifier,
    _validate_version,
)
from .discovery import LoadedPlugin, PluginDiscoveryError, _validate_installed_metadata


class VerificationConfigurationError(ValueError):
    """The selected plugin or adapter set is unsafe to execute."""


@dataclass(frozen=True)
class CheckResult:
    """Redacted result for one selected adapter."""

    adapter_id: str
    status: CheckStatus
    reason: CheckReason
    duration_ms: int

    def __post_init__(self) -> None:
        _validate_identifier(self.adapter_id, "adapter_id", namespaced=True)
        if not isinstance(self.status, CheckStatus):
            raise TypeError("status must be CheckStatus")
        if not isinstance(self.reason, CheckReason):
            raise TypeError("reason must be CheckReason")
        valid_reasons = {
            CheckStatus.PASS: {CheckReason.VERIFIED},
            CheckStatus.FAIL: {CheckReason.MISMATCH},
            CheckStatus.BLOCKED: {CheckReason.PREREQUISITE_UNSATISFIED},
            CheckStatus.ERROR: {
                CheckReason.PREREQUISITE_ERROR,
                CheckReason.ADAPTER_ERROR,
                CheckReason.RUNNER_ERROR,
                CheckReason.TIMEOUT,
                CheckReason.CANCELLED,
                CheckReason.DEADLINE_EXCEEDED,
                CheckReason.INVALID_RESULT,
            },
        }
        if self.reason not in valid_reasons[self.status]:
            raise ValueError("check status and reason disagree")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int):
            raise TypeError("duration_ms must be an integer")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")


@dataclass(frozen=True)
class VerificationReport:
    """One immutable redacted aggregate report DTO."""

    schema_version: str
    distribution: str
    distribution_version: str
    entry_point: str
    plugin_id: str
    plugin_version: str
    checks: tuple[CheckResult, ...]
    duration_ms: int

    def __post_init__(self) -> None:
        if self.schema_version != REPORT_SCHEMA_VERSION:
            raise ValueError("unsupported report schema version")
        try:
            _validate_installed_metadata(self.distribution, self.distribution_version, self.entry_point)
        except PluginDiscoveryError as exc:
            raise ValueError(str(exc)) from None
        _validate_identifier(self.plugin_id, "plugin_id", namespaced=True)
        _validate_version(self.plugin_version, "plugin_version")
        if not isinstance(self.checks, tuple) or not self.checks:
            raise ValueError("report checks must be a non-empty tuple")
        if not all(isinstance(check, CheckResult) for check in self.checks):
            raise TypeError("checks must contain CheckResult values")
        check_ids = [check.adapter_id for check in self.checks]
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("report check identities must be unique")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int):
            raise TypeError("duration_ms must be an integer")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")

    @property
    def counts(self) -> dict[str, int]:
        """Return deterministic counts for every closed status."""
        counted = Counter(check.status.value for check in self.checks)
        return {
            CheckStatus.PASS.value: counted[CheckStatus.PASS.value],
            CheckStatus.FAIL.value: counted[CheckStatus.FAIL.value],
            CheckStatus.BLOCKED.value: counted[CheckStatus.BLOCKED.value],
            CheckStatus.ERROR.value: counted[CheckStatus.ERROR.value],
            "total": len(self.checks),
        }


def _validate_and_select(
    plugin: LoadedPlugin, selected_adapter_ids: tuple[str, ...] | None
) -> tuple[dict[str, AdapterDeclaration], set[str]]:
    """Validate a plugin and return its adapter index and selected closure."""
    adapter_by_id = _validated_adapter_index(plugin)
    return adapter_by_id, _validated_selection(adapter_by_id, selected_adapter_ids)


def _validated_adapter_index(plugin: LoadedPlugin) -> dict[str, AdapterDeclaration]:
    """Return a validated adapter index for one loaded plugin."""
    if not isinstance(plugin, LoadedPlugin):
        raise TypeError("plugin must be a LoadedPlugin returned by discovery")
    if plugin.declaration.api_version != API_VERSION:
        raise VerificationConfigurationError("unsupported plugin API version")
    adapters = plugin.adapters
    if not adapters:
        raise VerificationConfigurationError("plugin contains no adapters")
    adapter_by_id = {adapter.adapter_id: adapter for adapter in adapters}
    if len(adapter_by_id) != len(adapters):
        raise VerificationConfigurationError("plugin contains duplicate adapter identities")

    declared = set(adapter_by_id)
    for adapter in adapters:
        if set(adapter.prerequisites) - declared:
            raise VerificationConfigurationError("adapter contains an unknown prerequisite")
    return adapter_by_id


def _validated_selection(
    adapter_by_id: dict[str, AdapterDeclaration], selected_adapter_ids: tuple[str, ...] | None
) -> set[str]:
    """Return a non-empty selected adapter set with prerequisite closure."""
    declared = set(adapter_by_id)
    if selected_adapter_ids is None:
        return declared
    if not isinstance(selected_adapter_ids, tuple):
        raise TypeError("selected_adapter_ids must be a tuple or None")
    if not selected_adapter_ids:
        raise VerificationConfigurationError("selected adapter set must be non-empty")
    if len(set(selected_adapter_ids)) != len(selected_adapter_ids):
        raise VerificationConfigurationError("selected adapter set contains duplicates")
    selected = set(selected_adapter_ids)
    if selected - declared:
        raise VerificationConfigurationError("selected adapter set contains unknown adapters")
    for adapter_id in selected:
        if not set(adapter_by_id[adapter_id].prerequisites).issubset(selected):
            raise VerificationConfigurationError("selected adapter set must include prerequisite closure")
    return selected


def _topological_order(adapter_by_id: dict[str, AdapterDeclaration], selected: set[str]) -> tuple[str, ...]:
    """Return a deterministic topological order for selected adapters."""
    pending = {adapter_id: set(adapter_by_id[adapter_id].prerequisites) for adapter_id in selected}
    ordered: list[str] = []
    while pending:
        ready = sorted(adapter_id for adapter_id, prerequisites in pending.items() if not prerequisites)
        if not ready:
            raise VerificationConfigurationError("adapter prerequisite cycle detected")
        ordered.extend(ready)
        ready_set = set(ready)
        pending = {
            adapter_id: prerequisites - ready_set
            for adapter_id, prerequisites in pending.items()
            if adapter_id not in ready_set
        }
    return tuple(ordered)


def _duration_ms(started: float, finished: float) -> int:
    """Return a non-negative elapsed duration in whole milliseconds."""
    return max(0, int((finished - started) * 1000))


def _contained_result(
    *,
    adapter_id: str,
    status: CheckStatus,
    reason: CheckReason,
    started: float,
    monotonic: Callable[[], float],
) -> CheckResult:
    """Build one redacted check result with measured duration."""
    return CheckResult(adapter_id, status, reason, _duration_ms(started, monotonic()))


def _prerequisite_short_circuit(
    adapter: AdapterDeclaration,
    results_by_id: dict[str, CheckResult],
    *,
    started: float,
    monotonic: Callable[[], float],
) -> CheckResult | None:
    """Return a closed result when a prerequisite prevents execution."""
    prerequisite_results = [results_by_id[prerequisite] for prerequisite in adapter.prerequisites]
    if any(result.status is CheckStatus.ERROR for result in prerequisite_results):
        return _contained_result(
            adapter_id=adapter.adapter_id,
            status=CheckStatus.ERROR,
            reason=CheckReason.PREREQUISITE_ERROR,
            started=started,
            monotonic=monotonic,
        )
    if any(result.status is not CheckStatus.PASS for result in prerequisite_results):
        return _contained_result(
            adapter_id=adapter.adapter_id,
            status=CheckStatus.BLOCKED,
            reason=CheckReason.PREREQUISITE_UNSATISFIED,
            started=started,
            monotonic=monotonic,
        )
    return None


def _budget_short_circuit(
    adapter_id: str,
    context: AdapterContext,
    *,
    started: float,
    monotonic: Callable[[], float],
) -> CheckResult | None:
    """Return a closed result when cancellation or the run budget prevents work."""
    reason = None
    if context.cancellation.cancelled:
        reason = CheckReason.CANCELLED
    elif context.remaining_seconds <= 0:
        reason = CheckReason.DEADLINE_EXCEEDED
    if reason is None:
        return None
    return _contained_result(
        adapter_id=adapter_id,
        status=CheckStatus.ERROR,
        reason=reason,
        started=started,
        monotonic=monotonic,
    )


def _execute_adapter(
    adapter: AdapterDeclaration,
    context: AdapterContext,
    *,
    started: float,
    monotonic: Callable[[], float],
) -> CheckResult:
    """Execute one adapter and contain every outcome in the closed result model."""
    try:
        outcome = adapter.execute(context)
    except VerificationCancelled:
        status, reason = CheckStatus.ERROR, CheckReason.CANCELLED
    except VerificationDeadlineExceeded:
        status, reason = CheckStatus.ERROR, CheckReason.DEADLINE_EXCEEDED
    except TimeoutError:
        status, reason = CheckStatus.ERROR, CheckReason.TIMEOUT
    except RunnerExecutionError:
        status, reason = CheckStatus.ERROR, CheckReason.RUNNER_ERROR
    except Exception:
        status, reason = CheckStatus.ERROR, CheckReason.ADAPTER_ERROR
    else:
        if not isinstance(outcome, AdapterOutcome):
            status, reason = CheckStatus.ERROR, CheckReason.INVALID_RESULT
        elif context.cancellation.cancelled:
            status, reason = CheckStatus.ERROR, CheckReason.CANCELLED
        elif context.remaining_seconds <= 0:
            status, reason = CheckStatus.ERROR, CheckReason.DEADLINE_EXCEEDED
        elif outcome.status is AdapterStatus.PASS:
            status, reason = CheckStatus.PASS, outcome.reason
        else:
            status, reason = CheckStatus.FAIL, outcome.reason
    return _contained_result(
        adapter_id=adapter.adapter_id,
        status=status,
        reason=reason,
        started=started,
        monotonic=monotonic,
    )


def run_verification(
    plugin: LoadedPlugin,
    context: AdapterContext,
    *,
    selected_adapter_ids: tuple[str, ...] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> VerificationReport:
    """Execute a validated non-empty adapter set with closed failure semantics."""
    if not isinstance(context, AdapterContext):
        raise TypeError("context must be AdapterContext")
    if not callable(monotonic):
        raise TypeError("monotonic must be callable")
    adapter_by_id, selected = _validate_and_select(plugin, selected_adapter_ids)
    ordered = _topological_order(adapter_by_id, selected)
    run_started = monotonic()
    results_by_id: dict[str, CheckResult] = {}

    for adapter_id in ordered:
        adapter = adapter_by_id[adapter_id]
        started = monotonic()
        short_circuit = _prerequisite_short_circuit(
            adapter, results_by_id, started=started, monotonic=monotonic
        ) or _budget_short_circuit(adapter_id, context, started=started, monotonic=monotonic)
        if short_circuit is not None:
            results_by_id[adapter_id] = short_circuit
            continue
        results_by_id[adapter_id] = _execute_adapter(
            adapter,
            context,
            started=started,
            monotonic=monotonic,
        )

    checks = tuple(results_by_id[adapter_id] for adapter_id in ordered)
    return VerificationReport(
        schema_version=REPORT_SCHEMA_VERSION,
        distribution=plugin.distribution,
        distribution_version=plugin.distribution_version,
        entry_point=plugin.entry_point,
        plugin_id=plugin.plugin_id,
        plugin_version=plugin.plugin_version,
        checks=checks,
        duration_ms=_duration_ms(run_started, monotonic()),
    )


def aggregate_exit_code(report: VerificationReport) -> int:
    """Return zero only when every selected check passed."""
    if not isinstance(report, VerificationReport):
        raise TypeError("report must be VerificationReport")
    return 0 if all(check.status is CheckStatus.PASS for check in report.checks) else 1


__all__ = [
    "CheckResult",
    "VerificationConfigurationError",
    "VerificationReport",
    "aggregate_exit_code",
    "run_verification",
]
