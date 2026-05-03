"""Tests for CMS AgentConfig model.

These tests verify the AgentConfig model is:
- Importable from cms.models
- Inherits from FileAsset (which inherits from Asset)
- Has correct fields (user, os FK)
- Has correct meta options (ordering, verbose_name)
"""

from unittest.mock import MagicMock, patch

from django.db import models

# -----------------------------------------------------------------------------
# Test AgentConfig Model Structure
# -----------------------------------------------------------------------------


class TestAgentConfigModel:
    """Tests for AgentConfig model structure."""

    def test_agent_config_can_be_imported_from_cms(self):
        """AgentConfig should be importable from cms.models."""
        from cms.models import AgentConfig

        assert AgentConfig is not None

    def test_agent_config_is_not_abstract(self):
        """AgentConfig should be a concrete model."""
        from cms.models import AgentConfig

        assert AgentConfig._meta.abstract is False

    def test_agent_config_inherits_from_file_asset(self):
        """AgentConfig should inherit from FileAsset."""
        from cms.models import AgentConfig, FileAsset

        assert issubclass(AgentConfig, FileAsset)

    def test_agent_config_has_user_fk(self):
        """AgentConfig should have a user ForeignKey."""
        from cms.models import AgentConfig

        field = AgentConfig._meta.get_field("user")
        assert isinstance(field, models.ForeignKey)
        assert field.related_query_name() == "cms_agents"

    def test_agent_config_has_os_fk(self):
        """AgentConfig should have an os ForeignKey to OperatingSystem."""
        from cms.models import AgentConfig

        field = AgentConfig._meta.get_field("os")
        assert isinstance(field, models.ForeignKey)

    def test_agent_config_inherits_name_field(self):
        """AgentConfig should inherit name field from Asset."""
        from cms.models import AgentConfig

        field = AgentConfig._meta.get_field("name")
        assert isinstance(field, models.CharField)
        assert field.max_length == 100

    def test_agent_config_inherits_s3_key_field(self):
        """AgentConfig should inherit s3_key field from FileAsset."""
        from cms.models import AgentConfig

        field = AgentConfig._meta.get_field("s3_key")
        assert isinstance(field, models.CharField)
        assert field.max_length == 500

    def test_agent_config_inherits_original_filename_field(self):
        """AgentConfig should inherit original_filename field from FileAsset."""
        from cms.models import AgentConfig

        field = AgentConfig._meta.get_field("original_filename")
        assert isinstance(field, models.CharField)
        assert field.max_length == 255

    def test_agent_config_inherits_file_size_bytes_field(self):
        """AgentConfig should inherit file_size_bytes field from FileAsset."""
        from cms.models import AgentConfig

        field = AgentConfig._meta.get_field("file_size_bytes")
        assert isinstance(field, models.PositiveBigIntegerField)

    def test_agent_config_inherits_sha256_hash_field(self):
        """AgentConfig should inherit sha256_hash field from FileAsset."""
        from cms.models import AgentConfig

        field = AgentConfig._meta.get_field("sha256_hash")
        assert isinstance(field, models.CharField)
        assert field.max_length == 64

    def test_agent_config_inherits_created_at_field(self):
        """AgentConfig should inherit created_at field from Asset."""
        from cms.models import AgentConfig

        field = AgentConfig._meta.get_field("created_at")
        assert isinstance(field, models.DateTimeField)
        assert field.auto_now_add is True

    def test_agent_config_inherits_deleted_at_field(self):
        """AgentConfig should inherit deleted_at field from Asset."""
        from cms.models import AgentConfig

        field = AgentConfig._meta.get_field("deleted_at")
        assert isinstance(field, models.DateTimeField)
        assert field.null is True
        assert field.blank is True

    def test_agent_config_has_ordering_meta(self):
        """AgentConfig should be ordered by -created_at."""
        from cms.models import AgentConfig

        assert AgentConfig._meta.ordering == ["-created_at"]

    def test_agent_config_has_verbose_name_meta(self):
        """AgentConfig should have correct verbose names."""
        from cms.models import AgentConfig

        assert AgentConfig._meta.verbose_name == "Agent Config"
        assert AgentConfig._meta.verbose_name_plural == "Agent Configs"


# -----------------------------------------------------------------------------
# Test AgentConfig Properties (no DB needed)
# -----------------------------------------------------------------------------


class TestAgentConfigProperties:
    """Tests for AgentConfig model properties using in-memory construction."""

    def test_str_returns_name_and_os(self):
        """__str__ should return name and OS name."""
        from cms.models import AgentConfig, OperatingSystem

        os_obj = OperatingSystem(slug="test", name="Test OS", extensions=[".test"])

        agent = AgentConfig(
            name="Test Agent",
            os=os_obj,
        )

        assert str(agent) == "Test Agent (Test OS)"

    def test_is_deleted_property(self):
        """is_deleted should return True if deleted_at is set."""
        from django.utils import timezone

        from cms.models import AgentConfig

        agent = AgentConfig(name="Test Agent")

        assert agent.is_deleted is False

        agent.deleted_at = timezone.now()

        assert agent.is_deleted is True

    def test_file_size_mb_property(self):
        """file_size_mb should return size in MB rounded to 1 decimal."""
        from cms.models import AgentConfig

        agent = AgentConfig(
            name="Test Agent",
            file_size_bytes=1048576,  # 1 MB
        )

        assert agent.file_size_mb == 1.0


# -----------------------------------------------------------------------------
# Test AgentConfig Behavior (DB required)
# -----------------------------------------------------------------------------


class TestAgentConfigBehavior:
    """Tests for AgentConfig model behavior with mocked database access."""

    def test_active_for_user_excludes_deleted(self):
        """active_for_user chains SoftDeleteQuerySet.active() and the user filter."""
        from cms.models import AgentConfig

        user = MagicMock(id=1, username="testuser-active")
        active_agent = MagicMock(name="Active Agent")

        mock_filtered = MagicMock()
        mock_filtered.__iter__ = lambda self: iter([active_agent])
        mock_active_qs = MagicMock()
        mock_active_qs.filter.return_value = mock_filtered

        with patch.object(AgentConfig.objects, "active", return_value=mock_active_qs) as mock_active:
            result = list(AgentConfig.active_for_user(user))

        mock_active.assert_called_once_with()
        mock_active_qs.filter.assert_called_once_with(user=user)
        assert result == [active_agent]

    def test_os_foreign_key_protects_on_delete(self):
        """OS FK uses PROTECT — verified via field inspection."""
        from django.db.models import PROTECT

        from cms.models import AgentConfig

        field = AgentConfig._meta.get_field("os")
        assert field.remote_field.on_delete is PROTECT
