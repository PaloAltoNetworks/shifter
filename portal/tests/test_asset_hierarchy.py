"""Unit tests for Asset/FileAsset abstract base classes.

Tests verify the abstract hierarchy provides:
- Asset: Common fields (name, timestamps) and soft delete
- FileAsset: S3 file storage fields and computed properties

These tests use AgentConfig as the concrete implementation since
abstract models cannot be instantiated directly.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from mission_control.models import AgentConfig, Asset, FileAsset, OperatingSystem

User = get_user_model()


@pytest.mark.django_db
class TestAssetAbstractBase:
    """Tests for Asset abstract base class functionality.

    Since Asset is abstract, we test through AgentConfig which inherits from it.
    """

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def windows_os(self):
        return OperatingSystem.objects.get(slug="windows")

    def test_asset_is_abstract(self):
        """Asset model class is abstract (cannot be instantiated directly)."""
        assert Asset._meta.abstract is True

    def test_has_name_field(self, user, windows_os):
        """Asset provides name field through inheritance."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test Agent",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        assert agent.name == "Test Agent"

    def test_has_created_at_auto_set(self, user, windows_os):
        """Asset provides created_at field with auto_now_add."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        assert agent.created_at is not None
        # Should be recent (within last minute)
        assert (timezone.now() - agent.created_at).total_seconds() < 60

    def test_has_deleted_at_nullable(self, user, windows_os):
        """Asset provides deleted_at field that defaults to None."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        assert agent.deleted_at is None

    def test_is_deleted_property_false_by_default(self, user, windows_os):
        """is_deleted returns False when deleted_at is None."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        assert agent.is_deleted is False

    def test_is_deleted_property_true_when_set(self, user, windows_os):
        """is_deleted returns True when deleted_at is set."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        agent.deleted_at = timezone.now()
        agent.save()
        assert agent.is_deleted is True

    def test_active_for_user_excludes_deleted(self, user, windows_os):
        """active_for_user classmethod excludes soft-deleted records."""
        active = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Active",
            s3_key="test/active.msi",
            original_filename="active.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Deleted",
            s3_key="test/deleted.msi",
            original_filename="deleted.msi",
            file_size_bytes=1024,
            sha256_hash="def456",
            deleted_at=timezone.now(),
        )
        result = list(AgentConfig.active_for_user(user))
        assert len(result) == 1
        assert result[0] == active

    def test_active_for_user_filters_by_user(self, user, windows_os):
        """active_for_user only returns records for the specified user."""
        other_user = User.objects.create_user(username="other@example.com", email="other@example.com")
        AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="My Agent",
            s3_key="test/mine.msi",
            original_filename="mine.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        AgentConfig.objects.create(
            user=other_user,
            os=windows_os,
            name="Other Agent",
            s3_key="test/other.msi",
            original_filename="other.msi",
            file_size_bytes=1024,
            sha256_hash="def456",
        )
        result = list(AgentConfig.active_for_user(user))
        assert len(result) == 1
        assert result[0].name == "My Agent"


@pytest.mark.django_db
class TestFileAssetAbstractBase:
    """Tests for FileAsset abstract base class functionality.

    FileAsset extends Asset with S3 storage fields.
    """

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def windows_os(self):
        return OperatingSystem.objects.get(slug="windows")

    def test_file_asset_is_abstract(self):
        """FileAsset model class is abstract (cannot be instantiated directly)."""
        assert FileAsset._meta.abstract is True

    def test_has_s3_key_field(self, user, windows_os):
        """FileAsset provides s3_key field."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="users/123/agents/installer.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        assert agent.s3_key == "users/123/agents/installer.msi"

    def test_has_original_filename_field(self, user, windows_os):
        """FileAsset provides original_filename field."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="XDR_Agent_7.5.1.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        assert agent.original_filename == "XDR_Agent_7.5.1.msi"

    def test_has_file_size_bytes_field(self, user, windows_os):
        """FileAsset provides file_size_bytes field."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=104857600,  # 100 MB
            sha256_hash="abc123",
        )
        assert agent.file_size_bytes == 104857600

    def test_has_sha256_hash_field(self, user, windows_os):
        """FileAsset provides sha256_hash field."""
        hash_value = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash=hash_value,
        )
        assert agent.sha256_hash == hash_value

    def test_file_size_mb_property(self, user, windows_os):
        """file_size_mb returns size in megabytes rounded to 1 decimal."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=104857600,  # Exactly 100 MB
            sha256_hash="abc123",
        )
        assert agent.file_size_mb == 100.0

    def test_file_size_mb_rounds_correctly(self, user, windows_os):
        """file_size_mb rounds to 1 decimal place."""
        # 52.35 MB = 54893568 bytes (52.35 * 1024 * 1024)
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=54893568,
            sha256_hash="abc123",
        )
        assert agent.file_size_mb == 52.4  # Rounds up from 52.35


@pytest.mark.django_db
class TestAgentConfigInheritsCorrectly:
    """Tests that AgentConfig properly inherits from FileAsset.

    These tests verify the inheritance chain is correct and
    AgentConfig-specific fields work alongside inherited fields.
    """

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def windows_os(self):
        return OperatingSystem.objects.get(slug="windows")

    def test_agent_config_is_subclass_of_file_asset(self):
        """AgentConfig inherits from FileAsset."""
        assert issubclass(AgentConfig, FileAsset)

    def test_agent_config_is_subclass_of_asset(self):
        """AgentConfig inherits from Asset (through FileAsset)."""
        assert issubclass(AgentConfig, Asset)

    def test_agent_config_has_os_field(self, user, windows_os):
        """AgentConfig has its own os foreign key field."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        assert agent.os == windows_os
        assert agent.os.name == "Windows"

    def test_agent_config_user_related_name_preserved(self, user, windows_os):
        """AgentConfig user FK has related_name='agents' preserved."""
        AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        # Access via reverse relation
        assert user.agents.count() == 1
        assert user.agents.first().name == "Test"

    def test_str_method_includes_name_and_os(self, user, windows_os):
        """__str__ returns name with OS for identification."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="My XDR Agent",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        assert str(agent) == "My XDR Agent (Windows)"

    def test_ordering_by_created_at_desc(self, user, windows_os):
        """Records are ordered by created_at descending (newest first)."""
        import time

        agent1 = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="First",
            s3_key="test/first.msi",
            original_filename="first.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        time.sleep(0.01)  # Ensure different timestamps
        agent2 = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Second",
            s3_key="test/second.msi",
            original_filename="second.msi",
            file_size_bytes=1024,
            sha256_hash="def456",
        )
        agents = list(AgentConfig.objects.filter(user=user))
        assert agents[0] == agent2  # Newest first
        assert agents[1] == agent1
