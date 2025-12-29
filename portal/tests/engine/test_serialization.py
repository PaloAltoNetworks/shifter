"""Tests for engine.services.serialization module."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.services.serialization import range_to_dict
from mission_control.models import AgentConfig, OperatingSystem, Range

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def windows_os(db):
    """Get the Windows operating system."""
    return OperatingSystem.objects.get(slug="windows")


@pytest.fixture
def agent(db, user, windows_os):
    """Create a test agent."""
    return AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Test Agent",
        s3_key="agents/1/test.msi",
        original_filename="test.msi",
        file_size_bytes=1024,
        sha256_hash="abc123",
    )


@pytest.fixture
def dc_agent(db, user, windows_os):
    """Create a DC agent."""
    return AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="DC Agent",
        s3_key="agents/1/dc.msi",
        original_filename="dc.msi",
        file_size_bytes=2048,
        sha256_hash="def456",
    )


def create_range(user, agent, **kwargs):
    """Helper to create a range with specific fields."""
    defaults = {
        "status": Range.Status.READY,
        "subnet_index": 1,
        "instance_config": [{"role": "attacker", "os_type": "kali"}],
    }
    defaults.update(kwargs)
    return Range.objects.create(user=user, agent=agent, **defaults)


# -----------------------------------------------------------------------------
# Tests for range_to_dict()
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestRangeToDict:
    """Tests for range_to_dict function."""

    def test_includes_required_fields(self, user, agent):
        """Should include all required fields in output."""
        range_obj = create_range(user, agent)

        result = range_to_dict(range_obj)

        assert "id" in result
        assert "status" in result
        assert "agent_id" in result
        assert "agent_name" in result
        assert "dc_agent_id" in result
        assert "dc_agent_name" in result
        assert "created_at" in result

    def test_includes_id_and_status(self, user, agent):
        """Should correctly serialize id and status."""
        range_obj = create_range(user, agent, status=Range.Status.PROVISIONING)

        result = range_to_dict(range_obj)

        assert result["id"] == range_obj.id
        assert result["status"] == Range.Status.PROVISIONING

    def test_includes_agent_details(self, user, agent):
        """Should include agent id and name."""
        range_obj = create_range(user, agent)

        result = range_to_dict(range_obj)

        assert result["agent_id"] == agent.id
        assert result["agent_name"] == "Test Agent"

    def test_includes_dc_agent_details(self, user, agent, dc_agent):
        """Should include DC agent id and name when present."""
        range_obj = create_range(user, agent, dc_agent=dc_agent)

        result = range_to_dict(range_obj)

        assert result["dc_agent_id"] == dc_agent.id
        assert result["dc_agent_name"] == "DC Agent"

    def test_dc_agent_null_when_not_set(self, user, agent):
        """Should have null DC agent when not set."""
        range_obj = create_range(user, agent)

        result = range_to_dict(range_obj)

        assert result["dc_agent_id"] is None
        assert result["dc_agent_name"] is None

    def test_excludes_victim_ip(self, user, agent):
        """Should NOT include victim_ip (security)."""
        range_obj = create_range(user, agent)
        range_obj.victim_ip = "10.1.1.100"
        range_obj.save()

        result = range_to_dict(range_obj)

        assert "victim_ip" not in result

    def test_excludes_kali_ip(self, user, agent):
        """Should NOT include kali_ip (security)."""
        range_obj = create_range(user, agent)
        range_obj.kali_ip = "10.1.1.10"
        range_obj.save()

        result = range_to_dict(range_obj)

        assert "kali_ip" not in result

    def test_excludes_sensitive_fields(self, user, agent):
        """Should not include sensitive infrastructure fields."""
        range_obj = create_range(user, agent)
        range_obj.kali_ssh_key_secret_arn = "arn:aws:secretsmanager:..."
        range_obj.victim_ssh_key_secret_arn = "arn:aws:secretsmanager:..."
        range_obj.save()

        result = range_to_dict(range_obj)

        assert "kali_ssh_key_secret_arn" not in result
        assert "victim_ssh_key_secret_arn" not in result
        assert "subnet_index" not in result

    def test_handles_null_agent(self, user, windows_os):
        """Should handle range with null agent."""
        # Create range without agent (edge case)
        range_obj = Range.objects.create(
            user=user,
            agent=None,
            status=Range.Status.READY,
            subnet_index=1,
            instance_config=[],
        )

        result = range_to_dict(range_obj)

        assert result["agent_id"] is None
        assert result["agent_name"] is None

    def test_formats_timestamps_as_iso(self, user, agent):
        """Should format timestamps as ISO format strings."""
        now = timezone.now()
        range_obj = create_range(user, agent)
        range_obj.ready_at = now
        range_obj.save()

        result = range_to_dict(range_obj)

        # created_at should be ISO format string
        assert isinstance(result["created_at"], str)
        assert "T" in result["created_at"]  # ISO format has T separator

        # ready_at should be ISO format string
        assert isinstance(result["ready_at"], str)
        assert "T" in result["ready_at"]

    def test_handles_null_timestamps(self, user, agent):
        """Should handle null timestamps gracefully."""
        range_obj = create_range(user, agent)
        # ready_at and paused_at are None by default

        result = range_to_dict(range_obj)

        assert result["ready_at"] is None
        assert result["paused_at"] is None

    def test_includes_chat_url(self, user, agent):
        """Should include chat_url when present."""
        range_obj = create_range(user, agent)
        range_obj.chat_url = "https://chat.example.com/room/123"
        range_obj.save()

        result = range_to_dict(range_obj)

        assert result["chat_url"] == "https://chat.example.com/room/123"

    def test_includes_error_message(self, user, agent):
        """Should include error_message when present."""
        range_obj = create_range(user, agent, status=Range.Status.FAILED)
        range_obj.error_message = "Provisioning failed"
        range_obj.save()

        result = range_to_dict(range_obj)

        assert result["error_message"] == "Provisioning failed"

    def test_returns_dict(self, user, agent):
        """Should return a dict, not JsonResponse or other type."""
        range_obj = create_range(user, agent)

        result = range_to_dict(range_obj)

        assert isinstance(result, dict)

    def test_all_values_are_json_serializable(self, user, agent):
        """All values should be JSON serializable."""
        import json

        now = timezone.now()
        range_obj = create_range(user, agent)
        range_obj.ready_at = now
        range_obj.chat_url = "https://example.com"
        range_obj.save()

        result = range_to_dict(range_obj)

        # Should not raise
        json_str = json.dumps(result)
        assert json_str is not None
