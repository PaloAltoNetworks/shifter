"""Behavior tests for Mission Control / catalog models.

Pure value-logic on a model (computed properties, ``__str__``) is exercised on
in-memory instances; anything that touches a manager/queryset is exercised
against the real database instead of mocking ``.objects``.
"""

from datetime import timedelta

import pytest
from django.db.models import DurationField, ExpressionWrapper, F
from django.utils import timezone

from cms.models import AgentConfig, OperatingSystem
from engine.models import Range
from management.models import ActivityLog, UserProfile

# ---------------------------------------------------------------------------
# OperatingSystem
# ---------------------------------------------------------------------------


class TestOperatingSystem:
    def test_str_returns_name(self):
        os = OperatingSystem(slug="test", name="Test OS", extensions=[".test"])
        assert str(os) == "Test OS"

    @pytest.fixture
    def os_row(self, db):
        return OperatingSystem.objects.create(slug="exttest", name="Ext Test", extensions=[".widget"])

    def test_get_for_extension_finds_match(self, os_row):
        assert OperatingSystem.get_for_extension(".widget") == os_row

    def test_get_for_extension_case_insensitive(self, os_row):
        assert OperatingSystem.get_for_extension(".WIDGET") == os_row

    def test_get_for_extension_adds_dot_if_missing(self, os_row):
        assert OperatingSystem.get_for_extension("widget") == os_row

    def test_get_for_extension_returns_none_for_unknown(self, db):
        assert OperatingSystem.get_for_extension(".no-such-ext") is None


# ---------------------------------------------------------------------------
# UserProfile
# ---------------------------------------------------------------------------


class TestUserProfile:
    @pytest.fixture
    def profile(self, db, django_user_model):
        user = django_user_model.objects.create_user(username="prof@example.com", email="prof@example.com")
        # A profile is auto-created for each user via signal.
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile

    def test_str_includes_user_email(self, profile):
        assert "prof@example.com" in str(profile)

    def test_is_deleted_false_by_default(self, profile):
        assert profile.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self, profile):
        profile.deleted_at = timezone.now()
        profile.save(update_fields=["deleted_at"])
        assert profile.is_deleted is True


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------


class TestAgentConfig:
    @pytest.fixture
    def agent(self, db, make_agent, django_user_model):
        user = django_user_model.objects.create_user(
            username="agentowner2@example.com", email="agentowner2@example.com"
        )
        return make_agent(user, name="Test Agent")

    def test_str_returns_name_and_os(self, agent):
        assert str(agent) == "Test Agent (Windows)"

    def test_is_deleted_false_by_default(self, agent):
        assert agent.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self, agent):
        agent.deleted_at = timezone.now()
        agent.save(update_fields=["deleted_at"])
        assert agent.is_deleted is True

    def test_active_for_user_returns_only_user_active_agents(self, db, make_agent, django_user_model):
        owner = django_user_model.objects.create_user(username="afu-owner@example.com", email="afu-owner@example.com")
        other = django_user_model.objects.create_user(username="afu-other@example.com", email="afu-other@example.com")
        keep = make_agent(owner, name="Keep")
        deleted = make_agent(owner, name="Deleted")
        deleted.deleted_at = timezone.now()
        deleted.save(update_fields=["deleted_at"])
        make_agent(other, name="Other")

        result = list(AgentConfig.active_for_user(owner))
        assert result == [keep]


# ---------------------------------------------------------------------------
# Range value-logic properties (pure, in-memory)
# ---------------------------------------------------------------------------


