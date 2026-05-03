"""Tests for CMS abstract base models behavior.

Tests Asset soft-delete and active_for_user behavior through concrete model.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class TestAssetBehavior:
    """Tests for Asset behavior through a concrete implementation.

    Uses cms.AgentConfig as the concrete model since it inherits from
    FileAsset which inherits from Asset.
    """

    def _make_agent(self, **overrides):
        """Build an in-memory AgentConfig with sensible defaults."""
        from cms.models import AgentConfig, OperatingSystem

        os_obj = OperatingSystem(slug="windows", name="Windows", extensions=[".msi"])
        user = User(id=1, username="test@example.com", email="test@example.com")

        defaults = {
            "id": 1,
            "user": user,
            "name": "Test Agent",
            "os": os_obj,
            "s3_key": "agents/test.msi",
            "original_filename": "test.msi",
            "file_size_bytes": 1024,
            "deleted_at": None,
        }
        defaults.update(overrides)
        return AgentConfig(**defaults)

    def test_is_deleted_property(self):
        """is_deleted reflects deleted_at state."""
        agent = self._make_agent()

        # Not deleted
        assert agent.is_deleted is False

        # Set deleted_at
        agent.deleted_at = timezone.now()
        assert agent.is_deleted is True

    def test_active_for_user_excludes_deleted_records(self):
        """active_for_user should chain SoftDeleteQuerySet.active() then user filter."""
        from cms.models import AgentConfig

        user = MagicMock(id=1)
        active = self._make_agent(name="Active Agent")

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
        """active_for_user should only return records for the specified user."""
        from cms.models import AgentConfig

        user = MagicMock(id=1)
        user_agent = self._make_agent(name="User Agent")

        mock_filtered = MagicMock()
        mock_filtered.__iter__ = lambda self: iter([user_agent])
        mock_active_qs = MagicMock()
        mock_active_qs.filter.return_value = mock_filtered

        with patch.object(AgentConfig.objects, "active", return_value=mock_active_qs) as mock_active:
            result = list(AgentConfig.active_for_user(user))

        mock_active.assert_called_once_with()
        mock_active_qs.filter.assert_called_once_with(user=user)
        assert len(result) == 1
        assert result[0].name == "User Agent"
