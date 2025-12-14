"""Tests for presigned URL upload flow (initiate/complete/cancel)."""

import json
import time
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from mission_control.models import ActivityLog, AgentConfig, OperatingSystem
from mission_control.services.upload_token import generate_upload_token, verify_upload_token

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
def agent(db, user, windows_os):
    """Create an existing agent to test quota calculations."""
    return AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Existing Agent",
        s3_key="agents/1/existing_agent.msi",
        original_filename="existing.msi",
        file_size_bytes=1024 * 1024 * 1024,  # 1 GB
        sha256_hash="existing123",
    )


# -----------------------------------------------------------------------------
# Upload Token Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestUploadToken:
    def test_generate_and_verify_token(self, user):
        """Token can be generated and verified."""
        token = generate_upload_token(
            user_id=user.id,
            s3_key="agents/1/test.msi",
            name="Test Agent",
            filename="test.msi",
            os_slug="windows",
            file_size=1024,
        )

        payload = verify_upload_token(token, user.id)

        assert payload["s3_key"] == "agents/1/test.msi"
        assert payload["name"] == "Test Agent"
        assert payload["filename"] == "test.msi"
        assert payload["os_slug"] == "windows"
        assert payload["file_size"] == 1024

    def test_token_user_mismatch(self, user):
        """Token verification fails if user doesn't match."""
        token = generate_upload_token(
            user_id=user.id,
            s3_key="agents/1/test.msi",
            name="Test Agent",
            filename="test.msi",
            os_slug="windows",
            file_size=1024,
        )

        with pytest.raises(ValueError, match="user mismatch"):
            verify_upload_token(token, user.id + 999)

    def test_token_expired(self, user, settings):
        """Token verification fails after expiration."""
        settings.AGENT_UPLOAD_URL_EXPIRES = 1  # 1 second

        token = generate_upload_token(
            user_id=user.id,
            s3_key="agents/1/test.msi",
            name="Test Agent",
            filename="test.msi",
            os_slug="windows",
            file_size=1024,
        )

        time.sleep(2)  # Wait for expiration

        with pytest.raises(ValueError, match="expired"):
            verify_upload_token(token, user.id)

    def test_token_invalid_signature(self, user):
        """Token verification fails with tampered signature."""
        token = generate_upload_token(
            user_id=user.id,
            s3_key="agents/1/test.msi",
            name="Test Agent",
            filename="test.msi",
            os_slug="windows",
            file_size=1024,
        )

        # Tamper with signature
        parts = token.rsplit(".", 1)
        tampered = parts[0] + ".tampered_signature"

        with pytest.raises(ValueError, match="signature"):
            verify_upload_token(tampered, user.id)

    def test_token_invalid_format(self, user):
        """Token verification fails with malformed token."""
        with pytest.raises(ValueError, match="format"):
            verify_upload_token("not_a_valid_token", user.id)


