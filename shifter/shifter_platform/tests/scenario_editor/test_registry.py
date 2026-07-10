"""Tests for the scenario registry."""

import pytest
from django.contrib.auth import get_user_model

from cms.models import AcesPackageSource, Scenario, ScenarioMetadata
from cms.scenarios.registry import (
    ScenarioWorkflow,
    _aces_launchable,
    check_scenario_access,
    get_catalog_entry,
    get_scenario_detail,
    is_default_scenario,
    is_scenario_launchable,
    list_all_scenarios,
    list_launchable_scenarios,
    load_demo_scenario_template,
    load_scenario_template,
)

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staff@example.com",
        email="staff@example.com",
        password="testpass",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="regular@example.com",
        email="regular@example.com",
        password="testpass",
        is_staff=False,
    )


@pytest.fixture
def valid_definition():
    return {
        "instances": [
            {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
            {"name": "Target", "role": "victim", "os_type": "windows", "xdr_agent": True},
        ],
        "subnets": [{"name": "core", "instances": ["Attacker", "Target"]}],
        "ngfw": False,
    }


@pytest.fixture
def custom_scenario(staff_user, valid_definition):
    return Scenario.objects.create(
        scenario_id="custom-test",
        name="Custom Test",
        description="A custom test scenario",
        definition=valid_definition,
        created_by=staff_user,
        updated_by=staff_user,
    )


class TestIsDefaultScenario:
    def test_yaml_scenario_is_default(self):
        assert is_default_scenario("basic") is True

    def test_nonexistent_is_not_default(self):
        assert is_default_scenario("nonexistent") is False

    def test_custom_scenario_is_not_default(self, custom_scenario):
        assert is_default_scenario("custom-test") is False


class TestListAllScenarios:
    def test_returns_yaml_defaults(self, db):
        """Should include YAML defaults even with no DB scenarios."""
        result = list_all_scenarios()
        ids = [s["id"] for s in result]
        assert "basic" in ids
        assert "ad_attack_lab" in ids

    def test_includes_custom_scenarios(self, custom_scenario):
        result = list_all_scenarios()
        ids = [s["id"] for s in result]
        assert "custom-test" in ids

    def test_custom_marked_as_not_default(self, custom_scenario):
        result = list_all_scenarios()
        custom = next(s for s in result if s["id"] == "custom-test")
        assert custom["is_default"] is False

    def test_yaml_marked_as_default(self, db):
        result = list_all_scenarios()
        basic = next(s for s in result if s["id"] == "basic")
        assert basic["is_default"] is True

    def test_metadata_overlay_applied(self, staff_user, db):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            staff_only=True,
            updated_by=staff_user,
        )
        result = list_all_scenarios()
        basic = next(s for s in result if s["id"] == "basic")
        assert basic["enabled"] is False
        assert basic["staff_only"] is True

    def test_non_staff_sees_only_enabled_non_staff(self, staff_user, regular_user):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            updated_by=staff_user,
        )
        result = list_all_scenarios(user=regular_user)
        ids = [s["id"] for s in result]
        # 'basic' is disabled, should not appear for regular user
        assert "basic" not in ids
        # other enabled scenarios should still appear
        assert "ad_attack_lab" in ids

    def test_staff_only_hidden_from_regular(self, staff_user, regular_user):
        ScenarioMetadata.objects.create(
            scenario_id="ad_attack_lab",
            staff_only=True,
            updated_by=staff_user,
        )
        result = list_all_scenarios(user=regular_user)
        ids = [s["id"] for s in result]
        assert "ad_attack_lab" not in ids

    def test_no_filtering_with_none_user(self, staff_user, db):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            updated_by=staff_user,
        )
        # user=None means no filtering (admin/staff view)
        result = list_all_scenarios(user=None)
        ids = [s["id"] for s in result]
        assert "basic" in ids

    def test_sorted_by_name(self, db):
        result = list_all_scenarios()
        names = [s["name"] for s in result]
        assert names == sorted(names)

    def test_includes_agent_requirements(self, db):
        result = list_all_scenarios()
        for scenario in result:
            assert "agent_requirements" in scenario

    def test_soft_deleted_scenarios_excluded(self, custom_scenario):
        """Soft-deleted custom scenarios should not appear."""
        from django.utils import timezone

        Scenario.objects.filter(pk=custom_scenario.pk).update(deleted_at=timezone.now())
        result = list_all_scenarios()
        ids = [s["id"] for s in result]
        assert "custom-test" not in ids


