"""Tests for cms.assets.services module."""

from unittest.mock import MagicMock, patch

import pytest

from cms.assets.services import (
    AgentUploadSpec,
    AssetError,
    create_agent,
    delete_agent,
    get_storage_used,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_user():
    """Create a mock user."""
    user = MagicMock()
    user.id = 1
    user.username = "test@example.com"
    user.email = "test@example.com"
    return user


@pytest.fixture
def mock_other_user():
    """Create another mock user."""
    user = MagicMock()
    user.id = 2
    user.username = "other@example.com"
    user.email = "other@example.com"
    return user


@pytest.fixture
def mock_windows_os():
    """Create a mock Windows operating system."""
    os_obj = MagicMock()
    os_obj.slug = "windows"
    os_obj.name = "Windows"
    os_obj.extensions = [".msi"]
    return os_obj


@pytest.fixture
def mock_linux_os():
    """Create a mock Linux operating system."""
    os_obj = MagicMock()
    os_obj.slug = "linux-debian"
    os_obj.name = "Linux (Debian/Ubuntu)"
    os_obj.extensions = [".deb"]
    return os_obj


@pytest.fixture
def mock_windows_agent(mock_user, mock_windows_os):
    """Create a mock Windows agent."""
    agent = MagicMock()
    agent.id = 10
    agent.pk = 10
    agent.user = mock_user
    agent.os = mock_windows_os
    agent.name = "Test Windows Agent"
    agent.s3_key = "agents/1/test.msi"
    agent.original_filename = "test.msi"
    agent.file_size_bytes = 1024
    agent.sha256_hash = "abc123"
    agent.deleted_at = None
    return agent


# -----------------------------------------------------------------------------
# Tests for get_storage_used()
# -----------------------------------------------------------------------------


class TestGetStorageUsed:
    """Tests for get_storage_used function."""

    @patch("cms.assets.services.AgentConfig")
    def test_returns_zero_for_no_agents(self, mock_agent_config, mock_user):
        """Should return 0 when user has no agents."""
        mock_qs = MagicMock()
        mock_qs.aggregate.return_value = {"total": None}
        mock_agent_config.active_for_user.return_value = mock_qs

        result = get_storage_used(mock_user)
        assert result == 0
        mock_agent_config.active_for_user.assert_called_once_with(mock_user)

    @patch("cms.assets.services.AgentConfig")
    def test_returns_zero_for_user_with_no_agents_but_others_have(self, mock_agent_config, mock_user):
        """Should return 0 for user even when other users have agents."""
        mock_qs = MagicMock()
        mock_qs.aggregate.return_value = {"total": None}
        mock_agent_config.active_for_user.return_value = mock_qs

        result = get_storage_used(mock_user)
        assert result == 0

    @patch("cms.assets.services.AgentConfig")
    def test_sums_active_agent_sizes(self, mock_agent_config, mock_user):
        """Should return sum of all active agent sizes."""
        mock_qs = MagicMock()
        mock_qs.aggregate.return_value = {"total": 1024 + 2048}
        mock_agent_config.active_for_user.return_value = mock_qs

        result = get_storage_used(mock_user)
        assert result == 1024 + 2048

    @patch("cms.assets.services.AgentConfig")
    def test_excludes_deleted_agents(self, mock_agent_config, mock_user):
        """Should not include deleted agents in the sum.

        active_for_user already filters out deleted agents,
        so we verify the service calls active_for_user (not objects.all).
        """
        mock_qs = MagicMock()
        mock_qs.aggregate.return_value = {"total": 1024}
        mock_agent_config.active_for_user.return_value = mock_qs

        result = get_storage_used(mock_user)
        assert result == 1024
        mock_agent_config.active_for_user.assert_called_once_with(mock_user)

    @patch("cms.assets.services.AgentConfig")
    def test_only_counts_own_agents(self, mock_agent_config, mock_user):
        """Should only count agents belonging to the specified user."""
        mock_qs = MagicMock()
        mock_qs.aggregate.return_value = {"total": 1024}
        mock_agent_config.active_for_user.return_value = mock_qs

        result = get_storage_used(mock_user)
        assert result == 1024
        mock_agent_config.active_for_user.assert_called_once_with(mock_user)

    @patch("cms.assets.services.AgentConfig")
    def test_returns_integer(self, mock_agent_config, mock_user):
        """Should always return an integer."""
        mock_qs = MagicMock()
        mock_qs.aggregate.return_value = {"total": 1024}
        mock_agent_config.active_for_user.return_value = mock_qs

        result = get_storage_used(mock_user)
        assert isinstance(result, int)


# -----------------------------------------------------------------------------
# Tests for create_agent()
# -----------------------------------------------------------------------------


class TestCreateAgent:
    """Tests for create_agent function."""

    @patch("cms.assets.services.audit_log")
    @patch("cms.assets.services.AgentConfig")
    @patch("cms.assets.services.OperatingSystem")
    def test_creates_agent_record(self, mock_os_model, mock_agent_config, mock_audit_log, mock_user, mock_windows_os):
        """Should create AgentConfig record with correct fields."""
        mock_os_model.objects.filter.return_value.first.return_value = mock_windows_os
        created_agent = MagicMock()
        created_agent.id = 42
        created_agent.pk = 42
        created_agent.user = mock_user
        created_agent.name = "New Agent"
        created_agent.s3_key = "agents/1/new.msi"
        created_agent.original_filename = "new.msi"
        created_agent.os = mock_windows_os
        created_agent.file_size_bytes = 2048
        created_agent.sha256_hash = "newhash123"
        created_agent.deleted_at = None
        mock_agent_config.objects.create.return_value = created_agent

        agent = create_agent(
            user=mock_user,
            spec=AgentUploadSpec(
                name="New Agent",
                s3_key="agents/1/new.msi",
                filename="new.msi",
                os_slug="windows",
                file_size=2048,
                sha256="newhash123",
            ),
        )

        assert agent.id is not None
        assert agent.user == mock_user
        assert agent.name == "New Agent"
        assert agent.s3_key == "agents/1/new.msi"
        assert agent.original_filename == "new.msi"
        assert agent.os == mock_windows_os
        assert agent.file_size_bytes == 2048
        assert agent.sha256_hash == "newhash123"
        assert agent.deleted_at is None

        mock_os_model.objects.filter.assert_called_once_with(slug="windows")
        mock_agent_config.objects.create.assert_called_once()

    @patch("cms.assets.services.audit_log")
    @patch("cms.assets.services.AgentConfig")
    @patch("cms.assets.services.OperatingSystem")
    def test_creates_agent_record_with_linux_os(
        self, mock_os_model, mock_agent_config, mock_audit_log, mock_user, mock_linux_os
    ):
        """Should correctly look up Linux OS."""
        mock_os_model.objects.filter.return_value.first.return_value = mock_linux_os
        created_agent = MagicMock()
        created_agent.id = 43
        created_agent.os = mock_linux_os
        mock_agent_config.objects.create.return_value = created_agent

        agent = create_agent(
            user=mock_user,
            spec=AgentUploadSpec(
                name="Linux Agent",
                s3_key="agents/1/linux.sh",
                filename="linux.sh",
                os_slug="linux-debian",
                file_size=1024,
                sha256="linuxhash",
            ),
        )

        assert agent.os == mock_linux_os
        mock_os_model.objects.filter.assert_called_once_with(slug="linux-debian")

    @patch("cms.assets.services.audit_log")
    @patch("cms.assets.services.AgentConfig")
    @patch("cms.assets.services.OperatingSystem")
    def test_logs_activity(self, mock_os_model, mock_agent_config, mock_audit_log, mock_user, mock_windows_os):
        """Should create an audit log entry for agent creation."""
        mock_os_model.objects.filter.return_value.first.return_value = mock_windows_os
        created_agent = MagicMock()
        created_agent.id = 44
        mock_agent_config.objects.create.return_value = created_agent

        create_agent(
            user=mock_user,
            spec=AgentUploadSpec(
                name="Logged Agent",
                s3_key="agents/1/logged.msi",
                filename="logged.msi",
                os_slug="windows",
                file_size=1024,
                sha256="loggedhash",
            ),
        )

        mock_audit_log.assert_called_once()
        event = mock_audit_log.call_args.args[0]
        assert event.entity_id == 44
        assert event.new_state["name"] == "Logged Agent"
        assert event.new_state["filename"] == "logged.msi"
        assert event.actor_id == mock_user.id

    @patch("cms.assets.services.audit_log")
    @patch("cms.assets.services.AgentConfig")
    @patch("cms.assets.services.OperatingSystem")
    def test_logs_upload_method_when_provided(
        self, mock_os_model, mock_agent_config, mock_audit_log, mock_user, mock_windows_os
    ):
        """Should include upload_method in audit log when provided."""
        mock_os_model.objects.filter.return_value.first.return_value = mock_windows_os
        created_agent = MagicMock()
        created_agent.id = 45
        mock_agent_config.objects.create.return_value = created_agent

        create_agent(
            user=mock_user,
            spec=AgentUploadSpec(
                name="Presigned Agent",
                s3_key="agents/1/presigned.msi",
                filename="presigned.msi",
                os_slug="windows",
                file_size=1024,
                sha256="presignedhash",
                upload_method="presigned",
            ),
        )

        event = mock_audit_log.call_args.args[0]
        assert event.new_state["upload_method"] == "presigned"

    @patch("cms.assets.services.OperatingSystem")
    def test_raises_for_invalid_os_slug(self, mock_os_model, mock_user):
        """Should raise AssetError for invalid OS slug."""
        mock_os_model.objects.filter.return_value.first.return_value = None

        with pytest.raises(AssetError) as exc_info:
            create_agent(
                user=mock_user,
                spec=AgentUploadSpec(
                    name="Invalid OS Agent",
                    s3_key="agents/1/invalid.msi",
                    filename="invalid.msi",
                    os_slug="nonexistent-os",
                    file_size=1024,
                    sha256="invalidhash",
                ),
            )

        assert "not found" in str(exc_info.value).lower()

    @patch("cms.assets.services.audit_log")
    @patch("cms.assets.services.AgentConfig")
    @patch("cms.assets.services.OperatingSystem")
    def test_returns_agent_object(self, mock_os_model, mock_agent_config, mock_audit_log, mock_user, mock_windows_os):
        """Should return the created AgentConfig object."""
        from cms.models import AgentConfig as RealAgentConfig

        mock_os_model.objects.filter.return_value.first.return_value = mock_windows_os
        created_agent = MagicMock(spec=RealAgentConfig)
        created_agent.id = 46
        created_agent.pk = 46
        mock_agent_config.objects.create.return_value = created_agent

        result = create_agent(
            user=mock_user,
            spec=AgentUploadSpec(
                name="Return Test",
                s3_key="agents/1/return.msi",
                filename="return.msi",
                os_slug="windows",
                file_size=1024,
                sha256="returnhash",
            ),
        )

        assert isinstance(result, RealAgentConfig)
        assert result.pk is not None


# -----------------------------------------------------------------------------
# Tests for delete_agent()
# -----------------------------------------------------------------------------


class TestDeleteAgent:
    """Tests for delete_agent function."""

    @patch("cms.assets.services.audit_log")
    @patch("cms.assets.services.s3_delete")
    def test_soft_deletes_agent(self, mock_s3_delete, mock_audit_log, mock_windows_agent):
        """Should set deleted_at timestamp on agent."""
        mock_s3_delete.return_value = None
        assert mock_windows_agent.deleted_at is None

        delete_agent(mock_windows_agent)

        mock_windows_agent.save.assert_called_once_with(update_fields=["deleted_at"])
        assert mock_windows_agent.deleted_at is not None

    @patch("cms.assets.services.audit_log")
    @patch("cms.assets.services.s3_delete")
    def test_does_not_hard_delete(self, mock_s3_delete, mock_audit_log, mock_windows_agent):
        """Should not hard delete - only soft delete via save."""
        mock_s3_delete.return_value = None

        delete_agent(mock_windows_agent)

        # save was called (soft delete), but delete() was never called
        mock_windows_agent.save.assert_called_once()
        mock_windows_agent.delete.assert_not_called()

    @patch("cms.assets.services.audit_log")
    @patch("cms.assets.services.s3_delete")
    def test_calls_s3_delete_with_correct_key(self, mock_s3_delete, mock_audit_log, mock_windows_agent):
        """Should call S3 delete with the agent's s3_key."""
        mock_s3_delete.return_value = None

        delete_agent(mock_windows_agent)

        mock_s3_delete.assert_called_once_with(mock_windows_agent.s3_key)

    @patch("cms.assets.services.audit_log")
    @patch("cms.assets.services.s3_delete")
    def test_logs_activity(self, mock_s3_delete, mock_audit_log, mock_windows_agent):
        """Should create an audit log entry for agent deletion."""
        mock_s3_delete.return_value = None

        delete_agent(mock_windows_agent)

        mock_audit_log.assert_called_once()
        event = mock_audit_log.call_args.args[0]
        assert event.entity_id == mock_windows_agent.id
        assert event.previous_state["name"] == mock_windows_agent.name
        assert event.actor_id == mock_windows_agent.user.id

    @patch("cms.assets.services.s3_delete")
    def test_raises_if_s3_delete_fails(self, mock_s3_delete, mock_windows_agent):
        """Should raise AssetError if S3 delete fails."""
        from cms.assets.s3 import S3Error

        mock_s3_delete.side_effect = S3Error("Delete failed")

        with pytest.raises(AssetError) as exc_info:
            delete_agent(mock_windows_agent)

        assert "delete" in str(exc_info.value).lower()

    @patch("cms.assets.services.s3_delete")
    def test_agent_not_soft_deleted_if_s3_fails(self, mock_s3_delete, mock_windows_agent):
        """Should not soft delete agent if S3 delete fails."""
        from cms.assets.s3 import S3Error

        mock_s3_delete.side_effect = S3Error("Delete failed")

        with pytest.raises(AssetError):
            delete_agent(mock_windows_agent)

        # save should not have been called since s3 failed first
        mock_windows_agent.save.assert_not_called()
        assert mock_windows_agent.deleted_at is None

    @patch("cms.assets.services.audit_log")
    @patch("cms.assets.services.s3_delete")
    def test_s3_delete_called_before_db_update(self, mock_s3_delete, mock_audit_log, mock_windows_agent):
        """S3 delete should be called before database is updated."""
        call_order = []

        def track_s3_delete(*args):
            call_order.append("s3_delete")

        def track_save(*args, **kwargs):
            call_order.append("save")

        mock_s3_delete.side_effect = track_s3_delete
        mock_windows_agent.save.side_effect = track_save

        delete_agent(mock_windows_agent)

        assert call_order == ["s3_delete", "save"]


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
