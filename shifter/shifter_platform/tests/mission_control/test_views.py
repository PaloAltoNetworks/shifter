"""Tests for page-rendering views (dashboard, settings, help)."""

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
        from cms.assets.services import get_storage_used

        assert get_storage_used(user) == 0

    def test_sums_active_agent_sizes(self, user):
        from cms.assets.services import get_storage_used
        from cms.models import AgentConfig, OperatingSystem

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

        assert get_storage_used(user) == 3000

    def test_excludes_deleted_agents(self, user):
        from django.utils import timezone

        from cms.assets.services import get_storage_used
        from cms.models import AgentConfig, OperatingSystem

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
        assert get_storage_used(user) == 1000


@pytest.mark.django_db
class TestUploadLock:
    def test_check_upload_in_progress_false_by_default(self, user):
        from mission_control.upload_session import check_upload_in_progress

        client = get_authenticated_client(user)
        # Access the request through a view to get session
        response = client.get(reverse("mission_control:dashboard"))
        assert response.status_code == 200

        assert check_upload_in_progress(client.session) is False

    def test_upload_lock_expires(self, user, settings):
        from mission_control.upload_session import UPLOAD_LOCK_TIMEOUT, check_upload_in_progress

        client = get_authenticated_client(user)
        client.get(reverse("mission_control:dashboard"))

        # Set upload in progress with old timestamp
        client.session["upload_lock"] = {"started_at": time.time() - UPLOAD_LOCK_TIMEOUT - 10}
        client.session.save()

        # Should return False because lock is expired
        assert check_upload_in_progress(client.session) is False


# Note: TestRangeToJson was removed as engine.serialization.range_to_dict no longer exists.
# Ranges are now serialized via RangeContext.model_dump() directly in views.
