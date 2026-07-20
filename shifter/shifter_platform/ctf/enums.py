"""CTF-specific enums and constants.

Defines status values, categories, and other constants for CTF operations.
"""

from __future__ import annotations

from enum import StrEnum

# Recovery-domain enums live in ctf.enums_recovery (python:S104 split); they are
# re-exported here (see __all__ below) so `from ctf.enums import RecoveryPhase`
# keeps working.
from ctf.enums_recovery import (
    RecoveryFailureCategory,
    RecoveryPhase,
    RecoveryStrategy,
    SpareRangeStatus,
)


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
            disqualified / banned

    ``disqualified`` (CTF-609) removes competitive standing but keeps
    view access; ``banned`` (CTF-605) blocks all event access. Both are
    reversible by the organizer and preserve submission history.
    """

    INVITED = "invited"
    REGISTERED = "registered"
    ACTIVE = "active"
    COMPLETED = "completed"
    DISQUALIFIED = "disqualified"
    BANNED = "banned"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class ParticipantRole(StrEnum):
    """Event-scoped participation role (CTF-604).

    ``player`` competes normally; ``observer`` may watch the event
    (scoreboard, content) but cannot submit flags and never ranks.
    """

    PLAYER = "player"
    OBSERVER = "observer"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(role.value, role.name.title()) for role in cls]


class EventStaffRole(StrEnum):
    """Delegated event-staff roles beyond the owning organizer (CTF-607).

    ``moderator`` manages participants and announcements; ``judge`` reviews
    submissions and grants awards. Neither can modify event configuration,
    challenges, or scoring settings.
    """

    MODERATOR = "moderator"
    JUDGE = "judge"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(role.value, role.name.title()) for role in cls]


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
    EVENT_RESULTS = "event_results"
    PROVISION_FAILURE = "provision_failure"
    RANGE_READY = "range_ready"

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
    CLEANUP_WARNING = "cleanup_warning"
    SEND_REMINDER = "send_reminder"
    SEND_NOTIFICATION = "send_notification"
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
    only supported mode. The enum exists so future modes slot in as one
    additional value plus one scoring-service strategy (CTF-002).

    DYNAMIC: decaying per-challenge value (CTF-202). A challenge starts at its
    full point value and decays toward its configured minimum as more
    participants solve it; every new solve retroactively re-prices earlier
    solves so all solvers of a challenge hold the same base value.
    """

    STANDARD = "standard"
    DYNAMIC = "dynamic"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(m.value, m.name.title()) for m in cls]


class DecayFunction(StrEnum):
    """Shape of the dynamic-scoring decay curve (CTF-202).

    LINEAR: value falls in equal steps per solve until the minimum.
    LOGARITHMIC: value falls fastest for early solves, flattening toward the
    minimum (CTFd-style quadratic-over-decay-window curve).
    """

    LINEAR = "linear"
    LOGARITHMIC = "logarithmic"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Django choices tuples."""
        return [(member.value, member.name.title()) for member in cls]


class ScoreboardVisibility(StrEnum):
    """Controls who can view the event scoreboard (CTF-404).

    PUBLIC: Anyone, including unauthenticated viewers (projector screens).
    PARTICIPANTS: Only registered participants and organizers.
    HIDDEN: Only organizers (through the organizer scoreboard surface).
    """

    PUBLIC = "public"
    PARTICIPANTS = "participants"
    HIDDEN = "hidden"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Django choices tuples."""
        return [(member.value, member.name.title()) for member in cls]


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

# Moderation statuses an organizer can lift again (CTF-605 / CTF-609)
PARTICIPANT_MODERATED_STATUSES = frozenset({ParticipantStatus.DISQUALIFIED, ParticipantStatus.BANNED})

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


__all__ = [
    "EVENT_MODIFIABLE_STATUSES",
    "EVENT_TERMINAL_STATUSES",
    "PARTICIPANT_MODERATED_STATUSES",
    "VALID_TRANSITIONS",
    "AttemptLimitMode",
    "ChallengeCategory",
    "ChallengeDifficulty",
    "ChallengeVisibility",
    "DecayFunction",
    "EventStaffRole",
    "EventStatus",
    "NotificationStatus",
    "NotificationType",
    "ParticipantRole",
    "ParticipantStatus",
    "RatingVisibility",
    "RecoveryFailureCategory",
    "RecoveryPhase",
    "RecoveryStrategy",
    "ScheduledTaskStatus",
    "ScheduledTaskType",
    "ScoreboardVisibility",
    "ScoringMode",
    "SpareRangeStatus",
    "UserType",
    "validate_transition",
]
