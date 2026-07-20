"""Tests for the flag-gated Scenario Editor SPA host view + routing (#1371).

Mirrors ``tests/mission_control/test_spa_host.py``. The Scenario Editor carve-out
requires BOTH ``PLATFORM_SPA_ENABLED`` and ``SCENARIO_EDITOR_SPA_ENABLED`` (the
per-surface extension of the platform flag pattern); either flag alone must not
enable the SPA shell for Scenario Editor pages. Legacy POST action URLs and the
legacy validate-yaml / export endpoints stay Django-handled regardless of the
flag state — the SPA uses the canonical ``/api/v1/cms/`` routes exclusively.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import resolve

from cms.scenario_editor import views

pytestmark = pytest.mark.django_db

LIST_URL = "/scenario-editor/"
CREATE_URL = "/scenario-editor/create/"


@pytest.fixture
def spa_on(settings):
    settings.PLATFORM_SPA_ENABLED = True
    settings.SCENARIO_EDITOR_SPA_ENABLED = True


@pytest.fixture
def spa_off(settings):
    settings.PLATFORM_SPA_ENABLED = False
    settings.SCENARIO_EDITOR_SPA_ENABLED = False


class TestSpaEnabled:
    def test_list_serves_shell_and_primes_csrf(self, spa_on, threat_research_client):
        resp = threat_research_client.get(LIST_URL)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content
        assert "csrftoken" in resp.cookies

    def test_create_page_serves_shell(self, spa_on, threat_research_client):
        resp = threat_research_client.get(CREATE_URL)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_detail_deep_link_serves_shell(self, spa_on, threat_research_client):
        # Client-routed even for an id that does not exist server-side.
        resp = threat_research_client.get("/scenario-editor/does-not-exist/")
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_shell_served_without_threat_research_access(self, spa_on, regular_client):
        # The shell host is thin-auth (authenticated only); per-surface access
        # is enforced by the /api/v1/ endpoints the SPA calls, which render the
        # access-denied state. Any authenticated user gets the shell markup.
        resp = regular_client.get(LIST_URL)
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_client_router_catchall_serves_shell(self, spa_on, threat_research_client):
        resp = threat_research_client.get("/scenario-editor/deep/client/route/")
        assert resp.status_code == 200
        assert b'id="root"' in resp.content

    def test_anonymous_redirects_to_login(self, spa_on):
        resp = Client().get(LIST_URL)
        assert resp.status_code == 302

    def test_form_post_falls_through_to_django_when_enabled(self, spa_on, threat_research_client):
        # The create/edit/YAML page views own BOTH GET rendering and POST
        # submission on the same URL. The shell (require_safe) must not take over
        # unsafe methods, or the legacy form POST would 405 and break old-tab /
        # rollback. A POST must reach the Django view, not the shell.
        resp = threat_research_client.post(CREATE_URL, {})
        assert resp.status_code != 405
        assert b'id="root"' not in resp.content


class TestSpaDisabled:
    def test_list_serves_django_page_not_shell(self, spa_off, threat_research_client):
        resp = threat_research_client.get(LIST_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content

    def test_client_router_catchall_404s(self, spa_off, threat_research_client):
        resp = threat_research_client.get("/scenario-editor/deep/client/route/")
        assert resp.status_code == 404


class TestSpaRequiresBothFlags:
    def test_platform_flag_alone_does_not_enable_scenario_editor_spa(self, threat_research_client, settings):
        settings.PLATFORM_SPA_ENABLED = True
        settings.SCENARIO_EDITOR_SPA_ENABLED = False
        resp = threat_research_client.get(LIST_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content

    def test_scenario_editor_flag_alone_does_not_enable_without_platform_flag(self, threat_research_client, settings):
        settings.PLATFORM_SPA_ENABLED = False
        settings.SCENARIO_EDITOR_SPA_ENABLED = True
        resp = threat_research_client.get(LIST_URL)
        assert resp.status_code == 200
        assert b'id="root"' not in resp.content


def test_legacy_action_and_validate_routes_stay_django():
    """The SPA uses the canonical /api/v1/cms/ routes exclusively; these legacy
    Django POST-action, validate-yaml, and export paths keep serving their real
    views regardless of the SPA flags (never wrapped by ``_page``)."""
    assert resolve("/scenario-editor/validate-yaml/").func is views.validate_yaml_view
    assert resolve("/scenario-editor/my-lab/delete/").func is views.scenario_delete_view
    assert resolve("/scenario-editor/my-lab/clone/").func is views.scenario_clone_view
    assert resolve("/scenario-editor/my-lab/toggle-enabled/").func is views.scenario_toggle_enabled
    assert resolve("/scenario-editor/my-lab/toggle-staff-only/").func is views.scenario_toggle_staff_only
    assert resolve("/scenario-editor/my-lab/export/").func is views.scenario_export_view
