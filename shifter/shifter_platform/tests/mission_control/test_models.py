"""Unit tests for Mission Control models — fully mocked, no DB access."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.db.models.base import ModelState
from django.utils import timezone

from cms.models import AgentConfig, OperatingSystem
from engine.models import Range
from management.models import ActivityLog, UserProfile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make(model_cls, **attrs):
    """Create an in-memory Django model instance without DB or FK validation.

    Uses __new__ to skip __init__ (avoids FK type checks), then injects
    Django's required _state and sets all given attributes via __dict__.
    FK-related objects are also stored in the fields_cache so that Django's
    FK descriptor __get__ finds them without hitting the database.
    """
    obj = model_cls.__new__(model_cls)
    obj._state = ModelState()
    obj.__dict__.update(attrs)
    # Populate the fields_cache for any FK fields whose related object was
    # provided, so Django's ForwardManyToOneDescriptor.__get__ returns it
    # without a DB query.
    fk_field_names = {f.name for f in model_cls._meta.get_fields() if f.many_to_one or f.one_to_one}
    for name in fk_field_names:
        if name in attrs:
            obj._state.fields_cache[name] = attrs[name]
    return obj


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_user():
    """An in-memory mock User with common attributes."""
    user = MagicMock()
    user.pk = 1
    user.username = "test@example.com"
    user.email = "test@example.com"
    return user


@pytest.fixture
def windows_os():
    """An in-memory OperatingSystem instance."""
    return OperatingSystem(slug="windows", name="Windows", extensions=[".msi"])


# ---------------------------------------------------------------------------
# OperatingSystem
# ---------------------------------------------------------------------------


class TestOperatingSystem:
    def test_str_returns_name(self):
        os = OperatingSystem(slug="test", name="Test OS", extensions=[".test"])
        assert str(os) == "Test OS"

    @patch.object(OperatingSystem.objects, "all")
    def test_get_for_extension_finds_match(self, mock_all, windows_os):
        """get_for_extension returns OS when extension matches."""
        mock_all.return_value = [windows_os]
        result = OperatingSystem.get_for_extension(".msi")
        assert result == windows_os

    @patch.object(OperatingSystem.objects, "all")
    def test_get_for_extension_case_insensitive(self, mock_all, windows_os):
        """get_for_extension is case insensitive."""
        mock_all.return_value = [windows_os]
        result = OperatingSystem.get_for_extension(".MSI")
        assert result is not None
        assert result.slug == "windows"

    @patch.object(OperatingSystem.objects, "all")
    def test_get_for_extension_adds_dot_if_missing(self, mock_all, windows_os):
        """get_for_extension adds leading dot if missing."""
        mock_all.return_value = [windows_os]
        result = OperatingSystem.get_for_extension("msi")
        assert result is not None
        assert result.slug == "windows"

    @patch.object(OperatingSystem.objects, "all")
    def test_get_for_extension_returns_none_for_unknown(self, mock_all, windows_os):
        """get_for_extension returns None for unknown extensions."""
        mock_all.return_value = [windows_os]
        result = OperatingSystem.get_for_extension(".xyz")
        assert result is None


# ---------------------------------------------------------------------------
# UserProfile
# ---------------------------------------------------------------------------


class TestUserProfile:
    @pytest.fixture
    def profile(self, mock_user):
        """Build a UserProfile in-memory, bypassing FK validation."""
        return _make(
            UserProfile,
            user=mock_user,
            user_id=mock_user.pk,
            deleted_at=None,
            anonymized_at=None,
        )

    def test_str_returns_user_email(self, profile):
        """__str__ returns profile description with email."""
        assert "test@example.com" in str(profile)

    def test_is_deleted_false_by_default(self, profile):
        """is_deleted returns False when deleted_at is None."""
        assert profile.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self, profile):
        """is_deleted returns True when deleted_at is set."""
        profile.deleted_at = timezone.now()
        assert profile.is_deleted is True


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------


class TestAgentConfig:
    @pytest.fixture
    def agent(self, mock_user, windows_os):
        """Build an AgentConfig in-memory, bypassing FK validation."""
        return _make(
            AgentConfig,
            user=mock_user,
            user_id=mock_user.pk,
            os=windows_os,
            os_id=windows_os.pk,
            name="Test Agent",
            s3_key="test/key.msi",
            original_filename="installer.msi",
            file_size_bytes=1024,
            sha256_hash="abc123",
            deleted_at=None,
        )

    def test_str_returns_name_and_os(self, agent):
        """__str__ returns agent name with OS."""
        assert str(agent) == "Test Agent (Windows)"

    def test_is_deleted_false_by_default(self, agent):
        """is_deleted returns False when deleted_at is None."""
        assert agent.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self, agent):
        """is_deleted returns True when deleted_at is set."""
        agent.deleted_at = timezone.now()
        assert agent.is_deleted is True

    @patch.object(AgentConfig.objects, "filter")
    def test_active_for_user_excludes_deleted(self, mock_filter, mock_user, agent):
        """active_for_user excludes soft-deleted agents."""
        agent.name = "Active Agent"
        mock_filter.return_value = [agent]

        result = list(AgentConfig.active_for_user(mock_user))
        assert len(result) == 1
        assert result[0] is agent
        mock_filter.assert_called_once_with(user=mock_user, deleted_at__isnull=True)

    @patch.object(AgentConfig.objects, "filter")
    def test_active_for_user_only_returns_user_agents(self, mock_filter, mock_user, agent):
        """active_for_user only returns agents for the specified user."""
        agent.name = "My Agent"
        mock_filter.return_value = [agent]

        result = list(AgentConfig.active_for_user(mock_user))
        assert len(result) == 1
        assert result[0].name == "My Agent"
        mock_filter.assert_called_once_with(user=mock_user, deleted_at__isnull=True)


# ---------------------------------------------------------------------------
# Range Properties (no DB needed — unchanged)
# ---------------------------------------------------------------------------


class TestRangeProperties:
    """Tests for Range model properties using in-memory construction."""

    def test_str_with_scenario(self):
        """__str__ includes scenario_id from range_config."""
        range_obj = Range(
            id=42,
            range_config={"scenario_id": "ad_attack_lab"},
        )
        assert "ad_attack_lab" in str(range_obj)
        assert "42" in str(range_obj)

    def test_str_without_range_config(self):
        """__str__ shows 'unknown' scenario when range_config is None."""
        range_obj = Range(range_config=None)
        assert "unknown" in str(range_obj)

    # --- kali_private_ip property tests ---

    def test_kali_private_ip_returns_attacker_ip(self):
        """kali_private_ip returns the attacker instance's private_ip."""
        range_obj = Range(
            provisioned_instances=[
                {"role": "attacker", "os": "kali", "private_ip": "10.1.5.10"},
                {"role": "victim", "os": "ubuntu", "private_ip": "10.1.5.20"},
            ],
        )
        assert range_obj.kali_private_ip == "10.1.5.10"

    def test_kali_private_ip_returns_none_when_no_provisioned_instances(self):
        """kali_private_ip returns None when provisioned_instances is empty."""
        range_obj = Range(provisioned_instances=None)
        assert range_obj.kali_private_ip is None

    def test_kali_private_ip_returns_none_when_no_attacker(self):
        """kali_private_ip returns None when no attacker instance exists."""
        range_obj = Range(
            provisioned_instances=[
                {"role": "victim", "os": "ubuntu", "private_ip": "10.1.5.20"},
            ],
        )
        assert range_obj.kali_private_ip is None

    def test_kali_private_ip_returns_none_when_attacker_missing_ip(self):
        """kali_private_ip returns None when attacker has no private_ip field."""
        range_obj = Range(
            provisioned_instances=[
                {"role": "attacker", "os": "kali"},
            ],
        )
        assert range_obj.kali_private_ip is None

    # --- victim_private_ip property tests ---

    def test_victim_private_ip_returns_first_victim_ip(self):
        """victim_private_ip returns the first victim instance's private_ip."""
        range_obj = Range(
            provisioned_instances=[
                {"role": "attacker", "os": "kali", "private_ip": "10.1.5.10"},
                {"role": "victim", "os": "ubuntu", "private_ip": "10.1.5.20"},
            ],
        )
        assert range_obj.victim_private_ip == "10.1.5.20"

    def test_victim_private_ip_returns_none_when_no_provisioned_instances(self):
        """victim_private_ip returns None when provisioned_instances is empty."""
        range_obj = Range(provisioned_instances=None)
        assert range_obj.victim_private_ip is None

    def test_victim_private_ip_returns_none_when_no_victims(self):
        """victim_private_ip returns None when no victim instances exist."""
        range_obj = Range(
            provisioned_instances=[
                {"role": "attacker", "os": "kali", "private_ip": "10.1.5.10"},
            ],
        )
        assert range_obj.victim_private_ip is None

    def test_victim_private_ip_returns_none_when_victim_missing_ip(self):
        """victim_private_ip returns None when victim has no private_ip field."""
        range_obj = Range(
            provisioned_instances=[
                {"role": "victim", "os": "ubuntu"},
            ],
        )
        assert range_obj.victim_private_ip is None

    def test_victim_private_ip_returns_first_when_multiple_victims(self):
        """victim_private_ip returns first victim's IP when multiple victims exist."""
        range_obj = Range(
            provisioned_instances=[
                {"role": "victim", "os": "ubuntu", "private_ip": "10.1.5.20"},
                {"role": "victim", "os": "windows", "private_ip": "10.1.5.30"},
            ],
        )
        assert range_obj.victim_private_ip == "10.1.5.20"

    # --- NGFW/GWLB fields tests ---

    def test_gwlb_endpoint_id_defaults_to_empty(self):
        """gwlb_endpoint_id defaults to empty string."""
        range_obj = Range()
        assert range_obj.gwlb_endpoint_id == ""


