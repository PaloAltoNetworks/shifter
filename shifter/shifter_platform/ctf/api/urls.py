"""Canonical /api/v1 CTF API routes."""

from __future__ import annotations

from django.urls import path

from ctf.api import views

app_name = "ctf"

urlpatterns = [
    path("events/", views.api_event_list, name="api_event_list"),
    path("events/<uuid:event_id>/", views.api_event_detail, name="api_event_detail"),
    path("events/<uuid:event_id>/force-delete/", views.api_force_delete_event, name="api_force_delete_event"),
    path("scenarios/", views.api_scenarios, name="api_scenarios"),
    path("events/<uuid:event_id>/challenges/", views.api_challenge_list, name="api_challenge_list"),
    path("challenges/<uuid:challenge_id>/", views.api_challenge_detail, name="api_challenge_detail"),
    path("challenges/<uuid:challenge_id>/submit/", views.api_submit_flag, name="api_submit_flag"),
    path("challenges/<uuid:challenge_id>/hint/", views.api_use_hint, name="api_use_hint"),
    path("challenges/<uuid:challenge_id>/hints/", views.api_challenge_hints, name="api_challenge_hints"),
    path("hints/<uuid:hint_id>/delete/", views.api_hint_delete, name="api_hint_delete"),
    path("challenges/<uuid:challenge_id>/rate/", views.api_rate_challenge, name="api_rate_challenge"),
    path("submissions/", views.api_submissions, name="api_submissions"),
    path("events/<uuid:event_id>/participants/", views.api_participant_list, name="api_participant_list"),
    path("events/<uuid:event_id>/participants/import/", views.api_participant_import, name="api_participant_import"),
    path("participants/<uuid:participant_id>/", views.api_participant_detail, name="api_participant_detail"),
    path(
        "participants/<uuid:participant_id>/resend-invite/",
        views.api_participant_resend_invite,
        name="api_participant_resend_invite",
    ),
    path("range/status/", views.api_range_status, name="api_range_status"),
    path("range/access/", views.api_range_access, name="api_range_access"),
    path("events/<uuid:event_id>/ranges/", views.api_range_list, name="api_range_list"),
    path("events/<uuid:event_id>/ranges/provision/", views.api_provision_ranges, name="api_provision_ranges"),
    path(
        "participants/<uuid:participant_id>/range/provision/",
        views.api_provision_participant_range,
        name="api_provision_participant_range",
    ),
    path(
        "participants/<uuid:participant_id>/range/destroy/",
        views.api_destroy_participant_range,
        name="api_destroy_participant_range",
    ),
    path(
        "participants/<uuid:participant_id>/range/stop/",
        views.api_stop_participant_range,
        name="api_stop_participant_range",
    ),
    path(
        "participants/<uuid:participant_id>/range/start/",
        views.api_start_participant_range,
        name="api_start_participant_range",
    ),
    path(
        "participants/<uuid:participant_id>/range/restart/",
        views.api_restart_participant_range,
        name="api_restart_participant_range",
    ),
    path("participants/<uuid:participant_id>/bracket/", views.api_assign_bracket, name="api_assign_bracket"),
    path("events/<uuid:event_id>/scoreboard/", views.api_scoreboard, name="api_scoreboard"),
    path(
        "participants/<uuid:participant_id>/score-timeline/",
        views.api_score_timeline,
        name="api_score_timeline",
    ),
    path("events/<uuid:event_id>/notifications/", views.api_notification_list, name="api_notification_list"),
    path("notifications/<uuid:notification_id>/send/", views.api_notification_send, name="api_notification_send"),
    path(
        "events/<uuid:event_id>/email-templates/<str:notification_type>/",
        views.api_event_email_template,
        name="api_event_email_template",
    ),
    path("events/<uuid:event_id>/invitations/send/", views.api_send_invitations, name="api_send_invitations"),
    path("challenges/<uuid:challenge_id>/flags/add/", views.api_add_flag, name="api_add_flag"),
    path("flags/<uuid:flag_id>/remove/", views.api_remove_flag, name="api_remove_flag"),
    path("challenges/<uuid:challenge_id>/files/", views.api_challenge_files, name="api_challenge_files"),
    path("files/<uuid:file_id>/delete/", views.api_challenge_file_delete, name="api_challenge_file_delete"),
    path("files/<uuid:file_id>/download/", views.api_file_download, name="api_file_download"),
    path(
        "challenges/<uuid:challenge_id>/prerequisites/",
        views.api_challenge_prerequisites,
        name="api_challenge_prerequisites",
    ),
    path(
        "prerequisites/<uuid:prerequisite_id>/delete/",
        views.api_prerequisite_delete,
        name="api_prerequisite_delete",
    ),
]
