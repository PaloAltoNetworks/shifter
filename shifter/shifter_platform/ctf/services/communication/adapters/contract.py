"""Channel adapter command/result contract for the delivery engine (ADR-051-R12, #2098).

A channel adapter is the ONLY seam between the durable ledger and a transport. The
worker hands an adapter a bounded, immutable :class:`DeliveryCommand` (identifiers
and non-secret projections only), the adapter attempts exactly one delivery within
a bounded timeout, and returns a closed :class:`DeliveryOutcome`. The adapter never
decides authorization, audience, retry policy, or scheduling; those stay owned by
the ledger and the worker.

Registration is a plain, closed module-level mapping populated at import, never an
``AppConfig.ready()`` workflow hook or a dynamic plugin registry (preflight
non-goal). The email adapter is #1525 and is deliberately absent, so the worker
simply does not claim ``email`` commands until its owner registers it (no silent
downgrade, no invented acceptance).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID


class OutcomeClass(StrEnum):
    """Closed classification of a single delivery attempt's observed result.

    ``ACCEPTED`` means the transport backend (or socket) accepted the message; it
    never means read or acknowledged. ``RETRIABLE`` is a transient failure the
    worker may retry within its bounded budget. ``TERMINAL`` is a permanent failure
    that must not be retried. ``SUPPRESSED`` means the adapter declined because a
    cancellation/lifecycle/generation fence applied before its irreversible boundary.
    """

    ACCEPTED = "accepted"
    RETRIABLE = "retriable"
    TERMINAL = "terminal"
    SUPPRESSED = "suppressed"


@dataclass(frozen=True)
class DeliveryCommand:
    """Bounded, immutable input for one delivery attempt (reference-only).

    Carries stable identities and non-secret projections. The in-app channel never
    receives the email coordinate or decrypted body; the email adapter (#1525)
    resolves its own coordinate from the snapshot under its own boundary.
    """

    attempt_id: UUID
    intent_id: UUID
    snapshot_id: UUID
    channel: str
    event_id: UUID
    participant_public_id: UUID
    recipient_user_id: int | None
    occurrence_key: str


@dataclass(frozen=True)
class DeliveryOutcome:
    """The closed result of one delivery attempt.

    ``reason`` is a bounded, closed reason class for metrics/audit, never raw
    provider/model text. ``provider_receipt`` is an optional stable backend message
    identity used to mitigate at-least-once duplicates where supported.
    """

    outcome: OutcomeClass
    reason: str = ""
    provider_receipt: str = ""


@runtime_checkable
class ChannelAdapter(Protocol):
    """The bounded transport seam every channel implements."""

    channel: str

    def deliver(self, command: DeliveryCommand, *, timeout: float) -> DeliveryOutcome:
        """Attempt exactly one delivery for ``command`` within ``timeout`` seconds."""
        ...


_ADAPTERS: dict[str, ChannelAdapter] = {}


def register_adapter(adapter: ChannelAdapter) -> None:
    """Register (or replace) the adapter for its channel in the closed mapping."""
    _ADAPTERS[adapter.channel] = adapter


def get_adapter(channel: str) -> ChannelAdapter | None:
    """Return the registered adapter for ``channel``, or ``None`` when unavailable."""
    return _ADAPTERS.get(channel)


def registered_channels() -> frozenset[str]:
    """Return the channels that currently have a registered adapter.

    The worker claims only commands whose channel is in this set, so an
    unregistered channel (e.g. ``email`` before #1525) is never claimed, downgraded,
    or falsely marked accepted.
    """
    return frozenset(_ADAPTERS)
