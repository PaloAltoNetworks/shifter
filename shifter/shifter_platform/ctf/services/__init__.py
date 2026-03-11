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
from ctf.services.participant import (
    bulk_import_participants,
    delete_participant,
    disqualify_participant,
    get_participant,
    get_participant_by_user,
    invite_participant,
    list_participants_for_event,
    register_participant,
    resend_invite,
)
from ctf.services.range import (
    cleanup_event_ranges,
    destroy_participant_range,
    get_range_access_url,
    get_range_status,
    provision_event_ranges,
    provision_participant_range,
    update_participant_range_status,
)
from ctf.services.scoring import (
    calculate_score,
    get_challenge_statistics,
    get_event_statistics,
    get_participant_rank,
    get_scoreboard,
    get_team_scoreboard,
)
from ctf.services.submission import (
    get_challenge_submissions,
    get_correct_submissions,
    get_participant_submissions,
    submit_flag,
    use_hint,
)

__all__ = [
    "EventNotModifiableError",
    "activate_event",
    "bulk_import_participants",
    # Scoring services
    "calculate_score",
    "cancel_event",
    # Range services
    "cleanup_event_ranges",
    "complete_event",
    # Challenge services
    "create_challenge",
    # Event services
    "create_event",
    "delete_challenge",
    "delete_event",
    "delete_participant",
    "destroy_participant_range",
    "disqualify_participant",
    "end_event",
    "get_available_challenges",
    "get_challenge",
    "get_challenge_statistics",
    "get_challenge_submissions",
    "get_correct_submissions",
    "get_event",
    "get_event_statistics",
    "get_event_stats",
    "get_organizer_events",
    "get_participant",
    "get_participant_by_user",
    "get_participant_rank",
    "get_participant_submissions",
    "get_range_access_url",
    "get_range_status",
    "get_scoreboard",
    "get_team_scoreboard",
    "hash_flag",
    # Participant services
    "invite_participant",
    "list_challenges_for_event",
    "list_events_for_organizer",
    "list_participants_for_event",
    "provision_event_ranges",
    "provision_participant_range",
    "register_participant",
    "resend_invite",
    "schedule_event",
    "start_event",
    # Submission services
    "submit_flag",
    "update_challenge",
    "update_event",
    "update_participant_range_status",
    "use_hint",
    "verify_flag",
]