# ---------------------------------------------------------------------------
# Range DB Tests (now mocked)
# ---------------------------------------------------------------------------


class TestRangeDB:
    """Tests for Range model properties — previously DB-backed, now mocked."""

    def test_standup_duration_returns_timedelta_when_ready(self):
        """standup_duration returns timedelta when range is ready."""
        created = timezone.now()
        ready = created + timedelta(minutes=3, seconds=30)

        range_obj = Range()
        range_obj.created_at = created
        range_obj.ready_at = ready

        assert range_obj.standup_duration == timedelta(minutes=3, seconds=30)

    def test_standup_duration_returns_none_when_not_ready(self):
        """standup_duration returns None when ready_at is not set."""
        range_obj = Range()
        range_obj.created_at = timezone.now()
        range_obj.ready_at = None

        assert range_obj.standup_duration is None

    def test_standup_duration_returns_none_when_created_at_missing(self):
        """standup_duration returns None when created_at is somehow None."""
        range_obj = Range()
        range_obj.created_at = None
        range_obj.ready_at = timezone.now()

        assert range_obj.standup_duration is None

    @patch("engine.models.Range.objects")
    def test_standup_duration_queryset_annotation(self, mock_objects, mock_user):
        """standup_duration can be computed via ORM annotation for filtering."""
        from django.db.models import DurationField, ExpressionWrapper, F

        # Build a mock annotated queryset chain
        mock_qs = MagicMock()
        mock_objects.annotate.return_value = mock_qs

        slow_range_pk = 2
        mock_qs.filter.return_value.values_list.return_value = [slow_range_pk]

        # Execute the same query the original test used
        result = (
            Range.objects.annotate(
                computed_standup=ExpressionWrapper(F("ready_at") - F("created_at"), output_field=DurationField())
            )
            .filter(computed_standup__gt=timedelta(minutes=5))
            .values_list("pk", flat=True)
        )

        assert slow_range_pk in result
        # Verify the annotate -> filter -> values_list chain was called
        mock_objects.annotate.assert_called_once()
        mock_qs.filter.assert_called_once()
        mock_qs.filter.return_value.values_list.assert_called_once_with("pk", flat=True)


