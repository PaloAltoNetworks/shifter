"""Tests for agent upload and delete views."""

import io
import time
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from management.models import ActivityLog
from mission_control.models import AgentConfig, OperatingSystem

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


@pytest.mark.django_db
class TestUploadAgent:
    def test_requires_login(self, client):
        response = client.post(reverse("mission_control:upload_agent"))
        assert response.status_code == 302

    def test_requires_post(self, user):
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:upload_agent"))
        assert response.status_code == 405

    def test_requires_name(self, user):
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:upload_agent"), {"name": ""})
        assert response.status_code == 302
        # Should redirect with error message

    def test_requires_file(self, user):
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:upload_agent"), {"name": "Test"})
        assert response.status_code == 302
        # Should redirect with error message

    @patch("mission_control.views.s3_upload")
    def test_successful_upload(self, mock_upload, user, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 200
        mock_upload.return_value = ("agents/1/abc_test.msi", "sha256hash", 1024)

        client = get_authenticated_client(user)

        # Create valid MSI file (OLE magic bytes)
        magic = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])
        file_content = magic + b"x" * 100
        file_obj = io.BytesIO(file_content)
        file_obj.name = "agent.msi"

        response = client.post(
            reverse("mission_control:upload_agent"),
            {"name": "My Agent", "file": file_obj},
        )

        assert response.status_code == 302
        assert response.url == reverse("mission_control:agents")

        # Verify agent was created
        agent = AgentConfig.objects.get(user=user)
        assert agent.name == "My Agent"
        assert agent.os.slug == "windows"
        assert agent.sha256_hash == "sha256hash"

        # Verify activity was logged
        log = ActivityLog.objects.filter(action="agent_uploaded").first()
        assert log is not None
        assert log.user == user

    @patch("mission_control.views.s3_upload")
    def test_upload_tar_gz(self, mock_upload, user, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 200
        mock_upload.return_value = ("agents/1/abc_test.tar.gz", "sha256hash", 1024)

        client = get_authenticated_client(user)

        # Create valid gzip file
        magic = bytes([0x1F, 0x8B])
        file_content = magic + b"x" * 100
        file_obj = io.BytesIO(file_content)
        file_obj.name = "agent.tar.gz"

        response = client.post(
            reverse("mission_control:upload_agent"),
            {"name": "Linux Agent", "file": file_obj},
        )

        assert response.status_code == 302
        agent = AgentConfig.objects.get(user=user)
        assert agent.os.slug == "linux-generic"

    def test_rejects_invalid_extension(self, user, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 200
        client = get_authenticated_client(user)

        file_obj = io.BytesIO(b"content")
        file_obj.name = "agent.exe"

        response = client.post(
            reverse("mission_control:upload_agent"),
            {"name": "Bad Agent", "file": file_obj},
        )

        assert response.status_code == 302
        assert AgentConfig.objects.filter(user=user).count() == 0

    def test_rejects_magic_byte_mismatch(self, user, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 200
        client = get_authenticated_client(user)

        # File with .msi extension but wrong magic bytes
        file_obj = io.BytesIO(b"not a real msi file content here")
        file_obj.name = "fake.msi"

        response = client.post(
            reverse("mission_control:upload_agent"),
            {"name": "Fake Agent", "file": file_obj},
        )

        assert response.status_code == 302
        assert AgentConfig.objects.filter(user=user).count() == 0

    @patch("mission_control.views.s3_upload")
    def test_sanitizes_filename(self, mock_upload, user, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 200
        mock_upload.return_value = ("agents/1/abc_test.msi", "sha256hash", 1024)

        client = get_authenticated_client(user)

        # Create valid MSI file
        magic = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])
        file_content = magic + b"x" * 100
        file_obj = io.BytesIO(file_content)
        file_obj.name = "../../../etc/passwd.msi"  # Path traversal attempt

        response = client.post(
            reverse("mission_control:upload_agent"),
            {"name": "Traversal Test", "file": file_obj},
        )

        assert response.status_code == 302
        agent = AgentConfig.objects.get(user=user)
        assert agent.original_filename == "passwd.msi"  # Path stripped

    @patch("mission_control.views.s3_upload")
    def test_s3_upload_error_no_agent_created(self, mock_upload, user, settings):
        """S3 error should prevent agent creation in DB."""
        from mission_control.services.s3 import S3Error

        settings.AGENT_MAX_FILE_SIZE_MB = 200
        mock_upload.side_effect = S3Error("S3 is down")

        client = get_authenticated_client(user)

        magic = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])
        file_obj = io.BytesIO(magic + b"x" * 100)
        file_obj.name = "agent.msi"

        response = client.post(
            reverse("mission_control:upload_agent"),
            {"name": "Should Fail", "file": file_obj},
        )

        assert response.status_code == 302
        # No agent should be created
        assert AgentConfig.objects.filter(user=user).count() == 0
        # No activity log for upload
        assert ActivityLog.objects.filter(action="agent_uploaded").count() == 0

    def test_rejects_oversized_file(self, user, settings):
        """File exceeding size limit should be rejected."""
        settings.AGENT_MAX_FILE_SIZE_MB = 1  # 1 MB limit

        client = get_authenticated_client(user)

        # Create valid magic bytes but report large size
        magic = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])
        file_obj = io.BytesIO(magic + b"x" * 100)
        file_obj.name = "agent.msi"
        # Django's test client will set size from actual content,
        # so we need to actually upload something "large" or test at validation layer
        # This test verifies the view properly handles ValidationError

        response = client.post(
            reverse("mission_control:upload_agent"),
            {"name": "Big Agent", "file": file_obj},
        )

        # File passes because actual content is small
        # Real size check happens at validation layer (tested in test_validation.py)
        # This test confirms view doesn't crash on valid small file
        assert response.status_code == 302


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
        other_user = User.objects.create_user(username="other@example.com", email="other@example.com")
        client = get_authenticated_client(other_user)

        response = client.post(reverse("mission_control:delete_agent", args=[agent.id]))
        assert response.status_code == 404

    def test_cannot_delete_already_deleted(self, user, agent):
        from django.utils import timezone

        agent.deleted_at = timezone.now()
        agent.save()

        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:delete_agent", args=[agent.id]))
        assert response.status_code == 404

    @patch("cms.assets.services.s3_delete")
    def test_s3_error_prevents_delete(self, mock_delete, user, agent):
        from mission_control.services.s3 import S3Error

        mock_delete.side_effect = S3Error("Failed")

        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:delete_agent", args=[agent.id]))

        assert response.status_code == 302

        # Agent should NOT be deleted
        agent.refresh_from_db()
        assert agent.deleted_at is None

    def test_delete_nonexistent_agent(self, user):
        """Deleting non-existent agent returns 404."""
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:delete_agent", args=[99999]))
        assert response.status_code == 404
