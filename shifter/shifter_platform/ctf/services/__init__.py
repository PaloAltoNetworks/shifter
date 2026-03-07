"""CTF services package.

This package contains service modules for CTF business logic:
- event: Event lifecycle management
- challenge: Challenge CRUD and flag operations
- participant: Participant management
- submission: Flag submission and scoring
- scoring: Score calculation and leaderboards
- range: Range provisioning integration
- notification: Email notifications
- scheduler: Scheduled task management
"""

from ctf.services.challenge import (
    create_challenge,
    delete_challenge,
    get_available_challenges,
    get_challenge,
    hash_flag,
    list_challenges_for_event,
    update_challenge,
    verify_flag,
)
from ctf.services.event import (
    EventNotModifiableError,
    activate_event,
    cancel_event,
    complete_event,
    create_event,
    delete_event,
    end_event,
    get_event,
    get_event_stats,
    get_organizer_events,
    list_events_for_organizer,
    schedule_event,
    start_event,
    update_event,
)

__all__ = [
    # Event services
    "create_event",
    "update_event",
    "delete_event",
    "get_event",
    "get_organizer_events",
    "list_events_for_organizer",
    "schedule_event",
    "activate_event",
    "complete_event",
    "cancel_event",
    "start_event",
    "end_event",
    "get_event_stats",
    "EventNotModifiableError",
    # Challenge services
    "create_challenge",
    "update_challenge",
    "delete_challenge",
    "get_challenge",
    "list_challenges_for_event",
    "get_available_challenges",
    "hash_flag",
    "verify_flag",
]