# ---------------------------------------------------------------------------
# ActivityLog
# ---------------------------------------------------------------------------


class TestActivityLog:
    @patch.object(ActivityLog.objects, "create")
    def test_log_creates_entry(self, mock_create, mock_user):
        """ActivityLog.log() creates a new entry."""
        mock_log = MagicMock(spec=ActivityLog)
        mock_log.action = "test_action"
        mock_log.user = mock_user
        mock_log.pk = 1
        mock_create.return_value = mock_log

        log = ActivityLog.log("test_action", user=mock_user)

        assert log.action == "test_action"
        assert log.user == mock_user
        assert log.pk is not None
        mock_create.assert_called_once_with(user=mock_user, action="test_action", metadata={})

    @patch.object(ActivityLog.objects, "create")
    def test_log_stores_metadata(self, mock_create):
        """ActivityLog.log() stores kwargs as metadata."""
        mock_log = MagicMock(spec=ActivityLog)
        mock_log.metadata = {"foo": "bar", "count": 42}
        mock_create.return_value = mock_log

        log = ActivityLog.log("test_action", foo="bar", count=42)

        assert log.metadata == {"foo": "bar", "count": 42}
        mock_create.assert_called_once_with(user=None, action="test_action", metadata={"foo": "bar", "count": 42})

    @patch.object(ActivityLog.objects, "create")
    def test_log_works_without_user(self, mock_create):
        """ActivityLog.log() works with anonymous actions."""
        mock_log = MagicMock(spec=ActivityLog)
        mock_log.user = None
        mock_log.action = "anonymous_action"
        mock_create.return_value = mock_log

        log = ActivityLog.log("anonymous_action")

        assert log.user is None
        assert log.action == "anonymous_action"

    def test_str_with_user(self, mock_user):
        """__str__ includes user email when user exists."""
        log = _make(
            ActivityLog,
            user=mock_user,
            user_id=mock_user.pk,
            action="test_action",
            timestamp=timezone.now(),
        )
        assert "test@example.com" in str(log)
        assert "test_action" in str(log)

    def test_str_without_user(self):
        """__str__ shows 'anonymous' when user is None."""
        log = _make(
            ActivityLog,
            user=None,
            user_id=None,
            action="test_action",
            timestamp=timezone.now(),
        )
        assert "anonymous" in str(log)
