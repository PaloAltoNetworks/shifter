"""Scenario-neutral range-escape validation report contract (issue #1347).

This is the closed, versioned, machine-readable security report emitted by the
GCP range-cell escape-validation suite. It proves, from participant-controlled
context inside a live range cell, that the outer boundary fails closed before the
range is trusted for live fire (ADR-030-R5, ADR-039-R6).

The module is deliberately dependency-light: it uses only the standard library
plus :mod:`shared.log_sanitize`, so the standalone provisioner image can import
:class:`BoundaryCode` for the static plan-leak checker without loading Django or
the platform schema graph, exactly like :mod:`shared.range_cells`.

Design notes:

- Each check names the exact leaked boundary via :class:`BoundaryCode` so a
  failure identifies which outer boundary leaked (issue #1347 acceptance
  criterion 4), and never collapses distinct boundaries into one result.
- The verdict is ``passed`` only when every required core boundary passes; the
  two-or-more-range gate additionally requires the peer-dependent boundaries to
  pass rather than skip.
- Diagnostics are bounded, single-line, and scrubbed of token-shaped substrings
  so a report can carry a destination label without leaking credentials.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from shared.log_sanitize import safe_log_value

CONTRACT = "shifter.gcp-range-escape"
VERSION = "1"

_MAX_DIAGNOSTIC_LEN = 200


class EscapeContractError(Exception):
    """Raised when a report or check is constructed from invalid data."""


class BoundaryCode(StrEnum):
    """The outer boundary a check probes. Each value is one distinct boundary."""

    CROSS_RANGE_PRIVATE_IP = "cross_range_private_ip"
    CROSS_RANGE_DNS = "cross_range_dns"
    PLATFORM_POD_CIDR = "platform_pod_cidr"
    PLATFORM_SERVICE_CIDR = "platform_service_cidr"
    PLATFORM_NODE_IP = "platform_node_ip"
    PLATFORM_PORTAL_PRIVATE = "platform_portal_private"
    GKE_GDC_API = "gke_gdc_api"
    METADATA_SERVER = "metadata_server"
    INTERNET_EGRESS = "internet_egress"
    MANAGEMENT_INGRESS = "management_ingress"
    PLATFORM_DNS = "platform_dns"
    SCENARIO_SERVICE = "scenario_service"
    # A positive control: a target that MUST be reachable from participant context.
    # If it is not, the probe environment is broken and every "unreachable" result
    # is untrustworthy, so the whole run fails closed rather than false-certifying.
    PROBE_CONTROL = "probe_control"


class CheckStatus(StrEnum):
    """Outcome of a single check."""

    PASS = "pass"  # nosec B105  # NOSONAR check-status literal, not a password
    FAIL = "fail"
    SKIP = "skip"
    NOT_APPLICABLE = "not_applicable"


class CheckScope(StrEnum):
    """Whether a check is part of the scenario-neutral core or scenario-supplied."""

    CORE = "core"
    SCENARIO = "scenario"


class Outcome(StrEnum):
    """Observed or expected network reachability for a probe."""

    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"


class DestinationClass(StrEnum):
    """The class of target a probe attempted to reach."""

    PEER_RANGE = "peer_range"
    PLATFORM_POD = "platform_pod"
    PLATFORM_SERVICE = "platform_service"
    PLATFORM_NODE = "platform_node"
    PORTAL_PRIVATE = "portal_private"
    GKE_GDC_API = "gke_gdc_api"
    METADATA = "metadata"
    INTERNET = "internet"
    MANAGEMENT = "management"
    PLATFORM_DNS = "platform_dns"
    CONTROL = "control"
    SCENARIO_SERVICE = "scenario_service"


class SuiteMode(StrEnum):
    """Whether the run validated a single range or two-or-more simultaneous ranges."""

    ONE_RANGE = "one_range"
    MULTI_RANGE = "multi_range"


class Verdict(StrEnum):
    """The overall gate result."""

    PASSED = "passed"
    FAILED = "failed"


#: Core boundaries that a single range's participant context can prove without a
#: peer range. All of these must pass for any verdict to be ``passed``.
REQUIRED_CORE_BOUNDARIES: frozenset[BoundaryCode] = frozenset(
    {
        BoundaryCode.PLATFORM_POD_CIDR,
        BoundaryCode.PLATFORM_SERVICE_CIDR,
        BoundaryCode.PLATFORM_NODE_IP,
        BoundaryCode.PLATFORM_PORTAL_PRIVATE,
        BoundaryCode.GKE_GDC_API,
        BoundaryCode.METADATA_SERVER,
        BoundaryCode.INTERNET_EGRESS,
    }
)

#: Boundaries that require a peer range as a negative target. They are optional
#: in a one-range run but mandatory (must pass, not skip) for the multi-range gate.
PEER_DEPENDENT_BOUNDARIES: frozenset[BoundaryCode] = frozenset(
    {
        BoundaryCode.CROSS_RANGE_PRIVATE_IP,
        BoundaryCode.CROSS_RANGE_DNS,
        BoundaryCode.MANAGEMENT_INGRESS,
    }
)

# Token-shaped substrings that must never reach a report, log, or CI annotation.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN[ A-Z]*-----"),
    re.compile(r"ya29\.[A-Za-z0-9._\-]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9._\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"[Bb]earer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),
    re.compile(r"[A-Fa-f0-9]{40,}"),
)
_REDACTION = "[redacted]"


def contains_secret_shape(text: str) -> bool:
    """Return True when ``text`` contains a token-shaped substring."""
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def sanitize_diagnostic(text: str, *, max_len: int = _MAX_DIAGNOSTIC_LEN) -> str:
    """Return a bounded, single-line diagnostic with secret-shaped substrings redacted.

    Redaction runs before whitespace collapse and truncation so a token can never
    be split across the length boundary and re-surface as a partial secret.
    """
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTION, redacted)
    collapsed = " ".join(redacted.split())
    bounded = safe_log_value(collapsed, max_len=max_len)
    return bounded


@dataclass(frozen=True)
class CheckResult:
    """One boundary check result in a range-escape report."""

    check_id: str
    boundary_code: BoundaryCode
    scope: CheckScope
    source_context: str
    destination_class: DestinationClass
    expected: Outcome
    observed: Outcome | None
    status: CheckStatus
    elapsed_ms: int
    diagnostic: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "boundary_code": self.boundary_code.value,
            "scope": self.scope.value,
            "source_context": self.source_context,
            "destination_class": self.destination_class.value,
            "expected": self.expected.value,
            "observed": self.observed.value if self.observed is not None else None,
            "status": self.status.value,
            "elapsed_ms": self.elapsed_ms,
            "diagnostic": self.diagnostic,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckResult:
        observed_raw = data.get("observed")
        return cls(
            check_id=_require_str(data, "check_id"),
            boundary_code=_parse_enum(BoundaryCode, data.get("boundary_code"), "boundary_code"),
            scope=_parse_enum(CheckScope, data.get("scope"), "scope"),
            source_context=_require_str(data, "source_context"),
            destination_class=_parse_enum(DestinationClass, data.get("destination_class"), "destination_class"),
            expected=_parse_enum(Outcome, data.get("expected"), "expected"),
            observed=None if observed_raw is None else _parse_enum(Outcome, observed_raw, "observed"),
            status=_parse_enum(CheckStatus, data.get("status"), "status"),
            elapsed_ms=int(data.get("elapsed_ms", 0)),
            diagnostic=str(data.get("diagnostic", "")),
        )


@dataclass
class EscapeReport:
    """A closed, versioned range-escape validation report."""

    suite_id: str
    mode: SuiteMode
    request_id: str
    range_id: int | None
    started_at: str
    ended_at: str
    checks: list[CheckResult]
    policy_inputs: dict[str, str] = field(default_factory=dict)
    peer_request_ids: list[str] = field(default_factory=list)
    peer_range_ids: list[int] = field(default_factory=list)
    contract: str = CONTRACT
    version: str = VERSION

    @property
    def verdict(self) -> Verdict:
        return compute_verdict(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "version": self.version,
            "suite_id": self.suite_id,
            "mode": self.mode.value,
            "request_id": self.request_id,
            "range_id": self.range_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "peer_request_ids": list(self.peer_request_ids),
            "peer_range_ids": list(self.peer_range_ids),
            "policy_inputs": dict(self.policy_inputs),
            "checks": [check.to_dict() for check in self.checks],
            "verdict": self.verdict.value,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EscapeReport:
        if not isinstance(data, dict):
            raise EscapeContractError("report must be an object")
        checks_raw = data.get("checks")
        if not isinstance(checks_raw, list):
            raise EscapeContractError("report.checks must be a list")
        return cls(
            suite_id=_require_str(data, "suite_id"),
            mode=_parse_enum(SuiteMode, data.get("mode"), "mode"),
            request_id=_require_str(data, "request_id"),
            range_id=data.get("range_id"),
            started_at=_require_str(data, "started_at"),
            ended_at=_require_str(data, "ended_at"),
            checks=[CheckResult.from_dict(_require_check_dict(item)) for item in checks_raw],
            policy_inputs=dict(data.get("policy_inputs") or {}),
            peer_request_ids=list(data.get("peer_request_ids") or []),
            peer_range_ids=list(data.get("peer_range_ids") or []),
            contract=str(data.get("contract", CONTRACT)),
            version=str(data.get("version", VERSION)),
        )

    @classmethod
    def from_json(cls, raw: str) -> EscapeReport:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EscapeContractError(f"report is not valid JSON: {exc}") from exc
        return cls.from_dict(data)


@dataclass(frozen=True)
class CheckContext:
    """The identity of a check (its id and the boundary/source/destination it probes)."""

    check_id: str
    boundary_code: BoundaryCode
    scope: CheckScope
    source_context: str
    destination_class: DestinationClass


def evaluate_check(
    context: CheckContext,
    *,
    expected: Outcome,
    observed: Outcome | None,
    elapsed_ms: int,
    status: CheckStatus | None = None,
    diagnostic: str = "",
) -> CheckResult:
    """Build a :class:`CheckResult`, deriving ``pass``/``fail`` from expected vs observed.

    When ``status`` is supplied it is used verbatim (the caller has already decided
    the check is a skip or not-applicable). Otherwise ``observed`` is mandatory and
    the status is ``pass`` when it matches ``expected`` and ``fail`` otherwise.
    """
    if status is None:
        if observed is None:
            raise EscapeContractError(f"check {context.check_id!r} has no observed outcome and no explicit status")
        resolved = CheckStatus.PASS if observed == expected else CheckStatus.FAIL
    else:
        resolved = status
    return CheckResult(
        check_id=context.check_id,
        boundary_code=context.boundary_code,
        scope=context.scope,
        source_context=context.source_context,
        destination_class=context.destination_class,
        expected=expected,
        observed=observed,
        status=resolved,
        elapsed_ms=elapsed_ms,
        diagnostic=sanitize_diagnostic(diagnostic) if diagnostic else "",
    )


def compute_verdict(report: EscapeReport) -> Verdict:
    """Return ``passed`` only when every required boundary passes for the run's mode.

    Any failed check fails the gate. A positive-control check must be present and
    passing, so a broken or tampered probe environment fails closed instead of
    reporting everything unreachable. Every required core boundary must be present
    and passing. In multi-range mode the peer-dependent boundaries must also pass
    (a skipped peer check fails the two-or-more-range gate); in one-range mode they
    may be skipped or not-applicable.
    """
    checks = report.checks
    has_fail = any(check.status == CheckStatus.FAIL for check in checks)
    controls = [c for c in checks if c.boundary_code == BoundaryCode.PROBE_CONTROL]
    control_ok = bool(controls) and all(c.status == CheckStatus.PASS for c in controls)
    passed_core = _passed_core_boundaries(checks)
    core_ok = passed_core >= REQUIRED_CORE_BOUNDARIES
    peer_ok = report.mode != SuiteMode.MULTI_RANGE or passed_core >= PEER_DEPENDENT_BOUNDARIES
    if has_fail or not control_ok or not core_ok or not peer_ok:
        return Verdict.FAILED
    return Verdict.PASSED


def _passed_core_boundaries(checks: Iterable[CheckResult]) -> set[BoundaryCode]:
    """Return the set of core boundary codes whose checks passed."""
    return {c.boundary_code for c in checks if c.scope == CheckScope.CORE and c.status == CheckStatus.PASS}


def _parse_enum[EnumT: StrEnum](enum_cls: type[EnumT], value: object, field_name: str) -> EnumT:
    """Parse ``value`` into a member of ``enum_cls`` or raise a contract error."""
    if not isinstance(value, str):
        raise EscapeContractError(f"{field_name} must be a string")
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise EscapeContractError(f"{field_name} has invalid value {value!r}") from exc


def _require_str(data: dict[str, Any], field_name: str) -> str:
    """Return a required non-empty string field or raise a contract error."""
    value = data.get(field_name)
    if not isinstance(value, str) or not value:
        raise EscapeContractError(f"{field_name} must be a non-empty string")
    return value


def _require_check_dict(value: object) -> dict[str, Any]:
    """Return ``value`` as a check object or raise a contract error."""
    if not isinstance(value, dict):
        raise EscapeContractError("each check must be an object")
    return value


__all__ = [
    "CONTRACT",
    "PEER_DEPENDENT_BOUNDARIES",
    "REQUIRED_CORE_BOUNDARIES",
    "VERSION",
    "BoundaryCode",
    "CheckContext",
    "CheckResult",
    "CheckScope",
    "CheckStatus",
    "DestinationClass",
    "EscapeContractError",
    "EscapeReport",
    "Outcome",
    "SuiteMode",
    "Verdict",
    "compute_verdict",
    "contains_secret_shape",
    "evaluate_check",
    "sanitize_diagnostic",
]
