"""CTF-specific enums and constants.

Defines status values, categories, and other constants for CTF operations.
"""

from __future__ import annotations

from enum import StrEnum


class EventStatus(StrEnum):
    """CTF event lifecycle status.

    Events progress through these states:
        draft -> registration -> active -> ended -> archived
                     |            |  ^       |
                     |            v  |       |
                     |          paused       |
                     |            |          |
                     v            v          v
                          cancelled

    Valid transitions are defined in VALID_TRANSITIONS below.
    """

    DRAFT = "draft"
    REGISTRATION = "registration"
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class ParticipantStatus(StrEnum):
    """CTF participant lifecycle status.

    Participants progress through these states:
        invited -> registered -> active -> completed
                       |
                       v
                 disqualified
    """

    INVITED = "invited"
    REGISTERED = "registered"
    ACTIVE = "active"
    COMPLETED = "completed"
    DISQUALIFIED = "disqualified"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class ChallengeDifficulty(StrEnum):
    """Challenge difficulty levels."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(diff.value, diff.name.title()) for diff in cls]


class ChallengeVisibility(StrEnum):
    """Challenge visibility states.

    Controls whether a challenge is shown to participants and whether
    submissions are accepted.
    """

    VISIBLE = "visible"  # Shown to participants, submittable
    HIDDEN = "hidden"  # Not shown, not submittable (organizer-only)
    LOCKED = "locked"  # Shown but not submittable

    def __str__(self) -> str:
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(v.value, v.name.title()) for v in cls]


class ChallengeCategory(StrEnum):
    """Fixed challenge categories.

    Standard CTF challenge categories as used in major CTF competitions.
    """

    WEB = "web"
    FORENSICS = "forensics"
    CRYPTO = "crypto"
    REVERSE = "reverse"
    PWN = "pwn"
    MISC = "misc"
    OSINT = "osint"
    HARDWARE = "hardware"
    NETWORK = "network"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        labels = {
            "web": "Web Exploitation",
            "forensics": "Forensics",
            "crypto": "Cryptography",
            "reverse": "Reverse Engineering",
            "pwn": "Binary Exploitation",
            "misc": "Miscellaneous",
            "osint": "OSINT",
            "hardware": "Hardware",
            "network": "Network",
        }
        return [(cat.value, labels.get(cat.value, cat.name.title())) for cat in cls]


class NotificationType(StrEnum):
    """Types of CTF notifications."""

    INVITE = "invite"
    CREDENTIALS = "credentials"
    REMINDER = "reminder"
    ANNOUNCEMENT = "announcement"
    EVENT_START = "event_start"
    EVENT_END = "event_end"
    PROVISION_FAILURE = "provision_failure"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(t.value, t.name.replace("_", " ").title()) for t in cls]


class NotificationStatus(StrEnum):
    """Status of a notification."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(s.value, s.name.title()) for s in cls]


class ScheduledTaskType(StrEnum):
    """Types of scheduled tasks."""

    SPIN_UP_RANGES = "spin_up_ranges"
    CLEANUP_RANGES = "cleanup_ranges"
    SEND_REMINDER = "send_reminder"
    EVENT_START = "event_start"
    EVENT_END = "event_end"
    RELEASE_CHALLENGE = "release_challenge"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(t.value, t.name.replace("_", " ").title()) for t in cls]


class ScheduledTaskStatus(StrEnum):
    """Status of a scheduled task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(s.value, s.name.title()) for s in cls]


class AttemptLimitMode(StrEnum):
    """Behavior when a participant reaches the max submission attempts for a challenge.

    LOCKOUT: Permanently locked out of that challenge.
    TIMEOUT: Locked out for a configurable cooldown period, then attempts reset.
    """

    LOCKOUT = "lockout"
    TIMEOUT = "timeout"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(m.value, m.name.title()) for m in cls]


class ScoringMode(StrEnum):
    """Scoring strategy an event uses to award points for a correct solve.

    STANDARD: fixed per-challenge point value (CTF-201). A correct flag awards
    the challenge's full point value (less any cumulative hint penalty); points
    do not change with the number of solves. This is the default and, today, the
    only supported mode. The enum exists so future modes (e.g. dynamic) slot in
    as one additional value plus one scoring-service strategy (CTF-002).
    """

    STANDARD = "standard"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(m.value, m.name.title()) for m in cls]


class RatingVisibility(StrEnum):
    """Controls whether challenge ratings are visible to participants.

    PUBLIC: All participants can see average ratings.
    ORGANIZER: Only organizers can see ratings.
    DISABLED: Ratings are disabled for this event.
    """

    PUBLIC = "public"
    ORGANIZER = "organizer"
    DISABLED = "disabled"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(v.value, v.name.title()) for v in cls]


class UserType(StrEnum):
    """User types for the platform."""

    STANDARD = "standard"
    CTF_ORGANIZER = "ctf_organizer"
    CTF_PARTICIPANT = "ctf_participant"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        labels = {
            "standard": "Standard User",
            "ctf_organizer": "CTF Organizer",
            "ctf_participant": "CTF Participant",
        }
        return [(t.value, labels.get(t.value, t.name)) for t in cls]


# Terminal statuses — no further transitions possible
EVENT_TERMINAL_STATUSES = frozenset({EventStatus.ENDED, EventStatus.CANCELLED, EventStatus.ARCHIVED})

PARTICIPANT_TERMINAL_STATUSES = frozenset({ParticipantStatus.COMPLETED, ParticipantStatus.DISQUALIFIED})

# Statuses that allow content modifications (challenges, files, etc.)
EVENT_MODIFIABLE_STATUSES = frozenset({EventStatus.DRAFT, EventStatus.REGISTRATION})

# Valid state transitions for event lifecycle (CTF-701)
VALID_TRANSITIONS: dict[EventStatus, frozenset[EventStatus]] = {
    EventStatus.DRAFT: frozenset({EventStatus.REGISTRATION, EventStatus.CANCELLED}),
    EventStatus.REGISTRATION: frozenset({EventStatus.ACTIVE, EventStatus.CANCELLED}),
    EventStatus.ACTIVE: frozenset({EventStatus.PAUSED, EventStatus.ENDED, EventStatus.CANCELLED}),
    EventStatus.PAUSED: frozenset({EventStatus.ACTIVE, EventStatus.CANCELLED}),
    EventStatus.ENDED: frozenset({EventStatus.ARCHIVED}),
    EventStatus.CANCELLED: frozenset(),
    EventStatus.ARCHIVED: frozenset(),
}


def validate_transition(current: EventStatus, target: EventStatus) -> bool:
    """Return True if transitioning from current to target is valid."""
    return target in VALID_TRANSITIONS.get(current, frozenset())


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
