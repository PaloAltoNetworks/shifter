"""Unit tests for Mission Control models."""

import pytest
from django.contrib.auth import get_user_model

from mission_control.models import (
    ActivityLog,
    AgentConfig,
    OperatingSystem,
    Range,
    UserProfile,
)

User = get_user_model()


# --- OperatingSystem ---


class TestOperatingSystem:
    def test_str_returns_name(self):
        os = OperatingSystem(slug="test", name="Test OS", extensions=[".test"])
        assert str(os) == "Test OS"

    @pytest.mark.django_db
    def test_get_for_extension_finds_match(self):
        """get_for_extension returns OS when extension matches."""
        os = OperatingSystem.objects.get(slug="windows")
        result = OperatingSystem.get_for_extension(".msi")
        assert result == os

    @pytest.mark.django_db
    def test_get_for_extension_case_insensitive(self):
        """get_for_extension is case insensitive."""
        result = OperatingSystem.get_for_extension(".MSI")
        assert result is not None
        assert result.slug == "windows"

    @pytest.mark.django_db
    def test_get_for_extension_adds_dot_if_missing(self):
        """get_for_extension adds leading dot if missing."""
        result = OperatingSystem.get_for_extension("msi")
        assert result is not None
        assert result.slug == "windows"

    @pytest.mark.django_db
    def test_get_for_extension_returns_none_for_unknown(self):
        """get_for_extension returns None for unknown extensions."""
        result = OperatingSystem.get_for_extension(".xyz")
        assert result is None


# --- UserProfile ---


