"""Behavior tests for the page-rendering views (dashboard, settings, help).

Drives the real URLs with the test client and asserts the rendered template,
response status, and template context instead of mocking ``render`` and
inspecting its call args. The storage helper is exercised against real agents.
"""

import time

import pytest
from django.test import Client, override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _template_names(response):
    return [t.name for t in response.templates if t.name]


class TestDashboardView:
    URL = reverse("mission_control:dashboard")

    def test_requires_login(self):
        response = Client().get(self.URL)
        assert response.status_code == 302

    def test_requires_get(self, authenticated_client):
        client, _ = authenticated_client(email="dash-post@example.com")
        assert client.post(self.URL).status_code == 405

    def test_renders_dashboard(self, authenticated_client):
        client, _ = authenticated_client(email="dash@example.com")
        response = client.get(self.URL)
        assert response.status_code == 200
        assert "mission_control/dashboard.html" in _template_names(response)
        assert response.context["page_title"] == "Ranges"
        assert response.context["active_nav"] == "ranges"


class TestSettingsView:
    URL = reverse("mission_control:settings")

    def test_requires_login(self):
        assert Client().get(self.URL).status_code == 302

    def test_requires_get(self, authenticated_client):
        client, _ = authenticated_client(email="set-post@example.com")
        assert client.post(self.URL).status_code == 405

    def test_renders_settings(self, authenticated_client):
        client, _ = authenticated_client(email="set@example.com")
        response = client.get(self.URL)
        assert response.status_code == 200
        assert "mission_control/settings.html" in _template_names(response)
        assert response.context["page_title"] == "Settings"
        assert response.context["active_nav"] == "settings"


class TestHelpView:
    URL = reverse("mission_control:help")

    def test_requires_login(self):
        assert Client().get(self.URL).status_code == 302

    def test_requires_get(self, authenticated_client):
        client, _ = authenticated_client(email="help-post@example.com")
        assert client.post(self.URL).status_code == 405

    @override_settings(SHIFTER_SUPPORT_EMAIL="support@test.example.com")
    def test_renders_help(self, authenticated_client):
        client, _ = authenticated_client(email="help@example.com")
        response = client.get(self.URL)
        assert response.status_code == 200
        assert "mission_control/help.html" in _template_names(response)
        assert response.context["page_title"] == "Help"
        assert response.context["active_nav"] == "help"
        assert response.context["support_email"] == "support@test.example.com"


class TestGetUserStorageUsed:
    def test_returns_zero_for_no_agents(self, authenticated_client):
        from cms.assets.services import get_storage_used

        _client, user = authenticated_client(email="storage0@example.com")
        assert get_storage_used(user) == 0

    def test_sums_active_agent_sizes(self, authenticated_client, make_agent):
        from cms.assets.services import get_storage_used

        _client, user = authenticated_client(email="storage-sum@example.com")
        make_agent(user, name="A", file_size_bytes=1000)
        make_agent(user, name="B", file_size_bytes=2000)
        assert get_storage_used(user) == 3000

    def test_excludes_deleted_agents(self, authenticated_client, make_agent):
        from django.utils import timezone

        from cms.assets.services import get_storage_used

        _client, user = authenticated_client(email="storage-del@example.com")
        make_agent(user, name="Active", file_size_bytes=1000)
        deleted = make_agent(user, name="Deleted", file_size_bytes=5000)
        deleted.deleted_at = timezone.now()
        deleted.save(update_fields=["deleted_at"])
        assert get_storage_used(user) == 1000


class TestUploadLock:
    def test_check_upload_in_progress_false_by_default(self):
        from mission_control.upload_session import check_upload_in_progress

        assert check_upload_in_progress({}) is False

    def test_upload_lock_expires(self):
        from mission_control.upload_session import UPLOAD_LOCK_TIMEOUT, check_upload_in_progress

        session = {"upload_lock": {"started_at": time.time() - UPLOAD_LOCK_TIMEOUT - 10}}
        assert check_upload_in_progress(session) is False