def _make_aces_source(staff_user, scenario_id, **overrides):
    fields = {
        "scenario_id": scenario_id,
        "contract_kind": "aces",
        "contract_profile": "shifter",
        "package_ref": "scenario-dev/polaris/content-packages/polaris",
        "package_version": "1.0.0",
        "package_digest": "sha256:" + "a" * 64,
        "registered_by": staff_user,
    }
    fields.update(overrides)
    return AcesPackageSource.objects.create(**fields)


class TestAcesPackageSourceProjection:
    def test_aces_entry_appears(self, staff_user):
        _make_aces_source(staff_user, "polaris-aces", conformance_status="passed")
        result = list_all_scenarios()
        entry = next(s for s in result if s["id"] == "polaris-aces")
        assert entry["is_default"] is False
        assert entry["scenario_type"] == "aces"
        assert entry["source_kind"] == "repo"
        assert entry["contract_kind"] == "aces"
        # Review-only by default: no runtime adapter is wired yet.
        assert entry["launchable"] is False
        assert "agent_requirements" in entry
        assert entry["name"] == "polaris-aces"

    def test_projection_stays_sorted_by_name(self, staff_user):
        _make_aces_source(staff_user, "polaris-aces")
        result = list_all_scenarios()
        names = [s["name"] for s in result]
        assert names == sorted(names)

    def test_launchable_false_when_not_conformant(self, staff_user):
        _make_aces_source(staff_user, "polaris-pending", conformance_status="pending")
        result = list_all_scenarios()
        entry = next(s for s in result if s["id"] == "polaris-pending")
        assert entry["launchable"] is False

    def test_no_shadow_of_yaml_default(self, staff_user):
        _make_aces_source(staff_user, "basic")
        result = list_all_scenarios()
        basic = [s for s in result if s["id"] == "basic"]
        assert len(basic) == 1
        assert basic[0]["is_default"] is True
        assert basic[0].get("scenario_type") != "aces"

    def test_no_shadow_of_active_db_custom(self, custom_scenario, staff_user):
        _make_aces_source(staff_user, "custom-test")
        result = list_all_scenarios()
        entries = [s for s in result if s["id"] == "custom-test"]
        assert len(entries) == 1
        # The surviving entry is the DB custom (demo), not the ACES row.
        assert entries[0]["is_default"] is False
        assert entries[0].get("scenario_type") != "aces"

    def test_metadata_overlay_reuse(self, staff_user, regular_user):
        _make_aces_source(staff_user, "polaris-aces", conformance_status="passed")
        ScenarioMetadata.objects.create(
            scenario_id="polaris-aces",
            enabled=False,
            staff_only=True,
            updated_by=staff_user,
        )
        entry = next(s for s in list_all_scenarios(user=None) if s["id"] == "polaris-aces")
        assert entry["enabled"] is False
        assert entry["staff_only"] is True
        # Regular users do not see a disabled / staff-only ACES entry.
        ids = [s["id"] for s in list_all_scenarios(user=regular_user)]
        assert "polaris-aces" not in ids

    def test_access_and_launchability_independent(self, staff_user, aces_launch_adapter):
        _make_aces_source(staff_user, "polaris-split", conformance_status="passed")
        ScenarioMetadata.objects.create(
            scenario_id="polaris-split",
            enabled=False,
            updated_by=staff_user,
        )
        entry = next(s for s in list_all_scenarios(user=None) if s["id"] == "polaris-split")
        # Access (metadata) and launchability are separate axes: disabled for
        # access yet launchable once a runtime adapter exists.
        assert entry["enabled"] is False
        assert entry["launchable"] is True


class TestAcesPackageSourceNotLaunchable:
    """ACES package-source ids are fail-closed at the launch chokepoint.

    In this slice there is no ACES launch adapter (owned by #1253), so an ACES
    catalog entry is visible/selectable in the projection but MUST NOT resolve
    through the launch path that ``cms.services.create_range`` and the CTF
    hydrator both funnel through (``load_scenario_template`` /
    ``load_demo_scenario_template``). It resolves only DB ``Scenario`` rows and
    YAML defaults, so an ACES-only id raises ``ValueError`` — it cannot launch,
    regardless of its projected ``launchable`` flag.
    """

    def test_conformant_aces_id_not_resolvable_for_launch(self, staff_user):
        # Even a conformance-passed (launchable=True in the projection) ACES id
        # is not launchable while no launch adapter exists.
        _make_aces_source(staff_user, "polaris-aces", conformance_status="passed")
        with pytest.raises(ValueError, match="not found"):
            load_scenario_template("polaris-aces")
        with pytest.raises(ValueError, match="not found"):
            load_demo_scenario_template("polaris-aces")

    def test_pending_aces_id_not_resolvable_for_launch(self, staff_user):
        _make_aces_source(staff_user, "polaris-pending", conformance_status="pending")
        with pytest.raises(ValueError, match="not found"):
            load_scenario_template("polaris-pending")


