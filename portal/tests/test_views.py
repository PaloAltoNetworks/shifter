"""Tests for page-rendering views (dashboard, history, settings, help)."""

import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()


def get_authenticated_client(user):
    """Create a client with OIDC session data set to avoid SessionRefresh redirects."""
    client = Client()
    client.force_login(user)
    session = client.session
    session["oidc_id_token_expiration"] = time.time() + 3600
    session.save()
    return client


@pytest.fixture
def user(db):
    return User.objects.create_user(username="test@example.com", email="test@example.com")


# -----------------------------------------------------------------------------
# Dashboard View Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestDashboardView:
    def test_requires_login(self, client, db):
        response = client.get(reverse("mission_control:dashboard"))
        assert response.status_code == 302
        assert "/oidc/authenticate/" in response.url or "login" in response.url.lower()

    def test_requires_get(self, user, db):
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:dashboard"))
        assert response.status_code == 405

    def test_renders_dashboard(self, user, db):
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:dashboard"))

        assert response.status_code == 200
        assert "dashboard" in response.content.decode().lower()
        # Check context
        assert response.context["page_title"] == "Dashboard"
        assert response.context["active_nav"] == "dashboard"


# -----------------------------------------------------------------------------
# History View Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestHistoryView:
    def test_requires_login(self, client):
        response = client.get(reverse("mission_control:history"))
        assert response.status_code == 302

    def test_requires_get(self, user):
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:history"))
        assert response.status_code == 405

    def test_renders_history(self, user):
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:history"))

        assert response.status_code == 200
        assert response.context["page_title"] == "History"
        assert response.context["active_nav"] == "history"


# -----------------------------------------------------------------------------
# Settings View Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestSettingsView:
    def test_requires_login(self, client):
        response = client.get(reverse("mission_control:settings"))
        assert response.status_code == 302

    def test_requires_get(self, user):
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:settings"))
        assert response.status_code == 405

    def test_renders_settings(self, user):
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:settings"))

        assert response.status_code == 200
        assert response.context["page_title"] == "Settings"
        assert response.context["active_nav"] == "settings"


# -----------------------------------------------------------------------------
# Help View Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestHelpView:
    def test_requires_login(self, client):
        response = client.get(reverse("mission_control:help"))
        assert response.status_code == 302

    def test_requires_get(self, user):
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:help"))
        assert response.status_code == 405

    def test_renders_help(self, user, settings):
        settings.SHIFTER_SUPPORT_EMAIL = "support@test.example.com"

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:help"))

        assert response.status_code == 200
        assert response.context["page_title"] == "Help"
        assert response.context["active_nav"] == "help"
        assert response.context["support_email"] == "support@test.example.com"


# -----------------------------------------------------------------------------
# Helper Function Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetUserStorageUsed:
    def test_returns_zero_for_no_agents(self, user):
        from mission_control.views import _get_user_storage_used

        assert _get_user_storage_used(user) == 0

    def test_sums_active_agent_sizes(self, user):
        from mission_control.models import AgentConfig, OperatingSystem
        from mission_control.views import _get_user_storage_used

        windows_os = OperatingSystem.objects.get(slug="windows")

        # Create two agents
        AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Agent 1",
            s3_key="agents/1/a.msi",
            original_filename="a.msi",
            file_size_bytes=1000,
            sha256_hash="aaa",
        )
        AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Agent 2",
            s3_key="agents/1/b.msi",
            original_filename="b.msi",
            file_size_bytes=2000,
            sha256_hash="bbb",
        )

        assert _get_user_storage_used(user) == 3000

    def test_excludes_deleted_agents(self, user):
        from django.utils import timezone

        from mission_control.models import AgentConfig, OperatingSystem
        from mission_control.views import _get_user_storage_used

        windows_os = OperatingSystem.objects.get(slug="windows")

        # Create active agent
        AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Active",
            s3_key="agents/1/active.msi",
            original_filename="active.msi",
            file_size_bytes=1000,
            sha256_hash="active",
        )
        # Create deleted agent
        AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Deleted",
            s3_key="agents/1/deleted.msi",
            original_filename="deleted.msi",
            file_size_bytes=5000,
            sha256_hash="deleted",
            deleted_at=timezone.now(),
        )

        # Should only count active agent
        assert _get_user_storage_used(user) == 1000


@pytest.mark.django_db
class TestUploadLock:
    def test_check_upload_in_progress_false_by_default(self, user):
        from mission_control.views import _check_upload_in_progress

        client = get_authenticated_client(user)
        # Access the request through a view to get session
        response = client.get(reverse("mission_control:dashboard"))
        assert response.status_code == 200

        # Create a mock request with the session
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.session = client.session

        assert _check_upload_in_progress(request) is False

    def test_upload_lock_expires(self, user, settings):
        from mission_control.views import (
            UPLOAD_LOCK_TIMEOUT,
            _check_upload_in_progress,
        )

        client = get_authenticated_client(user)
        client.get(reverse("mission_control:dashboard"))

        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.session = client.session

        # Set upload in progress with old timestamp
        request.session["upload_lock"] = {"started_at": time.time() - UPLOAD_LOCK_TIMEOUT - 10}
        request.session.save()

        # Should return False because lock is expired
        assert _check_upload_in_progress(request) is False


@pytest.mark.django_db
class TestRangeToJson:
    def test_serializes_range_correctly(self, user):
        from django.utils import timezone

        from mission_control.models import AgentConfig, OperatingSystem, Range
        from mission_control.views import _range_to_json

        windows_os = OperatingSystem.objects.get(slug="windows")
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test Agent",
            s3_key="agents/1/test.msi",
            original_filename="test.msi",
            file_size_bytes=1000,
            sha256_hash="test",
        )

        now = timezone.now()
        range_obj = Range.objects.create(
            user=user,
            agent=agent,
            status=Range.Status.READY,
            chat_url="http://chat.example.com/123",
            victim_ip="10.0.1.100",  # Should NOT appear in output
            ready_at=now,
        )

        result = _range_to_json(range_obj)

        assert result["id"] == range_obj.id
        assert result["status"] == "ready"
        assert result["agent_id"] == agent.id
        assert result["agent_name"] == "Test Agent"
        assert result["chat_url"] == "http://chat.example.com/123"
        assert result["error_message"] == ""  # Empty string, not None (model default)
        assert "victim_ip" not in result  # Security: internal detail not exposed

    def test_handles_null_agent(self, user):
        from mission_control.models import Range
        from mission_control.views import _range_to_json

        range_obj = Range.objects.create(
            user=user,
            agent=None,
            status=Range.Status.PROVISIONING,
        )

        result = _range_to_json(range_obj)

        assert result["agent_id"] is None
        assert result["agent_name"] is None
