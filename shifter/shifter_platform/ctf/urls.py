"""CTF URL configuration.

Defines URL patterns for:
- CTF Admin/Organizer views (/ctf/admin/...)
- CTF Participant views (/ctf/...)
- CTF API endpoints (/ctf/api/...)
"""

from __future__ import annotations

from django.urls import path

from ctf import views

app_name = "ctf"

# -----------------------------------------------------------------------------
# Participant URLs (CTF Competitors)
# -----------------------------------------------------------------------------
participant_patterns = [
    # Dashboard
    path("", views.participant_dashboard, name="participant_dashboard"),
    path("register/", views.ctf_register, name="ctf_register"),
    path("event/", views.participant_event, name="participant_event"),
    # Challenges
    path("challenges/", views.participant_challenges, name="challenges"),
    path("challenges/<uuid:challenge_id>/", views.challenge_detail, name="challenge_detail"),
    # Range
    path("range/", views.participant_range, name="participant_range"),
    # Scoreboard
    path("scoreboard/", views.scoreboard, name="scoreboard"),
    # Team
    path("team/", views.participant_team, name="participant_team"),
    path("team/join/", views.team_join, name="team_join"),
    # Help
    path("help/", views.ctf_help, name="ctf_help"),
]

# -----------------------------------------------------------------------------
# Admin/Organizer URLs
# -----------------------------------------------------------------------------
admin_patterns = [
    # Dashboard
    path("admin/", views.admin_dashboard, name="admin_dashboard"),
    # Events
    path("admin/events/", views.admin_event_list, name="admin_event_list"),
    path("admin/events/create/", views.admin_event_create, name="admin_event_create"),
    path("admin/events/<uuid:event_id>/", views.admin_event_detail, name="admin_event_detail"),
    path("admin/events/<uuid:event_id>/edit/", views.admin_event_edit, name="admin_event_edit"),
    # Challenges
    path(
        "admin/events/<uuid:event_id>/challenges/",
        views.admin_challenge_list,
        name="admin_challenge_list",
    ),
    path(
        "admin/events/<uuid:event_id>/challenges/create/",
        views.admin_challenge_create,
        name="admin_challenge_create",
    ),
    path(
        "admin/challenges/<uuid:challenge_id>/",
        views.admin_challenge_detail,
        name="admin_challenge_detail",
    ),
    path(
        "admin/challenges/<uuid:challenge_id>/edit/",
        views.admin_challenge_edit,
        name="admin_challenge_edit",
    ),
    # Participants
    path(
        "admin/events/<uuid:event_id>/participants/",
        views.admin_participant_list,
        name="admin_participant_list",
    ),
    path(
        "admin/events/<uuid:event_id>/participants/import/",
        views.admin_participant_import,
        name="admin_participant_import",
    ),
    path(
        "admin/events/<uuid:event_id>/participants/add/",
        views.admin_participant_add,
        name="admin_participant_add",
    ),
    path(
        "admin/participants/<uuid:participant_id>/",
        views.admin_participant_detail,
        name="admin_participant_detail",
    ),
    # Teams
    path("admin/events/<uuid:event_id>/teams/", views.admin_team_list, name="admin_team_list"),
    # Scoreboard
    path(
        "admin/events/<uuid:event_id>/scoreboard/",
        views.admin_scoreboard,
        name="admin_scoreboard",
    ),
    # Ranges
    path("admin/events/<uuid:event_id>/ranges/", views.admin_range_list, name="admin_range_list"),
    # Notifications
    path(
        "admin/events/<uuid:event_id>/notifications/",
        views.admin_notification_list,
        name="admin_notification_list",
    ),
    path(
        "admin/events/<uuid:event_id>/notifications/create/",
        views.admin_notification_create,
        name="admin_notification_create",
    ),
    # Analytics
    path(
        "admin/events/<uuid:event_id>/analytics/",
        views.admin_analytics,
        name="admin_analytics",
    ),
    # Challenge file upload (from admin detail page)
    path(
        "admin/challenges/<uuid:challenge_id>/upload/",
        views.admin_challenge_file_upload,
        name="admin_challenge_file_upload",
    ),
]

