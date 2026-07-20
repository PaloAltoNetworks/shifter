"""Data model for the backend-aware ``doctor`` UX (#727): tiers, statuses, and results.

Split out of :mod:`installation.doctor` so the executor and the execution seams stay under
the per-file size limit; the public names are re-exported from ``installation.doctor``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: HTTP status range the health probe treats as healthy. Only 2xx is healthy; a 3xx means a
#: redirect the hardened opener refused to follow (SSRF guard), so it is reported, not passed.
HEALTHY_MIN, HEALTHY_MAX = 200, 299

#: The literal a bundle health-check target uses for the deployment's public hostname.
DOMAIN_PLACEHOLDER = "<deployment.domain>"


class CheckTier(StrEnum):
    """The side-effect tier of a check (preflight #727 classification)."""

    LOCAL = "local-only"
    CLOUD_READ = "cloud-read-only"
    MUTATING = "deployment-mutating"


class CheckStatus(StrEnum):
    """The outcome of a single doctor check."""

    # These are check-status labels, not credentials — silence the "pass" heuristics.
    PASS = "pass"  # noqa: S105 # nosec B105
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"
    INFO = "info"


class CheckScope(StrEnum):
    """Which tiers of check doctor runs for this invocation."""

    LOCAL = "local"
    CLOUD = "cloud"
    ALL = "all"


@dataclass(frozen=True)
class CommandOutcome:
    """The result of running one validation-check command (no captured output — sanitized)."""

    returncode: int | None
    timed_out: bool = False
    error: str | None = None


@dataclass(frozen=True)
class HealthOutcome:
    """The result of one read-only health probe."""

    status_code: int | None
    reachable: bool
    error: str | None = None


@dataclass(frozen=True)
class DoctorCheckResult:
    """One check's outcome, tier-labelled and sanitized."""

    name: str
    tier: CheckTier
    status: CheckStatus
    summary: str
    blocking: bool = False
    remediation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render the result as a JSON-serializable mapping for ``--json`` output."""
        return {
            "name": self.name,
            "tier": self.tier.value,
            "status": self.status.value,
            "summary": self.summary,
            "blocking": self.blocking,
            "remediation": self.remediation,
        }


@dataclass
class DoctorReport:
    """The full doctor run: the selected backend/profile and every check result."""

    backend: str | None
    profile: str | None
    results: list[DoctorCheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no *blocking* check failed. A non-blocking failure warns, it does not
        fail the run (every ``FAIL`` result is blocking by construction, so this also holds)."""
        return not any(result.status is CheckStatus.FAIL and result.blocking for result in self.results)

    def exit_code(self) -> int:
        """Process exit code: ``0`` when the report is ok, ``1`` when a blocking check failed."""
        return 0 if self.ok else 1

    def to_dict(self) -> dict[str, Any]:
        """Render the whole report as a JSON-serializable mapping for ``--json`` output."""
        return {
            "backend": self.backend,
            "profile": self.profile,
            "ok": self.ok,
            "results": [result.to_dict() for result in self.results],
        }
