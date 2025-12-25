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

    # --- NGFW fields tests ---

    def test_ngfw_enabled_defaults_to_false(self, user):
        """ngfw_enabled defaults to False."""
        range_obj = Range.objects.create(user=user)
        assert range_obj.ngfw_enabled is False

    def test_ngfw_enabled_can_be_set_true(self, user):
        """ngfw_enabled can be set to True."""
        range_obj = Range.objects.create(user=user, ngfw_enabled=True)
        assert range_obj.ngfw_enabled is True

    def test_ngfw_instance_id_defaults_to_empty(self, user):
        """ngfw_instance_id defaults to empty string."""
        range_obj = Range.objects.create(user=user)
        assert range_obj.ngfw_instance_id == ""

    def test_ngfw_instance_id_can_be_set(self, user):
        """ngfw_instance_id can store an EC2 instance ID."""
        range_obj = Range.objects.create(user=user, ngfw_instance_id="i-0abc123def456")
        assert range_obj.ngfw_instance_id == "i-0abc123def456"

    def test_ngfw_untrust_ip_defaults_to_none(self, user):
        """ngfw_untrust_ip defaults to None."""
        range_obj = Range.objects.create(user=user)
        assert range_obj.ngfw_untrust_ip is None

    def test_ngfw_untrust_ip_can_be_set(self, user):
        """ngfw_untrust_ip can store an IP address."""
        range_obj = Range.objects.create(user=user, ngfw_untrust_ip="10.1.5.10")
        assert range_obj.ngfw_untrust_ip == "10.1.5.10"

    def test_ngfw_trust_ip_defaults_to_none(self, user):
        """ngfw_trust_ip defaults to None."""
        range_obj = Range.objects.create(user=user)
        assert range_obj.ngfw_trust_ip is None

    def test_ngfw_trust_ip_can_be_set(self, user):
        """ngfw_trust_ip can store an IP address."""
        range_obj = Range.objects.create(user=user, ngfw_trust_ip="10.1.5.11")
        assert range_obj.ngfw_trust_ip == "10.1.5.11"


# --- NGFWConfig ---


