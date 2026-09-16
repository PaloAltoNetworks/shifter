"""CTF SPA page routes plus server-owned participant authentication.

Workspace reads and mutations use ``/api/v1/ctf/``.  The named page routes are
kept stable for redirects and outbound links, but no legacy form or JSON action
remains reachable below ``/ctf/``.
"""

from django.urls import path, re_path

from ctf import public_views, views
from shared.spa_host import platform_spa_host

app_name = "ctf"

urlpatterns = [
    path(
        "public/events/<uuid:event_id>/",
        public_views.public_event_registration,
        name="public_event_registration",
    ),
    path("", platform_spa_host, name="participant_dashboard"),
    path("login/", views.ctf_login, name="ctf_login"),
    path("change-password/", views.ctf_change_password, name="ctf_change_password"),
    path("event/", platform_spa_host, name="participant_event"),
    path("challenges/", platform_spa_host, name="challenges"),
    path("challenges/<uuid:challenge_id>/", platform_spa_host, name="challenge_detail"),
    path("range/", platform_spa_host, name="participant_range"),
    path("terminal/", platform_spa_host, name="participant_terminal"),
    path("scoreboard/", platform_spa_host, name="scoreboard"),
    path("participants/<uuid:participant_id>/solves/", platform_spa_host, name="participant_solve_history"),
    path("team/", platform_spa_host, name="participant_team"),
    path("team/join/", platform_spa_host, name="team_join"),
    path("help/", platform_spa_host, name="ctf_help"),
    path("admin/", platform_spa_host, name="admin_dashboard"),
    path("admin/events/", platform_spa_host, name="admin_event_list"),
    path("admin/events/create/", platform_spa_host, name="admin_event_create"),
    path("admin/events/<uuid:event_id>/", platform_spa_host, name="admin_event_detail"),
    path("admin/events/<uuid:event_id>/edit/", platform_spa_host, name="admin_event_edit"),
    path("admin/events/<uuid:event_id>/force-delete/", platform_spa_host, name="admin_event_force_delete"),
    path("admin/events/<uuid:event_id>/challenges/", platform_spa_host, name="admin_challenge_list"),
    path("admin/events/<uuid:event_id>/challenges/create/", platform_spa_host, name="admin_challenge_create"),
    path("admin/challenges/<uuid:challenge_id>/", platform_spa_host, name="admin_challenge_detail"),
    path("admin/challenges/<uuid:challenge_id>/edit/", platform_spa_host, name="admin_challenge_edit"),
    path("admin/events/<uuid:event_id>/participants/", platform_spa_host, name="admin_participant_list"),
    path("admin/events/<uuid:event_id>/participants/import/", platform_spa_host, name="admin_participant_import"),
    path("admin/events/<uuid:event_id>/participants/generate/", platform_spa_host, name="admin_participant_batch"),
    path("admin/events/<uuid:event_id>/participants/add/", platform_spa_host, name="admin_participant_add"),
    path("admin/participants/<uuid:participant_id>/", platform_spa_host, name="admin_participant_detail"),
    path("admin/participants/<uuid:participant_id>/rename/", platform_spa_host, name="admin_participant_rename"),
    path("admin/participants/<uuid:participant_id>/delivery-email/", platform_spa_host, name="admin_participant_email"),
    path("admin/participants/<uuid:participant_id>/password/", platform_spa_host, name="admin_participant_password"),
    path("admin/events/<uuid:event_id>/teams/", platform_spa_host, name="admin_team_list"),
    path("admin/events/<uuid:event_id>/scoreboard/", platform_spa_host, name="admin_scoreboard"),
    path("admin/events/<uuid:event_id>/brackets/", platform_spa_host, name="admin_bracket_list"),
    path("admin/events/<uuid:event_id>/brackets/create/", platform_spa_host, name="admin_bracket_create"),
    path("admin/brackets/<uuid:bracket_id>/edit/", platform_spa_host, name="admin_bracket_edit"),
    path("admin/brackets/<uuid:bracket_id>/delete/", platform_spa_host, name="admin_bracket_delete"),
    path("admin/events/<uuid:event_id>/ranges/", platform_spa_host, name="admin_range_list"),
    path("admin/events/<uuid:event_id>/notifications/", platform_spa_host, name="admin_notification_list"),
    path("admin/events/<uuid:event_id>/notifications/create/", platform_spa_host, name="admin_notification_create"),
    path("admin/events/<uuid:event_id>/email-templates/", platform_spa_host, name="admin_event_email_templates"),
    path("admin/events/<uuid:event_id>/analytics/", platform_spa_host, name="admin_analytics"),
    path("admin/challenges/<uuid:challenge_id>/upload/", platform_spa_host, name="admin_challenge_file_upload"),
    re_path(r"^(?!api/|login/|change-password/).*$", platform_spa_host),
]
