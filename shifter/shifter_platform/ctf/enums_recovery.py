"""Range-recovery enums (issue #1018 domain), split from ctf.enums (python:S104).

Import them from :mod:`ctf.enums` as before; this module keeps the recovery
vocabulary together without pushing the main enum module over the size gate.
"""

from __future__ import annotations

from enum import StrEnum


class RecoveryStrategy(StrEnum):
    """Replacement strategy for a destroyed-participant-range recovery (#1018).

    REBUILD: Provision a fresh same-event/same-scenario range via
        ``ctf.bridges.cms_create_range`` (mirrors normal provisioning).
    REASSIGN_SPARE: Reassign ownership of an existing, prewarmed,
        CTF-sourced spare range to the participant.
    """

    REBUILD = "rebuild"
    REASSIGN_SPARE = "reassign_spare"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(s.value, s.name.replace("_", " ").title()) for s in cls]


class RecoveryPhase(StrEnum):
    """Checkpointed progress of a range-recovery operation (#1018).

    Observability only: :mod:`ctf.services.range.recovery` resumes a retried
    recovery based on the presence/absence of recorded replacement/teardown
    state, not on this field, so a ``failed`` value never blocks re-entry.
    """

    INITIATED = "initiated"
    REPLACEMENT_READY = "replacement_ready"
    OLD_RANGE_BLOCKED = "old_range_blocked"
    PARTICIPANT_REPOINTED = "participant_repointed"
    COMPLETED = "completed"
    FAILED = "failed"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(p.value, p.name.replace("_", " ").title()) for p in cls]


class RecoveryFailureCategory(StrEnum):
    """Authored failure reason for a failed range-recovery operation (#1018).

    Bounded, operator-safe categories — never raw provider exceptions or
    traceback text (see ``shared.log_sanitize.safe_log_value`` at call sites).
    """

    VALIDATION_FAILED = "validation_failed"
    PROVISIONING_FAILED = "provisioning_failed"
    NO_COMPATIBLE_SPARE = "no_compatible_spare"
    OLD_RANGE_TEARDOWN_FAILED = "old_range_teardown_failed"
    INTERNAL_ERROR = "internal_error"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(f.value, f.name.replace("_", " ").title()) for f in cls]


class SpareRangeStatus(StrEnum):
    """Lifecycle status of a prewarmed event spare range (#1018).

    PROVISIONING: CMS provisioning has been dispatched but the range is not
        yet READY (tracked via the existing event range-status projection).
    READY: The underlying CMS ``RangeInstance`` is READY and available for
        assignment to a participant.
    FAILED: Provisioning failed, or the spare was torn down without being
        consumed (e.g. event cleanup); not offered as a candidate.
    CONSUMED: Ownership has been transferred to a participant during
        recovery; no longer part of the available pool.
    """

    PROVISIONING = "provisioning"
    READY = "ready"
    FAILED = "failed"
    CONSUMED = "consumed"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(s.value, s.name.title()) for s in cls]
