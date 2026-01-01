"""Unit tests for Mission Control models."""

import pytest
from django.contrib.auth import get_user_model

from management.models import ActivityLog, UserProfile
from mission_control.models import (
    AgentConfig,
    OperatingSystem,
    Range,
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
    # Note: Old per-range NGFW fields (ngfw_enabled, ngfw_instance_id, ngfw_untrust_ip, ngfw_trust_ip)
    # were removed in favor of the UserNGFW model with Range.ngfw FK (issue #412)

    def test_ngfw_defaults_to_none(self, user):
        """ngfw FK defaults to None."""
        range_obj = Range.objects.create(user=user)
        assert range_obj.ngfw is None

    def test_gwlb_endpoint_id_defaults_to_empty(self, user):
        """gwlb_endpoint_id defaults to empty string."""
        range_obj = Range.objects.create(user=user)
        assert range_obj.gwlb_endpoint_id == ""

    # --- standup_duration property tests ---

    def test_standup_duration_returns_timedelta_when_ready(self, user):
        """standup_duration returns timedelta when range is ready."""
        from datetime import timedelta

        from django.utils import timezone

        created = timezone.now()
        ready = created + timedelta(minutes=3, seconds=30)

        range_obj = Range.objects.create(user=user)
        # Override auto_now_add by updating directly
        Range.objects.filter(pk=range_obj.pk).update(created_at=created, ready_at=ready)
        range_obj.refresh_from_db()

        assert range_obj.standup_duration == timedelta(minutes=3, seconds=30)

    def test_standup_duration_returns_none_when_not_ready(self, user):
        """standup_duration returns None when ready_at is not set."""
        range_obj = Range.objects.create(user=user)
        assert range_obj.standup_duration is None

    def test_standup_duration_returns_none_when_created_at_missing(self, user):
        """standup_duration returns None when created_at is somehow None."""
        from django.utils import timezone

        range_obj = Range.objects.create(user=user)
        Range.objects.filter(pk=range_obj.pk).update(ready_at=timezone.now())
        range_obj.refresh_from_db()
        # Force created_at to None (shouldn't happen in practice but defensive)
        range_obj.created_at = None

        assert range_obj.standup_duration is None

    def test_standup_duration_queryset_annotation(self, user):
        """standup_duration can be computed via ORM annotation for filtering."""
        from datetime import timedelta

        from django.db.models import DurationField, ExpressionWrapper, F
        from django.utils import timezone

        # Create a fast range (2 min)
        fast_range = Range.objects.create(user=user)
        fast_created = timezone.now() - timedelta(hours=1)
        fast_ready = fast_created + timedelta(minutes=2)
        Range.objects.filter(pk=fast_range.pk).update(created_at=fast_created, ready_at=fast_ready)

        # Create a slow range (10 min)
        slow_range = Range.objects.create(user=user)
        slow_created = timezone.now() - timedelta(hours=2)
        slow_ready = slow_created + timedelta(minutes=10)
        Range.objects.filter(pk=slow_range.pk).update(created_at=slow_created, ready_at=slow_ready)

        # Create a pending range (no ready_at)
        pending_range = Range.objects.create(user=user)

        # Query ranges with standup > 5 minutes
        slow_ranges = (
            Range.objects.annotate(
                computed_standup=ExpressionWrapper(F("ready_at") - F("created_at"), output_field=DurationField())
            )
            .filter(computed_standup__gt=timedelta(minutes=5))
            .values_list("pk", flat=True)
        )

        assert slow_range.pk in slow_ranges
        assert fast_range.pk not in slow_ranges
        assert pending_range.pk not in slow_ranges


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