@pytest.fixture
def aces_launch_adapter(monkeypatch):
    """Simulate a wired ACES runtime adapter for the ('aces','shifter') profile.

    Launchability is gated on a runtime hydration adapter existing; none is wired
    yet, so ACES entries are review-only by default. Tests that exercise the
    positive launchability path use this fixture to simulate the future adapter.
    """
    monkeypatch.setattr(
        "cms.scenarios.registry._LAUNCH_ADAPTER_CONTRACT_PROFILES",
        frozenset({("aces", "shifter")}),
    )


class TestLaunchability:
    def test_legacy_entries_are_launchable(self, db):
        entry = next(s for s in list_all_scenarios() if s["id"] == "basic")
        assert entry["launchable"] is True

    def test_aces_review_only_without_adapter(self, staff_user):
        # No runtime adapter is wired, so even a conformant ACES entry is
        # review-only (not launchable) — it must not be exposed to launch flows.
        _make_aces_source(staff_user, "polaris-aces", conformance_status="passed")
        assert get_catalog_entry("polaris-aces")["launchable"] is False

    def test_conformant_supported_aces_launchable_with_adapter(self, staff_user, aces_launch_adapter):
        _make_aces_source(staff_user, "polaris-aces", conformance_status="passed")
        assert get_catalog_entry("polaris-aces")["launchable"] is True

    def test_pending_aces_not_launchable_with_adapter(self, staff_user, aces_launch_adapter):
        _make_aces_source(staff_user, "polaris-pending", conformance_status="pending")
        assert get_catalog_entry("polaris-pending")["launchable"] is False

    def test_unsupported_profile_not_launchable_with_adapter(self, staff_user, aces_launch_adapter):
        # profile is a free single-line string at persistence, but only supported
        # profiles (with a wired adapter) are launchable.
        _make_aces_source(staff_user, "polaris-badprofile", conformance_status="passed", contract_profile="polaris")
        assert get_catalog_entry("polaris-badprofile")["launchable"] is False

    def test_invalid_digest_fails_closed_with_adapter(self, staff_user, aces_launch_adapter):
        # Build (unsaved) a row that bypasses the persistence validator to prove
        # launchability re-validates refs/digests fail-closed.
        from cms.models import AcesPackageSource

        row = AcesPackageSource(
            scenario_id="polaris-baddigest",
            contract_kind="aces",
            contract_profile="shifter",
            source_kind="repo",
            package_ref="pkg",
            package_version="1.0.0",
            package_digest="not-a-sha256",
            conformance_status="passed",
            registered_by=staff_user,
        )
        assert _aces_launchable(row, known_legacy_ids=set()) is False

    def test_list_launchable_excludes_aces_without_adapter(self, staff_user):
        _make_aces_source(staff_user, "polaris-ok", conformance_status="passed")
        _make_aces_source(staff_user, "polaris-pending", conformance_status="pending")
        ids = [s["id"] for s in list_launchable_scenarios(workflow=ScenarioWorkflow.RANGE_LAUNCH)]
        assert "polaris-ok" not in ids  # review-only: no adapter wired
        assert "polaris-pending" not in ids
        assert "basic" in ids  # legacy stays launchable

    def test_list_launchable_includes_conformant_aces_with_adapter(self, staff_user, aces_launch_adapter):
        _make_aces_source(staff_user, "polaris-ok", conformance_status="passed")
        _make_aces_source(staff_user, "polaris-pending", conformance_status="pending")
        ids = [s["id"] for s in list_launchable_scenarios(workflow=ScenarioWorkflow.RANGE_LAUNCH)]
        assert "polaris-ok" in ids
        assert "polaris-pending" not in ids
        assert "basic" in ids

    def test_staff_review_includes_non_launchable_aces(self, staff_user):
        _make_aces_source(staff_user, "polaris-pending", conformance_status="pending")
        ids = [s["id"] for s in list_launchable_scenarios(user=None, workflow=ScenarioWorkflow.STAFF_REVIEW)]
        assert "polaris-pending" in ids

    def test_is_scenario_launchable_without_adapter(self, staff_user):
        _make_aces_source(staff_user, "polaris-ok", conformance_status="passed")
        assert is_scenario_launchable("polaris-ok") is False  # review-only
        assert is_scenario_launchable("basic") is True  # legacy launchable
        assert is_scenario_launchable("does-not-exist") is False

    def test_is_scenario_launchable_with_adapter(self, staff_user, aces_launch_adapter):
        _make_aces_source(staff_user, "polaris-ok", conformance_status="passed")
        _make_aces_source(staff_user, "polaris-pending", conformance_status="pending")
        assert is_scenario_launchable("polaris-ok") is True
        assert is_scenario_launchable("polaris-pending") is False

    def test_get_catalog_entry_unknown_is_none(self, db):
        assert get_catalog_entry("does-not-exist") is None


