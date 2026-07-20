"""Tests for the flag-gated Mission Control SPA host view + routing (#1370).

Mirrors ``tests/risk_register/test_spa_host.py``. The Mission Control carve-out
requires BOTH ``PLATFORM_SPA_ENABLED`` and ``MISSION_CONTROL_SPA_ENABLED`` (the
per-surface extension of the platform flag pattern); either flag alone must not
enable the SPA shell for Mission Control pages. Legacy POST action URLs and the
legacy JSON API endpoints under ``api/`` stay Django-handled regardless of the
flag state.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import Resolver404, resolve

from mission_control import views

pytestmark = pytest.mark.django_db

DASHBOARD_URL = "/mission-control/"
AGENTS_URL = "/mission-control/agents/"


@pytest.fixture
def spa_on(settings):
    settings.PLATFORM_SPA_ENABLED = True
    settings.MISSION_CONTROL_SPA_ENABLED = True


@pytest.fixture
def spa_off(settings):
    settings.PLATFORM_SPA_ENABLED = False
    settings.MISSION_CONTROL_SPA_ENABLED = False


class TestSpaEnabled:
    def test_dashboard_serves_shell_and_primes_csrf(self, spa_on, authenticated_client):
        client, _user = authenticated_client(email="mc-spa-dashboard@example.com")
        resp = client.get(DASHBOARD_URL)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content
        assert "csrftoken" in resp.cookies

    def test_agents_page_serves_shell(self, spa_on, authenticated_client):
        client, _user = authenticated_client(email="mc-spa-agents@example.com")
        resp = client.get(AGENTS_URL)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_ngfw_detail_deep_link_serves_shell(self, spa_on, authenticated_client):
        client, _user = authenticated_client(email="mc-spa-ngfw@example.com")
        # Client-routed even for an id that does not exist server-side.
        resp = client.get("/mission-control/ngfw/00000000-0000-0000-0000-000000000000/")
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_client_router_catchall_serves_shell(self, spa_on, authenticated_client):
        client, _user = authenticated_client(email="mc-spa-catchall@example.com")
        resp = client.get("/mission-control/deep/client/route/")
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_anonymous_redirects_to_login(self, spa_on):
        resp = Client().get(DASHBOARD_URL)
        assert resp.status_code == 302

    def test_page_post_is_405(self, spa_on, authenticated_client):
        client, _user = authenticated_client(email="mc-spa-post@example.com")
        resp = client.post(AGENTS_URL, {})
        assert resp.status_code == 405


class TestSpaDisabled:
    def test_dashboard_serves_django_page_not_shell(self, spa_off, authenticated_client):
        client, _user = authenticated_client(email="mc-legacy-dashboard@example.com")
        resp = client.get(DASHBOARD_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content

    def test_client_router_catchall_404s(self, spa_off, authenticated_client):
        client, _user = authenticated_client(email="mc-legacy-catchall@example.com")
        resp = client.get("/mission-control/deep/client/route/")
        assert resp.status_code == 404


class TestSpaRequiresBothFlags:
    def test_platform_flag_alone_does_not_enable_mission_control_spa(self, authenticated_client, settings):
        settings.PLATFORM_SPA_ENABLED = True
        settings.MISSION_CONTROL_SPA_ENABLED = False
        client, _user = authenticated_client(email="mc-platform-only@example.com")
        resp = client.get(DASHBOARD_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content

    def test_mission_control_flag_alone_does_not_enable_without_platform_flag(self, authenticated_client, settings):
        settings.PLATFORM_SPA_ENABLED = False
        settings.MISSION_CONTROL_SPA_ENABLED = True
        client, _user = authenticated_client(email="mc-flag-only@example.com")
        resp = client.get(DASHBOARD_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content


class TestCatchAllExcludesRemovedLegacySurfaces:
    """The client-router catch-all must not resurrect the removed legacy
    experiments script surfaces (issue #1195); see
    ``tests/cms/test_experiments_removed.py::test_legacy_script_surfaces_are_not_routed``,
    which asserts these paths are unroutable (``Resolver404``) regardless of
    the SPA flags."""

    def test_removed_files_path_is_unresolvable_when_spa_enabled(self, spa_on):
        with pytest.raises(Resolver404):
            resolve("/mission-control/files/")

    def test_removed_api_scripts_path_is_unresolvable_when_spa_enabled(self, spa_on):
        with pytest.raises(Resolver404):
            resolve("/mission-control/api/scripts/")

    def test_removed_files_path_is_unresolvable_when_spa_disabled(self, spa_off):
        with pytest.raises(Resolver404):
            resolve("/mission-control/files/")


def test_legacy_delete_action_stays_django():
    """The remaining legacy POST-action path keeps serving its real Django view
    regardless of the SPA flags (never wrapped by ``_page``)."""
    assert resolve("/mission-control/agents/5/delete/").func is views.delete_agent


def test_legacy_json_api_routes_are_retired():
    """The legacy ``/mission-control/api/*`` JSON API was retired (#1328); the SPA
    and all callers use the canonical ``/api/v1/mission-control/`` DRF routes. The
    paths are unroutable at the URLconf level (excluded from the client-router
    catch-all), not merely 404-at-runtime."""
    for legacy_path in (
        "/mission-control/api/range/",
        "/mission-control/api/range/launch/",
        "/mission-control/api/agents/",
        "/mission-control/api/scenarios/",
        "/mission-control/api/upload/initiate/",
        "/mission-control/api/guacamole/rdp-url/",
        "/mission-control/api/ngfw/",
        "/mission-control/api/ngfw/list/",
        "/mission-control/api/credentials/",
    ):
        with pytest.raises(Resolver404):
            resolve(legacy_path)
