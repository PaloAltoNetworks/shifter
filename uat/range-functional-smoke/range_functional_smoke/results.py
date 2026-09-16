"""Check vocabulary, per-check outcomes, and the fail-closed run verdict.

The design constraint this module exists to enforce (#983 §6.4, #987): the
distinct proofs must never collapse into one undifferentiated "smoke passed"
signal. Range readiness, the terminal nonce exchange, and each Guacamole
evidence level stay separate check codes with their own outcome, and the run
verdict is a pass only when *every required check* is present and passed.

Nothing here holds secret material: ``detail`` is an authored, bounded string
chosen by the caller, never a response body, URL, token, exception, or terminal
stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

_MAX_DETAIL = 200


class Status(StrEnum):
    """Outcome of a single check.

    Only ``PASSED`` is success. ``BLOCKED`` (a precondition was not met),
    ``SKIPPED``, ``TIMED_OUT``, and ``ERROR`` are all non-success — a missing or
    unrunnable required check is a failure, never a green skip.
    """

    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ERROR = "error"


class CheckCode(StrEnum):
    """Authored check codes.

    The four Guacamole codes are deliberately distinct evidence levels, in
    ascending strength. ``GUACAMOLE_BOOTSTRAP_SUCCEEDED`` means the server minted
    a credential; only ``GUACAMOLE_SESSION_CONNECTED`` means guacd actually
    opened the session to the target. Treating the former as "Guacamole works" is
    the exact gap this smoke closes relative to the TCP-only post-deploy smoke.
    """

    SESSION_ESTABLISHED = "session_established"
    RANGE_OWNED_READY = "range_owned_ready"
    # The range projection does not expose participant_access_channels — the
    # declared-channel binding is enforced server-side by
    # engine.services._require_declared_participant_channel, and a violation
    # surfaces as a bootstrap/terminal refusal. So this check claims only what is
    # observable: the portal's own projection offers the authored logical target.
    TARGET_SELECTED = "target_selected"
    TERMINAL_SOCKET_OPEN = "terminal_socket_open"
    TERMINAL_NONCE_EXCHANGE = "terminal_nonce_exchange"
    GUACAMOLE_BOOTSTRAP_ACCEPTED = "guacamole_bootstrap_accepted"
    GUACAMOLE_BOOTSTRAP_SUCCEEDED = "guacamole_bootstrap_succeeded"
    GUACAMOLE_URL_DELIVERED = "guacamole_url_delivered"
    GUACAMOLE_SESSION_CONNECTED = "guacamole_session_connected"


#: Every check that must be present and ``PASSED`` for the run to pass.
#: ``TERMINAL_SOCKET_OPEN`` and the two intermediate Guacamole codes are
#: required as *ordering* evidence, but they are not sufficient on their own —
#: the sufficiency comes from the two terminal-state codes being in this set.
REQUIRED_CHECKS: frozenset[CheckCode] = frozenset(
    {
        CheckCode.SESSION_ESTABLISHED,
        CheckCode.RANGE_OWNED_READY,
        CheckCode.TARGET_SELECTED,
        CheckCode.TERMINAL_SOCKET_OPEN,
        CheckCode.TERMINAL_NONCE_EXCHANGE,
        CheckCode.GUACAMOLE_BOOTSTRAP_ACCEPTED,
        CheckCode.GUACAMOLE_BOOTSTRAP_SUCCEEDED,
        CheckCode.GUACAMOLE_URL_DELIVERED,
        CheckCode.GUACAMOLE_SESSION_CONNECTED,
    }
)


def _bounded(detail: str) -> str:
    """Collapse a detail string to one bounded, single-line value."""
    cleaned = " ".join(str(detail).split())
    return cleaned[:_MAX_DETAIL]


@dataclass(frozen=True)
class CheckResult:
    """One check's outcome. ``detail`` is authored text, never captured output."""

    code: CheckCode
    status: Status
    detail: str = ""
    duration_ms: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail", _bounded(self.detail))

    @property
    def ok(self) -> bool:
        return self.status is Status.PASSED


@dataclass
class RunResults:
    """Accumulates check results and composes the fail-closed verdict."""

    checks: list[CheckResult] = field(default_factory=list)

    def record(self, code: CheckCode, status: Status, detail: str = "", duration_ms: int = 0) -> CheckResult:
        result = CheckResult(code=code, status=status, detail=detail, duration_ms=duration_ms)
        self.checks.append(result)
        return result

    def by_code(self) -> dict[CheckCode, CheckResult]:
        """Latest result per code (a retried check supersedes its earlier attempt)."""
        return {result.code: result for result in self.checks}

    def missing(self) -> set[CheckCode]:
        """Required checks that never ran. A check that never ran is not a pass."""
        return set(REQUIRED_CHECKS) - set(self.by_code())

    def failures(self) -> list[CheckResult]:
        """Required checks that ran but did not pass."""
        latest = self.by_code()
        return [latest[code] for code in REQUIRED_CHECKS if code in latest and not latest[code].ok]

    @property
    def passed(self) -> bool:
        """True only when every required check is present and passed."""
        return not self.missing() and not self.failures()

    def verdict(self) -> str:
        return "pass" if self.passed else "fail"
