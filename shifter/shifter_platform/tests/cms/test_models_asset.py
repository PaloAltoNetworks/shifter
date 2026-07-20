"""Tests for CMS abstract base models behavior.

Tests Asset soft-delete and active_for_user behavior through concrete model.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


def _real_agent(user, *, name, deleted_at=None):
    """Create a real AgentConfig owned by ``user``."""
    from cms.models import AgentConfig, OperatingSystem

    os_obj, _ = OperatingSystem.objects.get_or_create(
        slug="windows", defaults={"name": "Windows", "extensions": [".msi"]}
    )
    agent = AgentConfig.objects.create(
        user=user,
        name=name,
        os=os_obj,
        s3_key=f"agents/{name}.msi",
        original_filename="test.msi",
        file_size_bytes=1024,
    )
    if deleted_at is not None:
        agent.deleted_at = deleted_at
        agent.save(update_fields=["deleted_at"])
    return agent


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

    @pytest.mark.django_db
    def test_active_for_user_excludes_deleted_records(self):
        """active_for_user (a SoftDeleteManager) returns active rows, not deleted ones."""
        from cms.models import AgentConfig

        user = User.objects.create_user(username="asset-active@e.com", email="asset-active@e.com")
        _real_agent(user, name="Active Agent")
        _real_agent(user, name="Deleted Agent", deleted_at=timezone.now())

        result = list(AgentConfig.active_for_user(user))
        assert [a.name for a in result] == ["Active Agent"]

    @pytest.mark.django_db
    def test_active_for_user_filters_by_user(self):
        """active_for_user only returns records for the specified user."""
        from cms.models import AgentConfig

        user = User.objects.create_user(username="asset-u1@e.com", email="asset-u1@e.com")
        other = User.objects.create_user(username="asset-u2@e.com", email="asset-u2@e.com")
        _real_agent(user, name="User Agent")
        _real_agent(other, name="Other Agent")

        result = list(AgentConfig.active_for_user(user))
        assert [a.name for a in result] == ["User Agent"]