class TestGetScenarioDetail:
    def test_get_yaml_default(self, db):
        detail = get_scenario_detail("basic")
        assert detail["id"] == "basic"
        assert detail["name"] == "Basic Range"
        assert detail["is_default"] is True

    def test_get_custom_scenario(self, custom_scenario):
        detail = get_scenario_detail("custom-test")
        assert detail["id"] == "custom-test"
        assert detail["is_default"] is False

    def test_not_found_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            get_scenario_detail("nonexistent")

    def test_metadata_applied(self, staff_user, db):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            staff_only=True,
            updated_by=staff_user,
        )
        detail = get_scenario_detail("basic")
        assert detail["enabled"] is False
        assert detail["staff_only"] is True


class TestLoadScenarioTemplate:
    def test_load_yaml_default(self, db):
        template = load_scenario_template("basic")
        assert template.id == "basic"
        assert len(template.instances) == 2

    def test_load_custom_scenario(self, custom_scenario):
        template = load_scenario_template("custom-test")
        assert template.id == "custom-test"
        assert len(template.instances) == 2

    def test_db_takes_precedence(self, staff_user, valid_definition):
        """A DB Scenario sharing a YAML default's id wins in load_scenario_template.

        The projection (``_db_source_entries``) hides such collisions, but the
        direct DB-first lookup in ``load_scenario_template`` still prefers the DB
        row — proven here by a DB ``basic`` whose definition differs from the
        shipped YAML ``basic`` (instance ``Target`` vs the YAML's ``Workstation``).
        """
        from cms.models import Scenario

        Scenario.objects.create(
            scenario_id="basic",
            name="DB Basic Override",
            description="DB row colliding with the YAML 'basic' default",
            definition=valid_definition,
            created_by=staff_user,
            updated_by=staff_user,
        )
        template = load_scenario_template("basic")
        instance_names = {i.name for i in template.instances}
        assert instance_names == {"Attacker", "Target"}  # DB definition, not YAML's Workstation

    def test_not_found_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            load_scenario_template("nonexistent")


class TestCheckScenarioAccess:
    def test_staff_can_access_disabled(self, staff_user):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            updated_by=staff_user,
        )
        detail = check_scenario_access("basic", staff_user)
        assert detail["id"] == "basic"
        assert detail["enabled"] is False

    def test_staff_can_access_staff_only(self, staff_user):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            staff_only=True,
            updated_by=staff_user,
        )
        detail = check_scenario_access("basic", staff_user)
        assert detail["id"] == "basic"
        assert detail["staff_only"] is True

    def test_regular_user_blocked_from_disabled(self, staff_user, regular_user):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            enabled=False,
            updated_by=staff_user,
        )
        with pytest.raises(ValueError, match="not available"):
            check_scenario_access("basic", regular_user)

    def test_regular_user_blocked_from_staff_only(self, staff_user, regular_user):
        ScenarioMetadata.objects.create(
            scenario_id="basic",
            staff_only=True,
            updated_by=staff_user,
        )
        with pytest.raises(ValueError, match="not available"):
            check_scenario_access("basic", regular_user)

    def test_regular_user_can_access_normal_scenario(self, regular_user, db):
        detail = check_scenario_access("basic", regular_user)
        assert detail["id"] == "basic"

    def test_nonexistent_scenario_raises(self, regular_user):
        with pytest.raises(ValueError, match="not found"):
            check_scenario_access("nonexistent", regular_user)