@pytest.mark.django_db
class TestNGFWConfig:
    """Tests for NGFWConfig model."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def other_user(self):
        return User.objects.create_user(username="other@example.com", email="other@example.com")

    # --- Creation tests ---

    def test_create_with_required_fields(self, user):
        """NGFWConfig can be created with required fields only."""
        from mission_control.models import NGFWConfig

        config = NGFWConfig.objects.create(
            user=user,
            name="Test Panorama",
            panorama_server="panorama.example.com",
            vm_auth_key="vmauth123456",
        )
        assert config.pk is not None
        assert config.user == user
        assert config.name == "Test Panorama"
        assert config.panorama_server == "panorama.example.com"
        assert config.vm_auth_key == "vmauth123456"

    def test_create_with_all_fields(self, user):
        """NGFWConfig can be created with all fields including optional ones."""
        from mission_control.models import NGFWConfig

        config = NGFWConfig.objects.create(
            user=user,
            name="Full Panorama Config",
            panorama_server="panorama1.example.com",
            vm_auth_key="vmauth789",
            panorama_server_2="panorama2.example.com",
            template_stack="Cloud-VM-Stack",
            device_group="Cloud-DG",
        )
        assert config.panorama_server_2 == "panorama2.example.com"
        assert config.template_stack == "Cloud-VM-Stack"
        assert config.device_group == "Cloud-DG"

    # --- Default values ---

    def test_optional_fields_default_to_empty(self, user):
        """Optional fields default to empty strings."""
        from mission_control.models import NGFWConfig

        config = NGFWConfig.objects.create(
            user=user,
            name="Minimal",
            panorama_server="panorama.example.com",
            vm_auth_key="key123",
        )
        assert config.panorama_server_2 == ""
        assert config.template_stack == ""
        assert config.device_group == ""

    def test_deleted_at_defaults_to_none(self, user):
        """deleted_at defaults to None (not soft-deleted)."""
        from mission_control.models import NGFWConfig

        config = NGFWConfig.objects.create(
            user=user,
            name="Test",
            panorama_server="panorama.example.com",
            vm_auth_key="key123",
        )
        assert config.deleted_at is None

    def test_created_at_auto_set(self, user):
        """created_at is automatically set on creation."""
        from mission_control.models import NGFWConfig

        config = NGFWConfig.objects.create(
            user=user,
            name="Test",
            panorama_server="panorama.example.com",
            vm_auth_key="key123",
        )
        assert config.created_at is not None

    # --- active_for_user manager method ---

    def test_active_for_user_returns_user_configs(self, user, other_user):
        """active_for_user returns only configs for the specified user."""
        from mission_control.models import NGFWConfig

        config1 = NGFWConfig.objects.create(
            user=user, name="User Config", panorama_server="p1.example.com", vm_auth_key="key1"
        )
        NGFWConfig.objects.create(
            user=other_user, name="Other Config", panorama_server="p2.example.com", vm_auth_key="key2"
        )

        user_configs = list(NGFWConfig.active_for_user(user))
        assert len(user_configs) == 1
        assert user_configs[0] == config1

    def test_active_for_user_excludes_deleted(self, user):
        """active_for_user excludes soft-deleted configs."""
        from django.utils import timezone

        from mission_control.models import NGFWConfig

        active_config = NGFWConfig.objects.create(
            user=user, name="Active", panorama_server="p1.example.com", vm_auth_key="key1"
        )
        NGFWConfig.objects.create(
            user=user,
            name="Deleted",
            panorama_server="p2.example.com",
            vm_auth_key="key2",
            deleted_at=timezone.now(),
        )

        active_configs = list(NGFWConfig.active_for_user(user))
        assert len(active_configs) == 1
        assert active_configs[0] == active_config

    def test_active_for_user_returns_empty_for_no_configs(self, user):
        """active_for_user returns empty queryset when user has no configs."""
        from mission_control.models import NGFWConfig

        active_configs = list(NGFWConfig.active_for_user(user))
        assert active_configs == []

    # --- Soft delete ---

    def test_soft_delete_sets_deleted_at(self, user):
        """Setting deleted_at soft-deletes the config."""
        from django.utils import timezone

        from mission_control.models import NGFWConfig

        config = NGFWConfig.objects.create(
            user=user, name="ToDelete", panorama_server="p.example.com", vm_auth_key="key"
        )
        config.deleted_at = timezone.now()
        config.save()

        # Config still exists in DB
        assert NGFWConfig.objects.filter(pk=config.pk).exists()
        # But not in active_for_user
        assert config not in NGFWConfig.active_for_user(user)

    # --- String representation ---

    def test_str_representation(self, user):
        """__str__ returns the config name and panorama server."""
        from mission_control.models import NGFWConfig

        config = NGFWConfig.objects.create(
            user=user, name="My Panorama", panorama_server="p.example.com", vm_auth_key="key"
        )
        assert str(config) == "My Panorama (p.example.com)"


@pytest.mark.django_db
class TestRangeNGFWConfigFK:
    """Tests for Range.ngfw_config foreign key relationship."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def ngfw_config(self, user):
        from mission_control.models import NGFWConfig

        return NGFWConfig.objects.create(
            user=user,
            name="Test Config",
            panorama_server="panorama.example.com",
            vm_auth_key="vmauth123",
        )

    def test_range_can_have_ngfw_config(self, user, ngfw_config):
        """Range can be associated with an NGFWConfig."""
        range_obj = Range.objects.create(
            user=user,
            ngfw_enabled=True,
            ngfw_config=ngfw_config,
        )
        assert range_obj.ngfw_config == ngfw_config
        assert range_obj.ngfw_config.panorama_server == "panorama.example.com"

    def test_range_ngfw_config_defaults_to_none(self, user):
        """ngfw_config defaults to None."""
        range_obj = Range.objects.create(user=user)
        assert range_obj.ngfw_config is None

    def test_ngfw_config_set_null_on_delete(self, user, ngfw_config):
        """When NGFWConfig is deleted, Range.ngfw_config becomes NULL."""
        from mission_control.models import NGFWConfig

        range_obj = Range.objects.create(
            user=user,
            ngfw_enabled=True,
            ngfw_config=ngfw_config,
        )
        config_id = ngfw_config.pk

        # Delete the NGFWConfig
        NGFWConfig.objects.filter(pk=config_id).delete()

        # Refresh the range
        range_obj.refresh_from_db()
        assert range_obj.ngfw_config is None
        # Range still exists
        assert Range.objects.filter(pk=range_obj.pk).exists()

    def test_ngfw_config_related_name(self, user, ngfw_config):
        """NGFWConfig has a 'ranges' related_name to access associated ranges."""
        range1 = Range.objects.create(user=user, ngfw_enabled=True, ngfw_config=ngfw_config)
        range2 = Range.objects.create(user=user, ngfw_enabled=True, ngfw_config=ngfw_config)

        assert list(ngfw_config.ranges.all()) == [range2, range1]  # Default ordering is -created_at


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