# -----------------------------------------------------------------------------
# API URLs
# -----------------------------------------------------------------------------
api_patterns = [
    # Event APIs
    path("api/events/", views.api_event_list, name="api_event_list"),
    path("api/events/<uuid:event_id>/", views.api_event_detail, name="api_event_detail"),
    path("api/scenarios/", views.api_scenarios, name="api_scenarios"),
    # Challenge APIs
    path(
        "api/events/<uuid:event_id>/challenges/",
        views.api_challenge_list,
        name="api_challenge_list",
    ),
    path(
        "api/challenges/<uuid:challenge_id>/",
        views.api_challenge_detail,
        name="api_challenge_detail",
    ),
    # Submission APIs
    path(
        "api/challenges/<uuid:challenge_id>/submit/",
        views.api_submit_flag,
        name="api_submit_flag",
    ),
    path(
        "api/challenges/<uuid:challenge_id>/hint/",
        views.api_use_hint,
        name="api_use_hint",
    ),
    path("api/submissions/", views.api_submissions, name="api_submissions"),
    # Participant APIs
    path(
        "api/events/<uuid:event_id>/participants/",
        views.api_participant_list,
        name="api_participant_list",
    ),
    path(
        "api/events/<uuid:event_id>/participants/import/",
        views.api_participant_import,
        name="api_participant_import",
    ),
    path(
        "api/participants/<uuid:participant_id>/",
        views.api_participant_detail,
        name="api_participant_detail",
    ),
    path(
        "api/participants/<uuid:participant_id>/resend-invite/",
        views.api_participant_resend_invite,
        name="api_participant_resend_invite",
    ),
    # Range APIs (participant-facing)
    path("api/range/status/", views.api_range_status, name="api_range_status"),
    path("api/range/access/", views.api_range_access, name="api_range_access"),
    # Range APIs (organizer-facing)
    path(
        "api/events/<uuid:event_id>/ranges/",
        views.api_range_list,
        name="api_range_list",
    ),
    path(
        "api/events/<uuid:event_id>/ranges/provision/",
        views.api_provision_ranges,
        name="api_provision_ranges",
    ),
    path(
        "api/participants/<uuid:participant_id>/range/provision/",
        views.api_provision_participant_range,
        name="api_provision_participant_range",
    ),
    path(
        "api/participants/<uuid:participant_id>/range/destroy/",
        views.api_destroy_participant_range,
        name="api_destroy_participant_range",
    ),
    # Scoreboard APIs
    path(
        "api/events/<uuid:event_id>/scoreboard/",
        views.api_scoreboard,
        name="api_scoreboard",
    ),
    # Notification APIs
    path(
        "api/events/<uuid:event_id>/notifications/",
        views.api_notification_list,
        name="api_notification_list",
    ),
    path(
        "api/notifications/<uuid:notification_id>/send/",
        views.api_notification_send,
        name="api_notification_send",
    ),
    # Invitation APIs
    path(
        "api/events/<uuid:event_id>/invitations/send/",
        views.api_send_invitations,
        name="api_send_invitations",
    ),
    # Flag management APIs
    path(
        "api/challenges/<uuid:challenge_id>/flags/add/",
        views.api_add_flag,
        name="api_add_flag",
    ),
    path(
        "api/flags/<uuid:flag_id>/remove/",
        views.api_remove_flag,
        name="api_remove_flag",
    ),
    # File attachment APIs
    path(
        "api/challenges/<uuid:challenge_id>/files/",
        views.api_challenge_files,
        name="api_challenge_files",
    ),
    path(
        "api/files/<uuid:file_id>/delete/",
        views.api_challenge_file_delete,
        name="api_challenge_file_delete",
    ),
    path(
        "api/files/<uuid:file_id>/download/",
        views.api_file_download,
        name="api_file_download",
    ),
    # Prerequisite APIs
    path(
        "api/challenges/<uuid:challenge_id>/prerequisites/",
        views.api_challenge_prerequisites,
        name="api_challenge_prerequisites",
    ),
    path(
        "api/prerequisites/<uuid:prerequisite_id>/delete/",
        views.api_prerequisite_delete,
        name="api_prerequisite_delete",
    ),
]

# Combine all patterns
urlpatterns = participant_patterns + admin_patterns + api_patterns
