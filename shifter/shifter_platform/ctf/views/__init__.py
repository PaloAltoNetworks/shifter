"""CTF views package.

Public view callables are re-exported here so ``from ctf import views``
and ``views.<name>`` (the ``ctf/urls.py`` URLconf) keep resolving after the
split of the former monolithic ``ctf/views.py`` (issue #885, python:S104).
Only URLconf-referenced views are exported; private helpers and framework
objects live in their defining submodules and are patched there.
"""

from __future__ import annotations

from ctf.views.admin_brackets import (
    admin_bracket_create,
    admin_bracket_delete,
    admin_bracket_edit,
    admin_bracket_list,
    api_assign_bracket,
)
from ctf.views.admin_challenges import (
    admin_challenge_create,
    admin_challenge_detail,
    admin_challenge_edit,
    admin_challenge_file_upload,
    admin_challenge_list,
)
from ctf.views.admin_events import (
    admin_analytics,
    admin_dashboard,
    admin_event_create,
    admin_event_detail,
    admin_event_edit,
    admin_event_email_templates,
    admin_event_force_delete,
    admin_event_list,
)
from ctf.views.admin_notifications import (
    admin_notification_create,
    admin_notification_list,
)
from ctf.views.admin_people import (
    admin_participant_add,
    admin_participant_detail,
    admin_participant_import,
    admin_participant_list,
    admin_range_list,
    admin_scoreboard,
    admin_team_list,
)
from ctf.views.api.challenges import (
    api_challenge_detail,
    api_challenge_list,
)
from ctf.views.api.events import (
    api_event_detail,
    api_event_list,
    api_force_delete_event,
    api_scenarios,
)
from ctf.views.api.files import (
    api_challenge_file_delete,
    api_challenge_files,
    api_file_download,
)
from ctf.views.api.flags import (
    api_add_flag,
    api_remove_flag,
)
from ctf.views.api.hints import (
    api_challenge_hints,
    api_hint_delete,
)
from ctf.views.api.notifications import (
    api_event_email_template,
    api_notification_list,
    api_notification_send,
)
from ctf.views.api.participants import (
    api_participant_detail,
    api_participant_import,
    api_participant_list,
    api_participant_resend_invite,
)
from ctf.views.api.play import (
    api_rate_challenge,
    api_submissions,
    api_submit_flag,
    api_use_hint,
)
from ctf.views.api.prerequisites import (
    api_challenge_prerequisites,
    api_prerequisite_delete,
)
from ctf.views.api.ranges import (
    api_destroy_participant_range,
    api_provision_event_spares,
    api_provision_participant_range,
    api_provision_ranges,
    api_range_access,
    api_range_list,
    api_range_status,
    api_recover_participant_range,
    api_restart_participant_range,
    api_send_invitations,
    api_start_participant_range,
    api_stop_participant_range,
)
from ctf.views.api.scoreboard import (
    api_score_timeline,
    api_scoreboard,
)
from ctf.views.participant import (
    ctf_help,
    ctf_register,
    ctf_register_exchange,
    participant_dashboard,
    participant_event,
    participant_range,
    participant_solve_history,
    participant_team,
    scoreboard,
    team_join,
)
from ctf.views.participant_challenges import (
    challenge_detail,
    participant_challenges,
)

__all__ = [
    "admin_analytics",
    "admin_bracket_create",
    "admin_bracket_delete",
    "admin_bracket_edit",
    "admin_bracket_list",
    "admin_challenge_create",
    "admin_challenge_detail",
    "admin_challenge_edit",
    "admin_challenge_file_upload",
    "admin_challenge_list",
    "admin_dashboard",
    "admin_event_create",
    "admin_event_detail",
    "admin_event_edit",
    "admin_event_email_templates",
    "admin_event_force_delete",
    "admin_event_list",
    "admin_notification_create",
    "admin_notification_list",
    "admin_participant_add",
    "admin_participant_detail",
    "admin_participant_import",
    "admin_participant_list",
    "admin_range_list",
    "admin_scoreboard",
    "admin_team_list",
    "api_add_flag",
    "api_assign_bracket",
    "api_challenge_detail",
    "api_challenge_file_delete",
    "api_challenge_files",
    "api_challenge_hints",
    "api_challenge_list",
    "api_challenge_prerequisites",
    "api_destroy_participant_range",
    "api_event_detail",
    "api_event_email_template",
    "api_event_list",
    "api_file_download",
    "api_force_delete_event",
    "api_hint_delete",
    "api_notification_list",
    "api_notification_send",
    "api_participant_detail",
    "api_participant_import",
    "api_participant_list",
    "api_participant_resend_invite",
    "api_prerequisite_delete",
    "api_provision_event_spares",
    "api_provision_participant_range",
    "api_provision_ranges",
    "api_range_access",
    "api_range_list",
    "api_range_status",
    "api_rate_challenge",
    "api_recover_participant_range",
    "api_remove_flag",
    "api_restart_participant_range",
    "api_scenarios",
    "api_score_timeline",
    "api_scoreboard",
    "api_send_invitations",
    "api_start_participant_range",
    "api_stop_participant_range",
    "api_submissions",
    "api_submit_flag",
    "api_use_hint",
    "challenge_detail",
    "ctf_help",
    "ctf_register",
    "ctf_register_exchange",
    "participant_challenges",
    "participant_dashboard",
    "participant_event",
    "participant_range",
    "participant_solve_history",
    "participant_team",
    "scoreboard",
    "team_join",
]