# -----------------------------------------------------------------------------
# Initiate Upload Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestInitiateUpload:
    def test_requires_login(self, client):
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps({"name": "Test", "filename": "test.msi", "file_size": 1024}),
            content_type="application/json",
        )
        assert response.status_code == 302

    def test_requires_post(self, user):
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:initiate_upload"))
        assert response.status_code == 405

    @patch("mission_control.views.generate_presigned_upload_url")
    def test_successful_initiate(self, mock_presign, user, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 2048
        settings.AGENT_USER_STORAGE_QUOTA_MB = 5120
        mock_presign.return_value = ("https://s3.example.com/presigned", "agents/1/abc_test.msi")

        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps({"name": "Test Agent", "filename": "test.msi", "file_size": 1024 * 1024}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert "presigned_url" in data
        assert "upload_token" in data
        assert data["expected_os"] == "windows"

    def test_requires_name(self, user):
        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps({"filename": "test.msi", "file_size": 1024}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "name" in response.json()["error"].lower()

    def test_requires_filename(self, user):
        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps({"name": "Test", "file_size": 1024}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "filename" in response.json()["error"].lower()

    def test_requires_file_size(self, user):
        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps({"name": "Test", "filename": "test.msi"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "size" in response.json()["error"].lower()

    def test_rejects_oversized_file(self, user, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 100  # 100 MB limit

        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps(
                {
                    "name": "Big Agent",
                    "filename": "big.msi",
                    "file_size": 200 * 1024 * 1024,  # 200 MB
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "exceeds" in response.json()["error"].lower()

    def test_rejects_invalid_extension(self, user, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 2048

        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps(
                {
                    "name": "Bad Agent",
                    "filename": "agent.exe",
                    "file_size": 1024 * 1024,
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "not allowed" in response.json()["error"].lower()

    def test_rejects_over_quota(self, user, agent, settings):
        """User exceeding storage quota is rejected."""
        settings.AGENT_MAX_FILE_SIZE_MB = 2048
        settings.AGENT_USER_STORAGE_QUOTA_MB = 1024  # 1 GB quota, existing agent uses 1 GB

        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps(
                {
                    "name": "Over Quota",
                    "filename": "over.msi",
                    "file_size": 100 * 1024 * 1024,  # 100 MB - would exceed quota
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "quota" in response.json()["error"].lower()

    @patch("mission_control.views.generate_presigned_upload_url")
    def test_concurrent_upload_blocked(self, mock_presign, user, settings):
        """Only one upload at a time per user."""
        settings.AGENT_MAX_FILE_SIZE_MB = 2048
        settings.AGENT_USER_STORAGE_QUOTA_MB = 5120
        mock_presign.return_value = ("https://s3.example.com/presigned", "agents/1/abc_test.msi")

        client = get_authenticated_client(user)

        # First upload
        response1 = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps({"name": "First", "filename": "first.msi", "file_size": 1024}),
            content_type="application/json",
        )
        assert response1.status_code == 200

        # Second upload should be blocked
        response2 = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps({"name": "Second", "filename": "second.msi", "file_size": 1024}),
            content_type="application/json",
        )
        assert response2.status_code == 409
        assert "already in progress" in response2.json()["error"].lower()

    def test_sanitizes_filename(self, user, settings):
        """Path traversal in filename is stripped."""
        settings.AGENT_MAX_FILE_SIZE_MB = 2048
        settings.AGENT_USER_STORAGE_QUOTA_MB = 5120

        client = get_authenticated_client(user)

        with patch("mission_control.views.generate_presigned_upload_url") as mock_presign:
            mock_presign.return_value = ("https://s3.example.com/presigned", "agents/1/test.msi")

            response = client.post(
                reverse("mission_control:initiate_upload"),
                data=json.dumps(
                    {
                        "name": "Traversal Test",
                        "filename": "../../../etc/passwd.msi",
                        "file_size": 1024,
                    }
                ),
                content_type="application/json",
            )

            assert response.status_code == 200
            # Check that generate_presigned_upload_url was called with sanitized filename
            call_args = mock_presign.call_args
            assert call_args[1]["filename"] == "passwd.msi"


# -----------------------------------------------------------------------------
# Complete Upload Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCompleteUpload:
    def test_requires_login(self, client):
        response = client.post(
            reverse("mission_control:complete_upload"),
            data=json.dumps({"upload_token": "test"}),
            content_type="application/json",
        )
        assert response.status_code == 302

    def test_requires_post(self, user):
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:complete_upload"))
        assert response.status_code == 405

    @patch("mission_control.views.verify_s3_object_exists")
    @patch("mission_control.views.tag_s3_object")
    def test_successful_complete(self, mock_tag, mock_verify, user, settings):
        settings.AGENT_UPLOAD_URL_EXPIRES = 3600
        mock_verify.return_value = (1024 * 1024, "etag123")  # file_size, etag

        client = get_authenticated_client(user)

        # Generate valid token (s3_key must match user.id)
        token = generate_upload_token(
            user_id=user.id,
            s3_key=f"agents/{user.id}/test.msi",
            name="Test Agent",
            filename="test.msi",
            os_slug="windows",
            file_size=1024 * 1024,
        )

        response = client.post(
            reverse("mission_control:complete_upload"),
            data=json.dumps({"upload_token": token}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "agent_id" in data

        # Verify agent was created
        agent = AgentConfig.objects.get(id=data["agent_id"])
        assert agent.name == "Test Agent"
        assert agent.user == user
        assert agent.os.slug == "windows"

        # Verify activity logged
        log = ActivityLog.objects.filter(action="agent_uploaded", user=user).first()
        assert log is not None

    def test_rejects_invalid_token(self, user):
        client = get_authenticated_client(user)

        response = client.post(
            reverse("mission_control:complete_upload"),
            data=json.dumps({"upload_token": "invalid_token_here"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "token" in response.json()["error"].lower()

    def test_rejects_expired_token(self, user, settings):
        settings.AGENT_UPLOAD_URL_EXPIRES = 1  # 1 second

        token = generate_upload_token(
            user_id=user.id,
            s3_key="agents/1/test.msi",
            name="Test Agent",
            filename="test.msi",
            os_slug="windows",
            file_size=1024,
        )

        time.sleep(2)  # Wait for expiration

        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:complete_upload"),
            data=json.dumps({"upload_token": token}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "expired" in response.json()["error"].lower()

    @patch("mission_control.views.verify_s3_object_exists")
    def test_rejects_missing_s3_object(self, mock_verify, user, settings):
        from mission_control.services.s3 import S3Error

        settings.AGENT_UPLOAD_URL_EXPIRES = 3600
        mock_verify.side_effect = S3Error("Object not found")

        token = generate_upload_token(
            user_id=user.id,
            s3_key=f"agents/{user.id}/missing.msi",
            name="Missing Agent",
            filename="missing.msi",
            os_slug="windows",
            file_size=1024,
        )

        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:complete_upload"),
            data=json.dumps({"upload_token": token}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "not found" in response.json()["error"].lower()

    def test_token_user_mismatch(self, user, settings):
        """Token from different user is rejected."""
        settings.AGENT_UPLOAD_URL_EXPIRES = 3600
        other_user = User.objects.create_user(username="other@example.com", email="other@example.com")

        # Generate token for other user
        token = generate_upload_token(
            user_id=other_user.id,
            s3_key="agents/1/test.msi",
            name="Other User Agent",
            filename="test.msi",
            os_slug="windows",
            file_size=1024,
        )

        # Try to complete as original user
        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:complete_upload"),
            data=json.dumps({"upload_token": token}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "mismatch" in response.json()["error"].lower()

    def test_rejects_s3_key_for_different_user(self, user, settings):
        """Token with S3 key for different user is rejected (security fix)."""
        settings.AGENT_UPLOAD_URL_EXPIRES = 3600

        # Generate token with correct user_id but wrong S3 key prefix
        token = generate_upload_token(
            user_id=user.id,
            s3_key="agents/99999/stolen.msi",  # Different user's path
            name="Stolen Agent",
            filename="stolen.msi",
            os_slug="windows",
            file_size=1024,
        )

        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:complete_upload"),
            data=json.dumps({"upload_token": token}),
            content_type="application/json",
        )

        assert response.status_code == 403
        assert "invalid" in response.json()["error"].lower()


# -----------------------------------------------------------------------------
# Cancel Upload Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCancelUpload:
    def test_requires_login(self, client):
        response = client.post(
            reverse("mission_control:cancel_upload"),
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 302

    def test_requires_post(self, user):
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:cancel_upload"))
        assert response.status_code == 405

    def test_cancel_clears_session(self, user, settings):
        """Cancel clears the upload in progress flag."""
        settings.AGENT_MAX_FILE_SIZE_MB = 2048
        settings.AGENT_USER_STORAGE_QUOTA_MB = 5120

        client = get_authenticated_client(user)

        # First set up an upload in progress
        with patch("mission_control.views.generate_presigned_upload_url") as mock_presign:
            mock_presign.return_value = ("https://s3.example.com/presigned", "agents/1/test.msi")

            response = client.post(
                reverse("mission_control:initiate_upload"),
                data=json.dumps({"name": "Test", "filename": "test.msi", "file_size": 1024}),
                content_type="application/json",
            )
            assert response.status_code == 200
            token = response.json()["upload_token"]

        # Verify concurrent upload is blocked
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps({"name": "Second", "filename": "second.msi", "file_size": 1024}),
            content_type="application/json",
        )
        assert response.status_code == 409

        # Cancel the upload
        with patch("mission_control.views.s3_delete"):
            response = client.post(
                reverse("mission_control:cancel_upload"),
                data=json.dumps({"upload_token": token}),
                content_type="application/json",
            )
            assert response.status_code == 200

        # Now another upload should work
        with patch("mission_control.views.generate_presigned_upload_url") as mock_presign:
            mock_presign.return_value = ("https://s3.example.com/presigned2", "agents/1/new.msi")

            response = client.post(
                reverse("mission_control:initiate_upload"),
                data=json.dumps({"name": "New Upload", "filename": "new.msi", "file_size": 1024}),
                content_type="application/json",
            )
            assert response.status_code == 200

    @patch("mission_control.views.s3_delete")
    def test_cancel_with_token_deletes_s3_object(self, mock_delete, user, settings):
        """Cancel with valid token attempts S3 cleanup."""
        settings.AGENT_UPLOAD_URL_EXPIRES = 3600

        token = generate_upload_token(
            user_id=user.id,
            s3_key="agents/1/to_cancel.msi",
            name="Cancel Me",
            filename="cancel.msi",
            os_slug="windows",
            file_size=1024,
        )

        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:cancel_upload"),
            data=json.dumps({"upload_token": token}),
            content_type="application/json",
        )

        assert response.status_code == 200
        mock_delete.assert_called_once_with("agents/1/to_cancel.msi")

    def test_cancel_without_token_still_succeeds(self, user):
        """Cancel without token still clears session and succeeds."""
        client = get_authenticated_client(user)

        response = client.post(
            reverse("mission_control:cancel_upload"),
            data=json.dumps({}),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_cancel_with_invalid_token_still_succeeds(self, user):
        """Cancel with invalid token still clears session."""
        client = get_authenticated_client(user)

        response = client.post(
            reverse("mission_control:cancel_upload"),
            data=json.dumps({"upload_token": "invalid_token_here"}),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["success"] is True


# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestUploadIntegration:
    @patch("mission_control.views.generate_presigned_upload_url")
    @patch("mission_control.views.verify_s3_object_exists")
    @patch("mission_control.views.tag_s3_object")
    def test_full_upload_flow(self, mock_tag, mock_verify, mock_presign, user, settings):
        """Test complete upload flow: initiate -> complete."""
        settings.AGENT_MAX_FILE_SIZE_MB = 2048
        settings.AGENT_USER_STORAGE_QUOTA_MB = 5120
        settings.AGENT_UPLOAD_URL_EXPIRES = 3600

        mock_presign.return_value = ("https://s3.example.com/presigned", f"agents/{user.id}/flow_test.msi")
        mock_verify.return_value = (1024 * 1024, "etag_flow")

        client = get_authenticated_client(user)

        # Step 1: Initiate
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps(
                {
                    "name": "Flow Test Agent",
                    "filename": "flow_test.msi",
                    "file_size": 1024 * 1024,
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        init_data = response.json()
        assert "presigned_url" in init_data
        token = init_data["upload_token"]

        # Step 2: Complete (simulating browser PUT to S3 succeeded)
        response = client.post(
            reverse("mission_control:complete_upload"),
            data=json.dumps({"upload_token": token}),
            content_type="application/json",
        )

        assert response.status_code == 200
        complete_data = response.json()
        assert complete_data["success"] is True

        # Verify agent exists
        agent = AgentConfig.objects.get(id=complete_data["agent_id"])
        assert agent.name == "Flow Test Agent"
        assert agent.s3_key == f"agents/{user.id}/flow_test.msi"

    @patch("mission_control.views.generate_presigned_upload_url")
    @patch("mission_control.views.s3_delete")
    def test_initiate_cancel_flow(self, mock_delete, mock_presign, user, settings):
        """Test upload cancellation flow: initiate -> cancel."""
        settings.AGENT_MAX_FILE_SIZE_MB = 2048
        settings.AGENT_USER_STORAGE_QUOTA_MB = 5120
        settings.AGENT_UPLOAD_URL_EXPIRES = 3600

        mock_presign.return_value = ("https://s3.example.com/presigned", "agents/1/cancel_test.msi")

        client = get_authenticated_client(user)

        # Step 1: Initiate
        response = client.post(
            reverse("mission_control:initiate_upload"),
            data=json.dumps(
                {
                    "name": "Cancel Test",
                    "filename": "cancel_test.msi",
                    "file_size": 1024,
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        token = response.json()["upload_token"]

        # Step 2: Cancel
        response = client.post(
            reverse("mission_control:cancel_upload"),
            data=json.dumps({"upload_token": token}),
            content_type="application/json",
        )

        assert response.status_code == 200

        # Verify no agent was created
        assert AgentConfig.objects.filter(user=user).count() == 0

        # Verify S3 cleanup was attempted
        mock_delete.assert_called_once_with("agents/1/cancel_test.msi")
