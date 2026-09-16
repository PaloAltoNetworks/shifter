"""Participant and registration enums split from :mod:`ctf.enums`."""

from enum import StrEnum


class ParticipantStatus(StrEnum):
    """CTF participant lifecycle status.

    Organizer creation is immediate seat provisioning: a participant is
    ``registered`` when created. Disqualification preserves view access while
    banning blocks all event access; both states remain reversible.
    """

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
        """Return choices for Django model fields."""
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class PublicRegistrationDisposition(StrEnum):
    """Organizer-controlled lifecycle of one untrusted public intake row."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model fields and serializers."""
        return [(status.value, status.name.replace("_", " ").title()) for status in cls]


class ParticipantRole(StrEnum):
    """Event-scoped participation role (CTF-604).

    Players compete normally. Observers may view the event but cannot submit
    flags and never appear in rankings.
    """

    PLAYER = "player"
    OBSERVER = "observer"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model fields."""
        return [(role.value, role.name.title()) for role in cls]
