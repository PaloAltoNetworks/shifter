"""Unit tests for Asset/FileAsset abstract base classes.

Tests verify the abstract hierarchy provides:
- Asset: Common fields (name, timestamps) and soft delete
- FileAsset: S3 file storage fields and computed properties

These tests use AgentConfig as the concrete implementation since
abstract models cannot be instantiated directly.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.utils import timezone

from cms.models import AgentConfig, Asset, FileAsset, OperatingSystem

User = get_user_model()


def _make_os():
    """Build an in-memory OperatingSystem."""
    return OperatingSystem(slug="windows", name="Windows", extensions=[".msi"])


def _make_user(**kwargs):
    """Build an in-memory User (unsaved)."""
    defaults = {"id": 1, "username": "test@example.com", "email": "test@example.com"}
    defaults.update(kwargs)
    return User(**defaults)


def _make_agent(**overrides):
    """Build an in-memory AgentConfig with sensible defaults."""
    defaults = {
        "id": 1,
        "user": _make_user(),
        "os": _make_os(),
        "name": "Test",
        "s3_key": "test/key.msi",
        "original_filename": "installer.msi",
        "file_size_bytes": 1024,
        "sha256_hash": "abc123",
        "deleted_at": None,
        "created_at": timezone.now(),
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


class TestAssetAbstractBase:
    """Tests for Asset abstract base class functionality.

    Since Asset is abstract, we test through AgentConfig which inherits from it.
    """

    def test_asset_is_abstract(self):
        """Asset model class is abstract (cannot be instantiated directly)."""
        assert Asset._meta.abstract is True

    def test_has_name_field(self):
        """Asset provides name field through inheritance."""
        agent = _make_agent(name="Test Agent")
        assert agent.name == "Test Agent"

    def test_has_created_at_auto_set(self):
        """Asset provides created_at field with auto_now_add."""
        now = timezone.now()
        agent = _make_agent(created_at=now)
        assert agent.created_at is not None
        assert (timezone.now() - agent.created_at).total_seconds() < 60

    def test_has_deleted_at_nullable(self):
        """Asset provides deleted_at field that defaults to None."""
        agent = _make_agent(deleted_at=None)
        assert agent.deleted_at is None

    def test_is_deleted_property_false_by_default(self):
        """is_deleted returns False when deleted_at is None."""
        agent = _make_agent(deleted_at=None)
        assert agent.is_deleted is False

    def test_is_deleted_property_true_when_set(self):
        """is_deleted returns True when deleted_at is set."""
        agent = _make_agent()
        agent.deleted_at = timezone.now()
        assert agent.is_deleted is True

    def test_active_for_user_excludes_deleted(self):
        """active_for_user chains SoftDeleteQuerySet.active() and the user filter."""
        user = _make_user()
        active = _make_agent(name="Active", user=user)

        mock_filtered = MagicMock()
        mock_filtered.__iter__ = lambda self: iter([active])
        mock_active_qs = MagicMock()
        mock_active_qs.filter.return_value = mock_filtered

        with patch.object(AgentConfig.objects, "active", return_value=mock_active_qs) as mock_active:
            result = list(AgentConfig.active_for_user(user))

        mock_active.assert_called_once_with()
        mock_active_qs.filter.assert_called_once_with(user=user)
        assert len(result) == 1
        assert result[0] == active

    def test_active_for_user_filters_by_user(self):
        """active_for_user only returns records for the specified user."""
        user = _make_user()
        my_agent = _make_agent(name="My Agent", user=user)

        mock_filtered = MagicMock()
        mock_filtered.__iter__ = lambda self: iter([my_agent])
        mock_active_qs = MagicMock()
        mock_active_qs.filter.return_value = mock_filtered

        with patch.object(AgentConfig.objects, "active", return_value=mock_active_qs) as mock_active:
            result = list(AgentConfig.active_for_user(user))

        mock_active.assert_called_once_with()
        mock_active_qs.filter.assert_called_once_with(user=user)
        assert len(result) == 1
        assert result[0].name == "My Agent"


class TestFileAssetAbstractBase:
    """Tests for FileAsset abstract base class functionality.

    FileAsset extends Asset with S3 storage fields.
    """

    def test_file_asset_is_abstract(self):
        """FileAsset model class is abstract (cannot be instantiated directly)."""
        assert FileAsset._meta.abstract is True

    def test_has_s3_key_field(self):
        """FileAsset provides s3_key field."""
        agent = _make_agent(s3_key="users/123/agents/installer.msi")
        assert agent.s3_key == "users/123/agents/installer.msi"

    def test_has_original_filename_field(self):
        """FileAsset provides original_filename field."""
        agent = _make_agent(original_filename="XDR_Agent_7.5.1.msi")
        assert agent.original_filename == "XDR_Agent_7.5.1.msi"

    def test_has_file_size_bytes_field(self):
        """FileAsset provides file_size_bytes field."""
        agent = _make_agent(file_size_bytes=104857600)
        assert agent.file_size_bytes == 104857600

    def test_has_sha256_hash_field(self):
        """FileAsset provides sha256_hash field."""
        hash_value = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        agent = _make_agent(sha256_hash=hash_value)
        assert agent.sha256_hash == hash_value

    def test_file_size_mb_property(self):
        """file_size_mb returns size in megabytes rounded to 1 decimal."""
        agent = _make_agent(file_size_bytes=104857600)
        assert agent.file_size_mb == 100.0

    def test_file_size_mb_rounds_correctly(self):
        """file_size_mb rounds to 1 decimal place."""
        agent = _make_agent(file_size_bytes=54893568)
        assert agent.file_size_mb == 52.4


class TestAgentConfigInheritsCorrectly:
    """Tests that AgentConfig properly inherits from FileAsset.

    These tests verify the inheritance chain is correct and
    AgentConfig-specific fields work alongside inherited fields.
    """

    def test_agent_config_is_subclass_of_file_asset(self):
        """AgentConfig inherits from FileAsset."""
        assert issubclass(AgentConfig, FileAsset)

    def test_agent_config_is_subclass_of_asset(self):
        """AgentConfig inherits from Asset (through FileAsset)."""
        assert issubclass(AgentConfig, Asset)

    def test_agent_config_has_os_field(self):
        """AgentConfig has its own os foreign key field."""
        os_obj = _make_os()
        agent = _make_agent(os=os_obj)
        assert agent.os == os_obj
        assert agent.os.name == "Windows"

    def test_agent_config_user_related_name(self):
        """AgentConfig user FK has related_name='cms_agents'."""
        field = AgentConfig._meta.get_field("user")
        assert field.remote_field.related_name == "cms_agents"

    def test_str_method_includes_name_and_os(self):
        """__str__ returns name with OS for identification."""
        agent = _make_agent(name="My XDR Agent")
        assert str(agent) == "My XDR Agent (Windows)"

    def test_ordering_by_created_at_desc(self):
        """Model meta has ordering by -created_at."""
        assert AgentConfig._meta.ordering == ["-created_at"]
