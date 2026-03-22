"""CTF services package.

This package contains service modules for CTF business logic:
- event: Event lifecycle management
- challenge: Challenge CRUD and flag operations
- participant: Participant management
- submission: Flag submission and scoring
- scoring: Score calculation and leaderboards
- award: Organizer-granted awards
- range: Range provisioning integration
- notification: Email notifications
"""

from ctf.services.award import (
    get_event_awards,
    get_participant_awards,
    grant_award,
    revoke_award,
)
from ctf.services.challenge import (
    add_flag,
    create_challenge,
    delete_challenge,
    get_available_challenges,
    get_challenge,
    hash_flag,
    list_challenges_for_event,
    remove_flag,
    update_challenge,
    verify_flag,
    verify_single_flag,
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
    "add_flag",
    "bulk_import_participants",
    "calculate_score",
    "cancel_event",
    "cleanup_event_ranges",
    "complete_event",
    "create_challenge",
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
    "get_event_awards",
    "get_event_statistics",
    "get_event_stats",
    "get_organizer_events",
    "get_participant",
    "get_participant_awards",
    "get_participant_by_user",
    "get_participant_rank",
    "get_participant_submissions",
    "get_range_access_url",
    "get_range_status",
    "get_scoreboard",
    "get_team_scoreboard",
    "grant_award",
    "hash_flag",
    "invite_participant",
    "list_challenges_for_event",
    "list_events_for_organizer",
    "list_participants_for_event",
    "provision_event_ranges",
    "provision_participant_range",
    "remove_flag",
    "resend_invite",
    "revoke_award",
    "schedule_event",
    "start_event",
    "submit_flag",
    "update_challenge",
    "update_event",
    "update_participant_range_status",
    "use_hint",
    "verify_flag",
    "verify_single_flag",
]
