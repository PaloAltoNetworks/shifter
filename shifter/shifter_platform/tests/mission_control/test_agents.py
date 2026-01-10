"""Tests for agent upload and delete views."""

import time
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from cms.models import AgentConfig, OperatingSystem
from management.models import ActivityLog

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


@pytest.fixture
def windows_os(db):
    return OperatingSystem.objects.get(slug="windows")


@pytest.fixture
def linux_os(db):
    return OperatingSystem.objects.get(slug="linux-generic")


@pytest.fixture
def agent(db, user, windows_os):
    return AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Test Agent",
        s3_key="agents/1/abc123_test.msi",
        original_filename="test.msi",
        file_size_bytes=1024 * 1024,
        sha256_hash="abc123",
    )


@pytest.mark.django_db
class TestAgentsView:
    def test_requires_login(self, client):
        response = client.get(reverse("mission_control:agents"))
        assert response.status_code == 302
        assert "/oidc/authenticate/" in response.url or "login" in response.url.lower()

    def test_shows_user_agents(self, user, agent):
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:agents"))
        assert response.status_code == 200
        assert "Test Agent" in response.content.decode()

    def test_hides_deleted_agents(self, user, agent):
        from django.utils import timezone

        agent.deleted_at = timezone.now()
        agent.save()

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:agents"))
        assert response.status_code == 200
        assert "Test Agent" not in response.content.decode()

    def test_shows_empty_state(self, user):
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:agents"))
        assert response.status_code == 200
        assert "No agents uploaded yet" in response.content.decode()


# Note: TestUploadAgent class removed - legacy form-based upload replaced by presigned URL flow
# See tests/mission_control/test_presigned_upload.py for upload tests


@pytest.mark.django_db
class TestDeleteAgent:
    def test_requires_login(self, client, agent):
        response = client.post(reverse("mission_control:delete_agent", args=[agent.id]))
        assert response.status_code == 302

    def test_requires_post(self, user, agent):
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:delete_agent", args=[agent.id]))
        assert response.status_code == 405

    @patch("cms.assets.services.s3_delete")
    def test_successful_delete(self, mock_delete, user, agent):
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:delete_agent", args=[agent.id]))

        assert response.status_code == 302
        assert response.url == reverse("mission_control:agents")

        # Verify soft delete
        agent.refresh_from_db()
        assert agent.deleted_at is not None

        # Verify S3 delete was called
        mock_delete.assert_called_once_with(agent.s3_key)

        # Verify activity was logged
        log = ActivityLog.objects.filter(action="agent_deleted").first()
        assert log is not None

    def test_cannot_delete_other_users_agent(self, user, agent):
        """Deleting another user's agent shows error and redirects."""
        other_user = User.objects.create_user(username="other@example.com", email="other@example.com")
        client = get_authenticated_client(other_user)

        response = client.post(reverse("mission_control:delete_agent", args=[agent.id]))
        # CMS raises CMSError, view catches it and redirects with error message
        assert response.status_code == 302
        assert response.url == reverse("mission_control:agents")

        # Agent should NOT be deleted
        agent.refresh_from_db()
        assert agent.deleted_at is None

    def test_cannot_delete_already_deleted(self, user, agent):
        """Deleting already-deleted agent shows error and redirects."""
        from django.utils import timezone

        agent.deleted_at = timezone.now()
        agent.save()

        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:delete_agent", args=[agent.id]))
        # CMS raises CMSError, view catches it and redirects with error message
        assert response.status_code == 302
        assert response.url == reverse("mission_control:agents")

    @patch("cms.assets.services.s3_delete")
    def test_s3_error_prevents_delete(self, mock_delete, user, agent):
        """S3 error during delete shows error and redirects."""
        from cms.assets.services import AssetError

        mock_delete.side_effect = AssetError("Failed to delete from S3")

        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:delete_agent", args=[agent.id]))

        assert response.status_code == 302

        # Agent should NOT be deleted
        agent.refresh_from_db()
        assert agent.deleted_at is None

    def test_delete_nonexistent_agent(self, user):
        """Deleting non-existent agent shows error and redirects."""
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:delete_agent", args=[99999]))
        # CMS raises CMSError, view catches it and redirects with error message
        assert response.status_code == 302
        assert response.url == reverse("mission_control:agents")