class TestRangeProperties:
    def test_str_with_scenario(self):
        range_obj = Range(id=42, range_config={"scenario_id": "ad_attack_lab"})
        assert "ad_attack_lab" in str(range_obj)
        assert "42" in str(range_obj)

    def test_str_without_range_config(self):
        assert "unknown" in str(Range(range_config=None))

    def test_kali_private_ip_returns_attacker_ip(self):
        range_obj = Range(
            provisioned_instances=[
                {"role": "attacker", "os": "kali", "private_ip": "10.1.5.10"},
                {"role": "victim", "os": "ubuntu", "private_ip": "10.1.5.20"},
            ]
        )
        assert range_obj.kali_private_ip == "10.1.5.10"

    def test_kali_private_ip_none_when_empty(self):
        assert Range(provisioned_instances=None).kali_private_ip is None

    def test_kali_private_ip_none_when_no_attacker(self):
        range_obj = Range(provisioned_instances=[{"role": "victim", "private_ip": "10.1.5.20"}])
        assert range_obj.kali_private_ip is None

    def test_kali_private_ip_none_when_attacker_missing_ip(self):
        range_obj = Range(provisioned_instances=[{"role": "attacker", "os": "kali"}])
        assert range_obj.kali_private_ip is None

    def test_victim_private_ip_returns_first_victim_ip(self):
        range_obj = Range(
            provisioned_instances=[
                {"role": "attacker", "private_ip": "10.1.5.10"},
                {"role": "victim", "private_ip": "10.1.5.20"},
                {"role": "victim", "private_ip": "10.1.5.30"},
            ]
        )
        assert range_obj.victim_private_ip == "10.1.5.20"

    def test_victim_private_ip_none_when_no_victims(self):
        range_obj = Range(provisioned_instances=[{"role": "attacker", "private_ip": "10.1.5.10"}])
        assert range_obj.victim_private_ip is None

    def test_gwlb_endpoint_id_defaults_to_empty(self):
        assert Range().gwlb_endpoint_id == ""

    def test_standup_duration_returns_timedelta_when_ready(self):
        created = timezone.now()
        range_obj = Range()
        range_obj.created_at = created
        range_obj.ready_at = created + timedelta(minutes=3, seconds=30)
        assert range_obj.standup_duration == timedelta(minutes=3, seconds=30)

    def test_standup_duration_none_when_not_ready(self):
        range_obj = Range()
        range_obj.created_at = timezone.now()
        range_obj.ready_at = None
        assert range_obj.standup_duration is None


# ---------------------------------------------------------------------------
# Range standup-duration ORM annotation (real rows)
# ---------------------------------------------------------------------------


class TestRangeStandupAnnotation:
    def test_annotation_filters_slow_ranges(self, db, django_user_model):
        user = django_user_model.objects.create_user(username="standup@example.com", email="standup@example.com")
        now = timezone.now()
        fast = Range.objects.create(user=user, status=Range.Status.READY)
        Range.objects.filter(pk=fast.pk).update(created_at=now, ready_at=now + timedelta(minutes=1))
        slow = Range.objects.create(user=user, status=Range.Status.READY)
        Range.objects.filter(pk=slow.pk).update(created_at=now, ready_at=now + timedelta(minutes=10))

        slow_pks = set(
            Range.objects.annotate(
                computed_standup=ExpressionWrapper(F("ready_at") - F("created_at"), output_field=DurationField())
            )
            .filter(computed_standup__gt=timedelta(minutes=5))
            .values_list("pk", flat=True)
        )
        assert slow.pk in slow_pks
        assert fast.pk not in slow_pks


# ---------------------------------------------------------------------------
# ActivityLog
# ---------------------------------------------------------------------------


class TestActivityLog:
    def test_log_creates_entry(self, db, django_user_model):
        user = django_user_model.objects.create_user(username="act@example.com", email="act@example.com")
        log = ActivityLog.log("test_action", user=user)
        assert log.pk is not None
        assert log.action == "test_action"
        assert log.user == user
        assert ActivityLog.objects.filter(pk=log.pk, action="test_action").exists()

    def test_log_stores_metadata(self, db):
        log = ActivityLog.log("test_action", foo="bar", count=42)
        log.refresh_from_db()
        assert log.metadata == {"foo": "bar", "count": 42}

    def test_log_works_without_user(self, db):
        log = ActivityLog.log("anonymous_action")
        assert log.user is None
        assert log.action == "anonymous_action"

    def test_str_with_user(self, db, django_user_model):
        user = django_user_model.objects.create_user(username="actstr@example.com", email="actstr@example.com")
        log = ActivityLog.log("test_action", user=user)
        assert "actstr@example.com" in str(log)
        assert "test_action" in str(log)

    def test_str_without_user(self, db):
        log = ActivityLog.log("test_action")
        assert "anonymous" in str(log)
