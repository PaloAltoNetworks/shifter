"""Tests for CMS abstract base models behavior.

Tests Asset soft-delete and active_for_user behavior through concrete model.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


@pytest.mark.django_db
class TestAssetBehavior:
    """Tests for Asset behavior through a concrete implementation.

    Uses cms.AgentConfig as the concrete model since it inherits from
    FileAsset which inherits from Asset.
    """

    @pytest.fixture
    def user(self):
        """Create a test user."""
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def operating_system(self):
        """Create an operating system for agents."""
        from cms.models import OperatingSystem

        os, _ = OperatingSystem.objects.get_or_create(
            slug="windows", defaults={"name": "Windows", "extensions": [".msi"]}
        )
        return os

    def test_is_deleted_property(self, user, operating_system):
        """is_deleted reflects deleted_at state."""
        from cms.models import AgentConfig

        agent = AgentConfig.objects.create(
            user=user,
            name="Test Agent",
            os=operating_system,
            s3_key="agents/test.msi",
            original_filename="test.msi",
            file_size_bytes=1024,
        )

        # Not deleted
        assert agent.is_deleted is False

        # Set deleted_at
        agent.deleted_at = timezone.now()
        assert agent.is_deleted is True

    def test_active_for_user_excludes_deleted_records(self, user, operating_system):
        """active_for_user should exclude soft-deleted records."""
        from cms.models import AgentConfig

        active = AgentConfig.objects.create(
            user=user,
            name="Active Agent",
            os=operating_system,
            s3_key="agents/active.msi",
            original_filename="active.msi",
            file_size_bytes=1024,
        )
        AgentConfig.objects.create(
            user=user,
            name="Deleted Agent",
            os=operating_system,
            s3_key="agents/deleted.msi",
            original_filename="deleted.msi",
            file_size_bytes=1024,
            deleted_at=timezone.now(),
        )

        result = list(AgentConfig.active_for_user(user))

        assert len(result) == 1
        assert result[0] == active

    def test_active_for_user_filters_by_user(self, user, operating_system):
        """active_for_user should only return records for the specified user."""
        from cms.models import AgentConfig

        other_user = User.objects.create_user(username="other@example.com", email="other@example.com")

        AgentConfig.objects.create(
            user=user,
            name="User Agent",
            os=operating_system,
            s3_key="agents/user.msi",
            original_filename="user.msi",
            file_size_bytes=1024,
        )
        AgentConfig.objects.create(
            user=other_user,
            name="Other Agent",
            os=operating_system,
            s3_key="agents/other.msi",
            original_filename="other.msi",
            file_size_bytes=1024,
        )

        result = list(AgentConfig.active_for_user(user))

        assert len(result) == 1
        assert result[0].name == "User Agent"
