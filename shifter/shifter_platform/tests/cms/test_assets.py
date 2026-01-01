"""Tests for cms.assets.services module."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms.assets.services import (
    AssetError,
    create_agent,
    delete_agent,
    get_storage_used,
)
from management.models import ActivityLog
from mission_control.models import AgentConfig, OperatingSystem

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def other_user(db):
    """Create another test user."""
    return User.objects.create_user(username="other@example.com", email="other@example.com")


@pytest.fixture
def windows_os(db):
    """Get the Windows operating system."""
    return OperatingSystem.objects.get(slug="windows")


@pytest.fixture
def linux_os(db):
    """Get the Linux (Debian/Ubuntu) operating system."""
    return OperatingSystem.objects.get(slug="linux-debian")


@pytest.fixture
def windows_agent(db, user, windows_os):
    """Create a Windows agent for the test user."""
    return AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Test Windows Agent",
        s3_key="agents/1/test.msi",
        original_filename="test.msi",
        file_size_bytes=1024,
        sha256_hash="abc123",
    )


@pytest.fixture
def linux_agent(db, user, linux_os):
    """Create a Linux agent for the test user."""
    return AgentConfig.objects.create(
        user=user,
        os=linux_os,
        name="Test Linux Agent",
        s3_key="agents/1/test.sh",
        original_filename="test.sh",
        file_size_bytes=2048,
        sha256_hash="def456",
    )


@pytest.fixture
def deleted_agent(db, user, windows_os):
    """Create a soft-deleted agent."""
    return AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Deleted Agent",
        s3_key="agents/1/deleted.msi",
        original_filename="deleted.msi",
        file_size_bytes=4096,
        sha256_hash="deleted123",
        deleted_at=timezone.now() - timedelta(days=1),
    )


# -----------------------------------------------------------------------------
# Tests for get_storage_used()
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetStorageUsed:
    """Tests for get_storage_used function."""

    def test_returns_zero_for_no_agents(self, user):
        """Should return 0 when user has no agents."""
        result = get_storage_used(user)
        assert result == 0

    def test_returns_zero_for_user_with_no_agents_but_others_have(self, user, other_user, windows_os):
        """Should return 0 for user even when other users have agents."""
        AgentConfig.objects.create(
            user=other_user,
            os=windows_os,
            name="Other Agent",
            s3_key="agents/2/other.msi",
            original_filename="other.msi",
            file_size_bytes=5000,
            sha256_hash="other123",
        )

        result = get_storage_used(user)
        assert result == 0

    def test_sums_active_agent_sizes(self, user, windows_agent, linux_agent):
        """Should return sum of all active agent sizes."""
        # windows_agent: 1024 bytes, linux_agent: 2048 bytes
        result = get_storage_used(user)
        assert result == 1024 + 2048

    def test_excludes_deleted_agents(self, user, windows_agent, deleted_agent):
        """Should not include deleted agents in the sum."""
        # windows_agent: 1024 bytes, deleted_agent: 4096 bytes (should be excluded)
        result = get_storage_used(user)
        assert result == 1024

    def test_only_counts_own_agents(self, user, other_user, windows_agent, windows_os):
        """Should only count agents belonging to the specified user."""
        # Create agent for other user
        AgentConfig.objects.create(
            user=other_user,
            os=windows_os,
            name="Other Agent",
            s3_key="agents/2/other.msi",
            original_filename="other.msi",
            file_size_bytes=8192,
            sha256_hash="other123",
        )

        result = get_storage_used(user)
        assert result == 1024  # Only windows_agent

    def test_returns_integer(self, user, windows_agent):
        """Should always return an integer."""
        result = get_storage_used(user)
        assert isinstance(result, int)


# -----------------------------------------------------------------------------
# Tests for create_agent()
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateAgent:
    """Tests for create_agent function."""

    def test_creates_agent_record(self, user, windows_os):
        """Should create AgentConfig record with correct fields."""
        agent = create_agent(
            user=user,
            name="New Agent",
            s3_key="agents/1/new.msi",
            filename="new.msi",
            os_slug="windows",
            file_size=2048,
            sha256="newhash123",
        )

        assert agent.id is not None
        assert agent.user == user
        assert agent.name == "New Agent"
        assert agent.s3_key == "agents/1/new.msi"
        assert agent.original_filename == "new.msi"
        assert agent.os == windows_os
        assert agent.file_size_bytes == 2048
        assert agent.sha256_hash == "newhash123"
        assert agent.deleted_at is None

    def test_creates_agent_record_with_linux_os(self, user, linux_os):
        """Should correctly look up Linux OS."""
        agent = create_agent(
            user=user,
            name="Linux Agent",
            s3_key="agents/1/linux.sh",
            filename="linux.sh",
            os_slug="linux-debian",
            file_size=1024,
            sha256="linuxhash",
        )

        assert agent.os == linux_os

    def test_logs_activity(self, user):
        """Should create an activity log entry."""
        agent = create_agent(
            user=user,
            name="Logged Agent",
            s3_key="agents/1/logged.msi",
            filename="logged.msi",
            os_slug="windows",
            file_size=1024,
            sha256="loggedhash",
        )

        log_entry = ActivityLog.objects.filter(
            user=user,
            action="agent_uploaded",
        ).first()
        assert log_entry is not None
        assert log_entry.metadata["agent_id"] == agent.id
        assert log_entry.metadata["agent_name"] == "Logged Agent"
        assert log_entry.metadata["filename"] == "logged.msi"

    def test_logs_upload_method_when_provided(self, user):
        """Should include upload_method in log when provided."""
        create_agent(
            user=user,
            name="Presigned Agent",
            s3_key="agents/1/presigned.msi",
            filename="presigned.msi",
            os_slug="windows",
            file_size=1024,
            sha256="presignedhash",
            upload_method="presigned",
        )

        log_entry = ActivityLog.objects.filter(
            user=user,
            action="agent_uploaded",
        ).first()
        assert log_entry.metadata["upload_method"] == "presigned"

    def test_raises_for_invalid_os_slug(self, user):
        """Should raise AssetError for invalid OS slug."""
        with pytest.raises(AssetError) as exc_info:
            create_agent(
                user=user,
                name="Invalid OS Agent",
                s3_key="agents/1/invalid.msi",
                filename="invalid.msi",
                os_slug="nonexistent-os",
                file_size=1024,
                sha256="invalidhash",
            )

        assert "not found" in str(exc_info.value).lower()

    def test_returns_agent_object(self, user):
        """Should return the created AgentConfig object."""
        result = create_agent(
            user=user,
            name="Return Test",
            s3_key="agents/1/return.msi",
            filename="return.msi",
            os_slug="windows",
            file_size=1024,
            sha256="returnhash",
        )

        assert isinstance(result, AgentConfig)
        assert result.pk is not None


# -----------------------------------------------------------------------------
# Tests for delete_agent()
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeleteAgent:
    """Tests for delete_agent function."""

    @patch("cms.assets.services.s3_delete")
    def test_soft_deletes_agent(self, mock_s3_delete, windows_agent):
        """Should set deleted_at timestamp on agent."""
        mock_s3_delete.return_value = None
        assert windows_agent.deleted_at is None

        delete_agent(windows_agent)

        windows_agent.refresh_from_db()
        assert windows_agent.deleted_at is not None

    @patch("cms.assets.services.s3_delete")
    def test_agent_still_exists_after_delete(self, mock_s3_delete, windows_agent):
        """Should not hard delete - record should still exist."""
        mock_s3_delete.return_value = None
        agent_id = windows_agent.id

        delete_agent(windows_agent)

        # Record should still exist
        assert AgentConfig.objects.filter(id=agent_id).exists()

    @patch("cms.assets.services.s3_delete")
    def test_calls_s3_delete_with_correct_key(self, mock_s3_delete, windows_agent):
        """Should call S3 delete with the agent's s3_key."""
        mock_s3_delete.return_value = None

        delete_agent(windows_agent)

        mock_s3_delete.assert_called_once_with(windows_agent.s3_key)

    @patch("cms.assets.services.s3_delete")
    def test_logs_activity(self, mock_s3_delete, user, windows_agent):
        """Should create an activity log entry."""
        mock_s3_delete.return_value = None

        delete_agent(windows_agent)

        log_entry = ActivityLog.objects.filter(
            user=user,
            action="agent_deleted",
        ).first()
        assert log_entry is not None
        assert log_entry.metadata["agent_id"] == windows_agent.id
        assert log_entry.metadata["agent_name"] == windows_agent.name

    @patch("cms.assets.services.s3_delete")
    def test_raises_if_s3_delete_fails(self, mock_s3_delete, windows_agent):
        """Should raise AssetError if S3 delete fails."""
        from mission_control.services.s3 import S3Error

        mock_s3_delete.side_effect = S3Error("Delete failed")

        with pytest.raises(AssetError) as exc_info:
            delete_agent(windows_agent)

        assert "delete" in str(exc_info.value).lower()

    @patch("cms.assets.services.s3_delete")
    def test_agent_not_deleted_if_s3_fails(self, mock_s3_delete, windows_agent):
        """Should not soft delete agent if S3 delete fails."""
        from mission_control.services.s3 import S3Error

        mock_s3_delete.side_effect = S3Error("Delete failed")

        with pytest.raises(AssetError):
            delete_agent(windows_agent)

        windows_agent.refresh_from_db()
        assert windows_agent.deleted_at is None

    @patch("cms.assets.services.s3_delete")
    def test_s3_delete_called_before_db_update(self, mock_s3_delete, windows_agent):
        """S3 delete should be called before database is updated."""
        call_order = []

        def track_s3_delete(*args):
            # Check deleted_at at time of S3 call
            windows_agent.refresh_from_db()
            call_order.append(("s3", windows_agent.deleted_at))

        mock_s3_delete.side_effect = track_s3_delete

        delete_agent(windows_agent)

        # S3 was called first, deleted_at was None at that point
        assert len(call_order) == 1
        assert call_order[0][1] is None


# -----------------------------------------------------------------------------
# Tests for AssetError
# -----------------------------------------------------------------------------


class TestAssetError:
    """Tests for the AssetError exception class."""

    def test_is_exception(self):
        """AssetError should be an Exception."""
        error = AssetError("Test error")
        assert isinstance(error, Exception)

    def test_message_accessible_via_str(self):
        """Error message should be accessible via str()."""
        error = AssetError("Test message")
        assert str(error) == "Test message"

    def test_can_be_raised_and_caught(self):
        """Should be raisable and catchable."""
        with pytest.raises(AssetError):
            raise AssetError("Test")
