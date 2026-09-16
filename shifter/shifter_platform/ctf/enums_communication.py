"""Scoped-communication enums (ADR-051, #2048).

Split from ``ctf.enums`` for the python:S104 file-size budget; re-exported from
``ctf.enums`` so ``from ctf.enums import CommunicationOrigin`` keeps working.
"""

from __future__ import annotations

from enum import StrEnum


class CommunicationOrigin(StrEnum):
    """Where a scoped communication originates (ADR-051, #2048).

    Origin records the SOURCE kind for provenance and audit; it never grants or
    implies authorization, which is decided separately per workspace and event.
    """

    PLATFORM_ADMIN = "platform_admin"
    ORGANIZER_STAFF = "organizer_staff"
    SCHEDULED_SCENARIO = "scheduled_scenario"
    DYNAMIC_RAES = "dynamic_raes"
    SYSTEM_MILESTONE = "system_milestone"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(o.value, o.name.replace("_", " ").title()) for o in cls]


class CommunicationChannel(StrEnum):
    """Selectable delivery channels for a communication (ADR-051, #2048).

    The durable in-app inbox and email are the two transports a campaign may
    select. WebSocket fan-out is a reference-only wake-up, never a selectable
    channel, so it is intentionally absent.
    """

    IN_APP = "in_app"
    EMAIL = "email"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(c.value, c.name.replace("_", " ").title()) for c in cls]


class AcknowledgementPolicy(StrEnum):
    """How a recipient's receipt is satisfied (ADR-051, #2048).

    NONE requires nothing; READ is satisfied by an authenticated inbox-body read;
    EXPLICIT requires a deliberate participant acknowledgement. Email acceptance,
    WebSocket publication, and socket writes never satisfy any of these.
    """

    NONE = "none"
    READ = "read"
    EXPLICIT = "explicit"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(p.value, p.name.title()) for p in cls]


class AudienceKind(StrEnum):
    """Closed audience-selector kinds (ADR-051, #2048).

    The supported product scopes: one participant, an explicit participant set,
    one or more teams, every eligible participant in one event, or an explicit
    union across multiple events. Audiences store public CTF identifiers only,
    never email addresses or ORM predicates.
    """

    PARTICIPANT = "participant"
    PARTICIPANT_SET = "participant_set"
    TEAM = "team"
    EVENT = "event"
    MULTI_EVENT = "multi_event"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(k.value, k.name.replace("_", " ").title()) for k in cls]


class TriggerKind(StrEnum):
    """Closed trigger-declaration kinds (ADR-051, #2048).

    Data, never code: a trigger is a manual action, an event-lifecycle
    transition, an absolute UTC time, a RAES shared-time/script occurrence, or an
    allowlisted range signal. It is never a webhook, dotted callable, or plugin
    entry point.
    """

    MANUAL = "manual"
    EVENT_LIFECYCLE = "event_lifecycle"
    ABSOLUTE_TIME = "absolute_time"
    RAES_OCCURRENCE = "raes_occurrence"
    RANGE_SIGNAL = "range_signal"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(k.value, k.name.replace("_", " ").title()) for k in cls]


class CampaignStatus(StrEnum):
    """Lifecycle of a communication campaign (ADR-051, #2048).

    A campaign is mutable only while DRAFT. SCHEDULED holds a timed trigger;
    RELEASING/RELEASED reflect intent materialization; CANCELLED stops further
    release and any not-yet-claimed work.
    """

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RELEASING = "releasing"
    RELEASED = "released"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(s.value, s.name.title()) for s in cls]


class IntentStatus(StrEnum):
    """Lifecycle of a communication intent (ADR-051, #2048).

    An intent is immutable once RELEASED. SCHEDULED is a timed intent awaiting
    its due occurrence; CANCELLED stops not-yet-claimed work; FENCED marks an
    intent whose range generation was replaced or whose event was cancelled, so
    it can never materialize new work; EXPIRED is a durable no-work terminal
    outcome for a scheduled intent that will never materialize an audience —
    picked up past its lateness/grace window, or permanently un-admittable at due
    time (e.g. authority revoked or audience over budget) — distinct from FENCED
    (#2099).
    """

    SCHEDULED = "scheduled"
    RELEASED = "released"
    CANCELLED = "cancelled"
    FENCED = "fenced"
    EXPIRED = "expired"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(s.value, s.name.title()) for s in cls]


class DeliveryStatus(StrEnum):
    """Truthful, transport-specific delivery-attempt status (ADR-051, #2048; engine #2098).

    Statuses are honest about what actually happened: QUEUED/CLAIMED/RETRY_DUE
    are in-flight, ACCEPTED means the transport backend accepted the message (not
    that it was read), PERMANENT_FAILURE is terminal, and CANCELLED is
    not-yet-claimed work stopped by cancellation. "Accepted" never means received
    or read.

    The delivery engine (#2098) adds two more terminal dispositions that must
    never be silently mapped onto ACCEPTED: SUPPRESSED is a claimed command the
    worker fenced against a cancellation/lifecycle/generation change immediately
    before its irreversible transport boundary (distinct from CANCELLED, which
    stops not-yet-claimed work), and EXPIRED is a command that reached its
    attempt/elapsed ceiling or expiry policy before any backend acceptance.
    """

    QUEUED = "queued"
    CLAIMED = "claimed"
    RETRY_DUE = "retry_due"
    ACCEPTED = "accepted"
    PERMANENT_FAILURE = "permanent_failure"
    CANCELLED = "cancelled"
    SUPPRESSED = "suppressed"
    EXPIRED = "expired"

    def __str__(self) -> str:
        """Return the string value for database storage."""
        return self.value

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return choices for Django model field."""
        return [(s.value, s.name.replace("_", " ").title()) for s in cls]
