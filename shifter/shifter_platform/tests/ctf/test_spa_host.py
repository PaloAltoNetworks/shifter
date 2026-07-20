"""Tests for the flag-gated CTF participant workspace SPA host + routing (#1372).

Mirrors ``tests/scenario_editor/test_spa_host.py``. The CTF carve-out requires
BOTH ``PLATFORM_SPA_ENABLED`` and ``CTF_WORKSPACE_SPA_ENABLED`` (the per-surface
extension of the platform flag pattern); either flag alone must not enable the
SPA shell for participant pages. Because participant and organizer share the
``/ctf/`` prefix, the deep-link catch-all is scoped with a negative lookahead:
the participant login / change-password / team-join Django views and the legacy
scoreboard JSON endpoint are NEVER shell-served regardless of the flag state,
while the organizer (``/ctf/admin/*``) GET page paths and client sub-routes ARE
shell-served when both flags are on (the full CTF workspace, #1372). The
organizer create/edit/action form URLs stay Django-served: they are exact routes
matched before the catch-all, so a GET lands on the incumbent Django form and a
POST reaches the Django action, never the shell.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.test import Client
from django.urls import resolve

from ctf import views

pytestmark = pytest.mark.django_db

DASHBOARD_URL = "/ctf/"
CHALLENGES_URL = "/ctf/challenges/"
SCOREBOARD_URL = "/ctf/scoreboard/"
TEAM_URL = "/ctf/team/"
RANGE_URL = "/ctf/range/"
HELP_URL = "/ctf/help/"
ADMIN_URL = "/ctf/admin/"
LOGIN_URL = "/ctf/login/"


@pytest.fixture
def spa_on(settings):
    settings.PLATFORM_SPA_ENABLED = True
    settings.CTF_WORKSPACE_SPA_ENABLED = True


@pytest.fixture
def spa_off(settings):
    settings.PLATFORM_SPA_ENABLED = False
    settings.CTF_WORKSPACE_SPA_ENABLED = False


class TestSpaEnabled:
    def test_dashboard_serves_shell_and_primes_csrf(self, spa_on, authenticated_participant_client):
        resp = authenticated_participant_client.get(DASHBOARD_URL)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content
        assert "csrftoken" in resp.cookies

    @pytest.mark.parametrize("url", [CHALLENGES_URL, SCOREBOARD_URL, TEAM_URL, RANGE_URL, HELP_URL, "/ctf/event/"])
    def test_participant_pages_serve_shell(self, spa_on, authenticated_participant_client, url):
        resp = authenticated_participant_client.get(url)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_challenge_detail_deep_link_serves_shell(self, spa_on, authenticated_participant_client):
        # Client-routed even for a challenge id that does not exist server-side.
        resp = authenticated_participant_client.get(f"/ctf/challenges/{uuid4()}/")
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_client_router_catchall_serves_shell(self, spa_on, authenticated_participant_client):
        # A participant client sub-route with no exact server route resolves to
        # the shell via the scoped catch-all.
        resp = authenticated_participant_client.get(f"/ctf/challenges/{uuid4()}/notes/")
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_shell_served_without_participant_role(self, spa_on, authenticated_standard_client):
        # The shell host is thin-auth (authenticated only); per-surface access is
        # enforced by the /api/v1/ctf/ endpoints the SPA calls. Any authenticated
        # user gets the shell markup.
        resp = authenticated_standard_client.get(CHALLENGES_URL)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_anonymous_redirects_to_login(self, spa_on):
        resp = Client().get(DASHBOARD_URL)
        assert resp.status_code == 302

    def test_post_falls_through_to_django_when_enabled(self, spa_on, ctf_participant, authenticated_participant_client):
        # The shell (require_safe) must not take over unsafe methods; a POST must
        # reach the Django view, not the shell (the SPA mutates via /api/v1/ctf/).
        resp = authenticated_participant_client.post(DASHBOARD_URL, {})
        assert b'id="root"' not in resp.content

    def test_login_never_shell_served(self, spa_on):
        resp = Client().get(LOGIN_URL)
        assert b'id="root"' not in resp.content


class TestSpaDisabled:
    def test_dashboard_serves_django_page_not_shell(self, spa_off, ctf_participant, authenticated_participant_client):
        resp = authenticated_participant_client.get(DASHBOARD_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content

    def test_client_router_catchall_404s(self, spa_off, authenticated_participant_client):
        resp = authenticated_participant_client.get(f"/ctf/challenges/{uuid4()}/notes/")
        assert resp.status_code == 404


class TestSpaRequiresBothFlags:
    def test_platform_flag_alone_does_not_enable_ctf_spa(
        self, ctf_participant, authenticated_participant_client, settings
    ):
        settings.PLATFORM_SPA_ENABLED = True
        settings.CTF_WORKSPACE_SPA_ENABLED = False
        resp = authenticated_participant_client.get(DASHBOARD_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content

    def test_ctf_flag_alone_does_not_enable_without_platform_flag(
        self, ctf_participant, authenticated_participant_client, settings
    ):
        settings.PLATFORM_SPA_ENABLED = False
        settings.CTF_WORKSPACE_SPA_ENABLED = True
        resp = authenticated_participant_client.get(DASHBOARD_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content


class TestOrganizerSpaEnabled:
    """The organizer (``/ctf/admin/*``) GET pages join the SPA shell once both
    flags are on (#1372). The shell host is thin-auth, so the wrapped ``_page``
    views serve the shell for safe methods without invoking the Django view (a
    bogus id still resolves to the shell — the client router owns the page)."""

    # Fixed placeholder ids so the parametrize ids are stable across xdist
    # workers (uuid4() at collection time diverges per worker). The wrapped
    # ``_page`` views serve the shell without invoking the Django view, so the
    # ids never need to resolve to real objects.
    _EVENT = "00000000-0000-4000-8000-000000000001"
    _CHALLENGE = "00000000-0000-4000-8000-000000000002"
    _PARTICIPANT = "00000000-0000-4000-8000-000000000003"
    ADMIN_GET_PAGES = [
        "/ctf/admin/",
        "/ctf/admin/events/",
        f"/ctf/admin/events/{_EVENT}/",
        f"/ctf/admin/events/{_EVENT}/challenges/",
        f"/ctf/admin/challenges/{_CHALLENGE}/",
        f"/ctf/admin/events/{_EVENT}/participants/",
        f"/ctf/admin/participants/{_PARTICIPANT}/",
        f"/ctf/admin/events/{_EVENT}/teams/",
        f"/ctf/admin/events/{_EVENT}/scoreboard/",
        f"/ctf/admin/events/{_EVENT}/brackets/",
        f"/ctf/admin/events/{_EVENT}/ranges/",
        f"/ctf/admin/events/{_EVENT}/notifications/",
        f"/ctf/admin/events/{_EVENT}/email-templates/",
        f"/ctf/admin/events/{_EVENT}/analytics/",
    ]

    @pytest.mark.parametrize("url", ADMIN_GET_PAGES)
    def test_admin_get_pages_serve_shell(self, spa_on, authenticated_organizer_client, url):
        resp = authenticated_organizer_client.get(url)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_admin_client_deep_link_serves_shell(self, spa_on, authenticated_organizer_client):
        # An organizer client sub-route with no exact server route resolves to the
        # shell via the (now admin-inclusive) catch-all.
        resp = authenticated_organizer_client.get(f"/ctf/admin/events/{uuid4()}/monitoring/")
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_admin_unknown_deep_link_serves_shell(self, spa_on, authenticated_organizer_client):
        # A bogus admin path is shell-served (the client router renders its own
        # Not Found), matching the participant catch-all behaviour.
        resp = authenticated_organizer_client.get("/ctf/admin/does-not-exist/")
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_admin_create_page_never_shell_served(self, spa_on, authenticated_organizer_client):
        # The create form owns a POST and stays Django-served: a GET lands on the
        # incumbent Django form, never the shell, even with the flags on.
        resp = authenticated_organizer_client.get("/ctf/admin/events/create/")
        assert b'id="root"' not in resp.content

    def test_admin_post_falls_through_to_django(self, spa_on, authenticated_organizer_client):
        # The require_safe shell must not take over unsafe methods on a wrapped
        # page; a POST reaches Django (the SPA mutates via /api/v1/ctf/).
        resp = authenticated_organizer_client.post(ADMIN_URL, {})
        assert b'id="root"' not in resp.content


class TestOrganizerSpaDisabled:
    def test_admin_dashboard_serves_django_not_shell(self, spa_off, authenticated_organizer_client):
        resp = authenticated_organizer_client.get(ADMIN_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content

    def test_admin_unknown_deep_link_404s(self, spa_off, authenticated_organizer_client):
        resp = authenticated_organizer_client.get("/ctf/admin/does-not-exist/")
        assert resp.status_code == 404


def test_participant_auth_and_organizer_form_routes_stay_django():
    """The participant login / change-password / team-join Django views, the
    legacy scoreboard JSON endpoint, and every organizer create/edit/action form
    URL keep serving their real Django views regardless of the SPA flags (never
    wrapped by ``_page``)."""
    assert resolve("/ctf/login/").func is views.ctf_login
    assert resolve("/ctf/change-password/").func is views.ctf_change_password
    assert resolve("/ctf/team/join/").func is views.team_join
    assert resolve(f"/ctf/api/events/{uuid4()}/scoreboard/").func is views.api_scoreboard
    # Organizer create/edit/action forms stay Django-served (exact routes).
    assert resolve("/ctf/admin/events/create/").func is views.admin_event_create
    assert resolve(f"/ctf/admin/events/{uuid4()}/edit/").func is views.admin_event_edit
    assert resolve(f"/ctf/admin/events/{uuid4()}/force-delete/").func is views.admin_event_force_delete
    assert resolve(f"/ctf/admin/events/{uuid4()}/challenges/create/").func is views.admin_challenge_create
    assert resolve(f"/ctf/admin/challenges/{uuid4()}/edit/").func is views.admin_challenge_edit
    assert resolve(f"/ctf/admin/events/{uuid4()}/participants/import/").func is views.admin_participant_import
    assert resolve(f"/ctf/admin/brackets/{uuid4()}/delete/").func is views.admin_bracket_delete
    assert resolve(f"/ctf/admin/events/{uuid4()}/notifications/create/").func is views.admin_notification_create


def test_organizer_get_pages_are_wrapped():
    """The organizer GET page routes are wrapped by ``_page`` (so the shell can
    take over): the resolved view is the dispatch wrapper, not the raw Django
    view, but the route name is preserved for ``reverse()`` callers."""
    match = resolve("/ctf/admin/")
    assert match.func is not views.admin_dashboard
    assert match.view_name == "ctf:admin_dashboard"