@pytest.mark.django_db
class TestUserProfile:
    def test_auto_created_on_user_creation(self):
        """UserProfile is automatically created when User is created."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        assert hasattr(user, "profile")
        assert isinstance(user.profile, UserProfile)

    def test_str_returns_user_email(self):
        """__str__ returns profile description with email."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        assert "test@example.com" in str(user.profile)

    def test_is_deleted_false_by_default(self):
        """is_deleted returns False when deleted_at is None."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        assert user.profile.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self):
        """is_deleted returns True when deleted_at is set."""
        from django.utils import timezone

        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        user.profile.deleted_at = timezone.now()
        assert user.profile.is_deleted is True


# --- AgentConfig ---


@pytest.mark.django_db
class TestAgentConfig:
    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def windows_os(self):
        return OperatingSystem.objects.get(slug="windows")

    def test_str_returns_name_and_os(self, user, windows_os):
        """__str__ returns agent name with OS."""
        agent = AgentConfig(
            user=user,
            os=windows_os,
            name="Test Agent",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        assert str(agent) == "Test Agent (Windows)"

    def test_is_deleted_false_by_default(self, user, windows_os):
        """is_deleted returns False when deleted_at is None."""
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test Agent",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        assert agent.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self, user, windows_os):
        """is_deleted returns True when deleted_at is set."""
        from django.utils import timezone

        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test Agent",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        agent.deleted_at = timezone.now()
        agent.save()
        assert agent.is_deleted is True

    def test_active_for_user_excludes_deleted(self, user, windows_os):
        """active_for_user excludes soft-deleted agents."""
        from django.utils import timezone

        # Create active agent
        active = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Active Agent",
            s3_key="test/active.msi",
            original_filename="active.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )

        # Create deleted agent
        AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Deleted Agent",
            s3_key="test/deleted.msi",
            original_filename="deleted.msi",
            file_size_bytes=1024,
            sha256_hash="def456",
            deleted_at=timezone.now(),
        )

        result = list(AgentConfig.active_for_user(user))
        assert len(result) == 1
        assert result[0] == active

    def test_active_for_user_only_returns_user_agents(self, user, windows_os):
        """active_for_user only returns agents for the specified user."""
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


# --- Range ---


@pytest.mark.django_db
class TestRange:
    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    def test_str_with_agent(self, user):
        """__str__ includes agent name when agent exists."""
        windows_os = OperatingSystem.objects.get(slug="windows")
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test Agent",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
        )
        range_obj = Range.objects.create(user=user, agent=agent)
        assert "Test Agent" in str(range_obj)

    def test_str_without_agent(self, user):
        """__str__ shows 'Unknown Agent' when agent is None."""
        range_obj = Range.objects.create(user=user, agent=None)
        assert "Unknown Agent" in str(range_obj)

    # --- kali_private_ip property tests ---

    def test_kali_private_ip_returns_attacker_ip(self, user):
        """kali_private_ip returns the attacker instance's private_ip."""
        range_obj = Range.objects.create(
            user=user,
            provisioned_instances=[
                {"role": "attacker", "os": "kali", "private_ip": "10.1.5.10"},
                {"role": "victim", "os": "ubuntu", "private_ip": "10.1.5.20"},
            ],
        )
        assert range_obj.kali_private_ip == "10.1.5.10"

    def test_kali_private_ip_returns_none_when_no_provisioned_instances(self, user):
        """kali_private_ip returns None when provisioned_instances is empty."""
        range_obj = Range.objects.create(user=user, provisioned_instances=None)
        assert range_obj.kali_private_ip is None

    def test_kali_private_ip_returns_none_when_no_attacker(self, user):
        """kali_private_ip returns None when no attacker instance exists."""
        range_obj = Range.objects.create(
            user=user,
            provisioned_instances=[
                {"role": "victim", "os": "ubuntu", "private_ip": "10.1.5.20"},
            ],
        )
        assert range_obj.kali_private_ip is None

    def test_kali_private_ip_returns_none_when_attacker_missing_ip(self, user):
        """kali_private_ip returns None when attacker has no private_ip field."""
        range_obj = Range.objects.create(
            user=user,
            provisioned_instances=[
                {"role": "attacker", "os": "kali"},
            ],
        )
        assert range_obj.kali_private_ip is None

    # --- victim_private_ip property tests ---

    def test_victim_private_ip_returns_first_victim_ip(self, user):
        """victim_private_ip returns the first victim instance's private_ip."""
        range_obj = Range.objects.create(
            user=user,
            provisioned_instances=[
                {"role": "attacker", "os": "kali", "private_ip": "10.1.5.10"},
                {"role": "victim", "os": "ubuntu", "private_ip": "10.1.5.20"},
            ],
        )
        assert range_obj.victim_private_ip == "10.1.5.20"

    def test_victim_private_ip_returns_none_when_no_provisioned_instances(self, user):
        """victim_private_ip returns None when provisioned_instances is empty."""
        range_obj = Range.objects.create(user=user, provisioned_instances=None)
        assert range_obj.victim_private_ip is None

    def test_victim_private_ip_returns_none_when_no_victims(self, user):
        """victim_private_ip returns None when no victim instances exist."""
        range_obj = Range.objects.create(
            user=user,
            provisioned_instances=[
                {"role": "attacker", "os": "kali", "private_ip": "10.1.5.10"},
            ],
        )
        assert range_obj.victim_private_ip is None

    def test_victim_private_ip_returns_none_when_victim_missing_ip(self, user):
        """victim_private_ip returns None when victim has no private_ip field."""
        range_obj = Range.objects.create(
            user=user,
            provisioned_instances=[
                {"role": "victim", "os": "ubuntu"},
            ],
        )
        assert range_obj.victim_private_ip is None

    def test_victim_private_ip_returns_first_when_multiple_victims(self, user):
        """victim_private_ip returns first victim's IP when multiple victims exist."""
        range_obj = Range.objects.create(
            user=user,
            provisioned_instances=[
                {"role": "victim", "os": "ubuntu", "private_ip": "10.1.5.20"},
                {"role": "victim", "os": "windows", "private_ip": "10.1.5.30"},
            ],
        )
        assert range_obj.victim_private_ip == "10.1.5.20"


# --- ActivityLog ---


@pytest.mark.django_db
class TestActivityLog:
    def test_log_creates_entry(self):
        """ActivityLog.log() creates a new entry."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        log = ActivityLog.log("test_action", user=user)

        assert log.action == "test_action"
        assert log.user == user
        assert log.pk is not None

    def test_log_stores_metadata(self):
        """ActivityLog.log() stores kwargs as metadata."""
        log = ActivityLog.log("test_action", foo="bar", count=42)

        assert log.metadata == {"foo": "bar", "count": 42}

    def test_log_works_without_user(self):
        """ActivityLog.log() works with anonymous actions."""
        log = ActivityLog.log("anonymous_action")

        assert log.user is None
        assert log.action == "anonymous_action"

    def test_str_with_user(self):
        """__str__ includes user email when user exists."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        log = ActivityLog.log("test_action", user=user)

        assert "test@example.com" in str(log)
        assert "test_action" in str(log)

    def test_str_without_user(self):
        """__str__ shows 'anonymous' when user is None."""
        log = ActivityLog.log("test_action")

        assert "anonymous" in str(log)
