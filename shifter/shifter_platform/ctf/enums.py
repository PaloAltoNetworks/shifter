"""CTF-specific enums and constants.

Defines status values, categories, and other constants for CTF operations.
"""

from __future__ import annotations

from enum import Enum


class EventStatus(str, Enum):
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


class ParticipantStatus(str, Enum):
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


class ChallengeDifficulty(str, Enum):
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


class ChallengeVisibility(str, Enum):
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


class ChallengeCategory(str, Enum):
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


class NotificationType(str, Enum):
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


class NotificationStatus(str, Enum):
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


class ScheduledTaskType(str, Enum):
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


class ScheduledTaskStatus(str, Enum):
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


class AttemptLimitMode(str, Enum):
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


class RatingVisibility(str, Enum):
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


class UserType(str, Enum):
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
