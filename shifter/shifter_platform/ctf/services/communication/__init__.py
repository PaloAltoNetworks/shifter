"""Scoped CTF communications service package (ADR-051, #2048).

The service contracts for the communication domain model: the single audience
resolver, campaign authoring with workspace/event confinement, atomic intent
release, lifecycle transitions (cancellation, participant removal, event
cancellation, range replacement), and retention purge. Transports, HTTP
endpoints, range-ingress, and the frontend renderer are later slices of the same
umbrella capability (issue #2047); this package is the durable domain contract.
"""

from __future__ import annotations

from .admission import AdmissionActor
from .audience import resolve_recipients
from .campaigns import CampaignDraft, create_campaign, revise_message
from .lifecycle import cancel_campaign, on_event_cancelled, on_participant_removed, on_range_replaced
from .release import release_campaign, release_due_declaration
from .retention import purge_expired_communications
from .scheduling import request_early_release, run_release_communication_task, schedule_declaration

__all__ = [
    "AdmissionActor",
    "CampaignDraft",
    "cancel_campaign",
    "create_campaign",
    "on_event_cancelled",
    "on_participant_removed",
    "on_range_replaced",
    "purge_expired_communications",
    "release_campaign",
    "release_due_declaration",
    "request_early_release",
    "resolve_recipients",
    "revise_message",
    "run_release_communication_task",
    "schedule_declaration",
]
