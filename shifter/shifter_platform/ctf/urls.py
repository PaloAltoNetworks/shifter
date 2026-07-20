"""CTF URL configuration.

Defines URL patterns for:
- CTF Admin/Organizer views (/ctf/admin/...)
- CTF Participant views (/ctf/...)
- CTF scoreboard JSON endpoint (/ctf/api/events/<id>/scoreboard/)

The legacy ``/ctf/api/*`` JSON API was retired (issue #1328): the UI and all
callers use the canonical ``/api/v1/ctf/`` DRF routes (see ``ctf.api.urls``).
The single scoreboard endpoint is intentionally retained on the legacy route
because the v1 scoreboard (``v1:ctf:api_scoreboard`` -> ``PublicScoreboardView``)
has different access semantics than the participant scoreboard page requires.

Rollout-flag aware (issue #1372, ADR-013 / ADR-029), mirroring
``cms.scenario_editor.urls``. When the SPA shell is enabled, the participant GET
page paths (dashboard, event, challenges, challenge detail, range, scoreboard,
solve history, team, help) AND the organizer GET page paths (admin dashboard,
event list/detail, challenge list/detail, participant list/detail, team list,
scoreboard, bracket list, range list, notification list, email templates,
analytics) are served by the platform SPA host view (the full CTF workspace
rehomed under the unified client router); when off (the default), the classic
Django template views handle them. The decision is made **per request** (not at
import) so the flag can be flipped without a restart and so tests can toggle it
with ``override_settings``. The enable check honours both ``PLATFORM_SPA_ENABLED``
(the platform-wide control) and ``CTF_WORKSPACE_SPA_ENABLED`` (the CTF-specific
extension of that flag pattern) — both must be on. Route *names* are identical in
both modes so ``reverse("ctf:...")`` callers keep working across the cutover.

Deliberately never wrapped (server-owned auth/forms + POST/create/edit action
pages the SPA replaces by mutating via ``/api/v1/ctf/``): the participant login /
change-password / team-join Django views, the legacy scoreboard JSON endpoint,
and every organizer create/edit/action page (event create/edit/force-delete,
challenge create/edit/file-upload, participant import/generate/add/rename/email,
bracket create/edit/delete, notification create). Those legacy form POST URLs
stay Django-served for rollback, and — being exact routes declared before the
catch-all — a GET to them serves the incumbent Django form, never the shell. The
client-router catch-all is scoped with a negative lookahead so the login /
change-password / team-join / legacy-API paths are never swallowed by the shell,
while organizer (``/ctf/admin/*``) client deep-links ARE shell-served (safe
methods, flag on) so the organizer client router resolves its own routes on
refresh.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import path, re_path

from ctf import views
from shared.spa_host import platform_spa_host

app_name = "ctf"


def _spa_enabled() -> bool:
    """Return whether the SPA shell should serve the CTF participant pages."""
    return bool(
        getattr(settings, "PLATFORM_SPA_ENABLED", False) and getattr(settings, "CTF_WORKSPACE_SPA_ENABLED", False)
    )


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _page(django_view: Callable[..., HttpResponse] | None) -> Callable[..., HttpResponse]:
    """Return a view that serves the SPA shell for a page path, else the Django page.

    The shell takeover is **method-aware**: several legacy participant page paths
    are handled by Django views that own BOTH page rendering (GET) AND a form
    submission (POST) on the same URL. Serving the ``@require_safe`` SPA shell for
    those unsafe methods would 405 the legacy form POST and break the old-tab /
    rollback guarantee. So the shell is served only for safe methods when enabled;
    unsafe methods always fall through to the incumbent Django view (the SPA itself
    mutates exclusively via the canonical ``/api/v1/ctf/`` routes).

    ``django_view=None`` marks a client-router-only path: it serves the shell for
    safe methods when the SPA is enabled and 404s otherwise (so the catch-all is
    inert in the default Django mode and never swallows an unsafe request).
    """

    def _dispatch(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """Serve the SPA shell for safe methods when enabled, else the Django page (or 404)."""
        if _spa_enabled() and request.method in _SAFE_METHODS:
            return platform_spa_host(request, *args, **kwargs)
        if django_view is None:
            raise Http404
        return django_view(request, *args, **kwargs)

    return _dispatch


# -----------------------------------------------------------------------------
# Participant URLs (CTF Competitors)
# -----------------------------------------------------------------------------
participant_patterns = [
    # Dashboard
    path("", _page(views.participant_dashboard), name="participant_dashboard"),
    # Auth pages stay Django-handled: server-owned login/password forms are not a
    # participant-workspace SPA goal in this slice.
    path("login/", views.ctf_login, name="ctf_login"),
    path("change-password/", views.ctf_change_password, name="ctf_change_password"),
    path("event/", _page(views.participant_event), name="participant_event"),
    # Challenges
    path("challenges/", _page(views.participant_challenges), name="challenges"),
    path("challenges/<uuid:challenge_id>/", _page(views.challenge_detail), name="challenge_detail"),
    # Range
    path("range/", _page(views.participant_range), name="participant_range"),
    # Scoreboard
    path("scoreboard/", _page(views.scoreboard), name="scoreboard"),
    path(
        "participants/<uuid:participant_id>/solves/",
        _page(views.participant_solve_history),
        name="participant_solve_history",
    ),
    # Team
    path("team/", _page(views.participant_team), name="participant_team"),
    # Team join owns a POST form; stays Django-handled.
    path("team/join/", views.team_join, name="team_join"),
    # Help
    path("help/", _page(views.ctf_help), name="ctf_help"),
]

# -----------------------------------------------------------------------------
# Admin/Organizer URLs
# -----------------------------------------------------------------------------
# GET page views are wrapped with ``_page`` so the SPA shell serves them (safe
# methods, both flags on) and the organizer client router owns the page; the
# create/edit/force-delete/import/action views own POST forms and stay
# Django-served (the SPA mutates via ``/api/v1/ctf/``), kept for rollback.
admin_patterns = [
    # Dashboard
    path("admin/", _page(views.admin_dashboard), name="admin_dashboard"),
    # Events
    path("admin/events/", _page(views.admin_event_list), name="admin_event_list"),
    path("admin/events/create/", views.admin_event_create, name="admin_event_create"),
    path("admin/events/<uuid:event_id>/", _page(views.admin_event_detail), name="admin_event_detail"),
    path("admin/events/<uuid:event_id>/edit/", views.admin_event_edit, name="admin_event_edit"),
    path(
        "admin/events/<uuid:event_id>/force-delete/",
        views.admin_event_force_delete,
        name="admin_event_force_delete",
    ),
    # Challenges
    path(
        "admin/events/<uuid:event_id>/challenges/",
        _page(views.admin_challenge_list),
        name="admin_challenge_list",
    ),
    path(
        "admin/events/<uuid:event_id>/challenges/create/",
        views.admin_challenge_create,
        name="admin_challenge_create",
    ),
    path(
        "admin/challenges/<uuid:challenge_id>/",
        _page(views.admin_challenge_detail),
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
        _page(views.admin_participant_list),
        name="admin_participant_list",
    ),
    path(
        "admin/events/<uuid:event_id>/participants/import/",
        views.admin_participant_import,
        name="admin_participant_import",
    ),
    path(
        "admin/events/<uuid:event_id>/participants/generate/",
        views.admin_participant_batch,
        name="admin_participant_batch",
    ),
    path(
        "admin/events/<uuid:event_id>/participants/add/",
        views.admin_participant_add,
        name="admin_participant_add",
    ),
    path(
        "admin/participants/<uuid:participant_id>/",
        _page(views.admin_participant_detail),
        name="admin_participant_detail",
    ),
    path(
        "admin/participants/<uuid:participant_id>/rename/",
        views.admin_participant_rename,
        name="admin_participant_rename",
    ),
    path(
        "admin/participants/<uuid:participant_id>/delivery-email/",
        views.admin_participant_email,
        name="admin_participant_email",
    ),
    # Teams
    path("admin/events/<uuid:event_id>/teams/", _page(views.admin_team_list), name="admin_team_list"),
    # Scoreboard
    path(
        "admin/events/<uuid:event_id>/scoreboard/",
        _page(views.admin_scoreboard),
        name="admin_scoreboard",
    ),
    # Brackets
    path(
        "admin/events/<uuid:event_id>/brackets/",
        _page(views.admin_bracket_list),
        name="admin_bracket_list",
    ),
    path(
        "admin/events/<uuid:event_id>/brackets/create/",
        views.admin_bracket_create,
        name="admin_bracket_create",
    ),
    path(
        "admin/brackets/<uuid:bracket_id>/edit/",
        views.admin_bracket_edit,
        name="admin_bracket_edit",
    ),
    path(
        "admin/brackets/<uuid:bracket_id>/delete/",
        views.admin_bracket_delete,
        name="admin_bracket_delete",
    ),
    # Ranges
    path("admin/events/<uuid:event_id>/ranges/", _page(views.admin_range_list), name="admin_range_list"),
    # Notifications
    path(
        "admin/events/<uuid:event_id>/notifications/",
        _page(views.admin_notification_list),
        name="admin_notification_list",
    ),
    path(
        "admin/events/<uuid:event_id>/notifications/create/",
        views.admin_notification_create,
        name="admin_notification_create",
    ),
    # Email Templates
    path(
        "admin/events/<uuid:event_id>/email-templates/",
        _page(views.admin_event_email_templates),
        name="admin_event_email_templates",
    ),
    # Analytics
    path(
        "admin/events/<uuid:event_id>/analytics/",
        _page(views.admin_analytics),
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
    # Scoreboard API: intentionally retained on the legacy /ctf/api/ route (#1328).
    # Every other legacy /ctf/api/* endpoint was retired in favour of /api/v1/ctf/.
    path(
        "api/events/<uuid:event_id>/scoreboard/",
        views.api_scoreboard,
        name="api_scoreboard",
    ),
]

# -----------------------------------------------------------------------------
# Client-router deep-link catch-all (participant + organizer)
# -----------------------------------------------------------------------------
# Participant and organizer share the ``/ctf/`` prefix. This catch-all serves the
# SPA shell (safe methods, when both flags are on; 404 otherwise) for any
# ``/ctf/*`` deep link — including organizer (``/ctf/admin/*``) client sub-routes
# — that is NOT a Django-owned prefix. It is scoped with a negative lookahead
# excluding the server-owned auth views (login / change-password / team-join) and
# the legacy scoreboard JSON API, which must never be shell-served. Declared last,
# so every exact participant, organizer, and API route (the wrapped GET pages and
# the Django-only create/edit/action POST forms) is matched first; the catch-all
# only covers client sub-routes with no exact server route. Unsafe methods on a
# non-existent path fall through to the ``_page(None)`` 404 (never the shell), so a
# stray POST is never swallowed.
_spa_catchall = re_path(
    r"^(?!api/|login/|change-password/|team/join/).*$",
    _page(None),
)

# Combine all patterns
urlpatterns = participant_patterns + admin_patterns + api_patterns + [_spa_catchall]
