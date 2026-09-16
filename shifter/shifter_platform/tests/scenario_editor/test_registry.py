"""RAES-only catalog registry behavior after the #1311 hard cut."""

import pytest
from django.contrib.auth import get_user_model

from cms.models import RaesPackageSource, ScenarioMetadata
from cms.scenarios.registry import (
    ScenarioWorkflow,
    get_catalog_entry,
    get_scenario_detail,
    is_scenario_launchable,
    list_all_scenarios,
    list_launchable_scenarios,
)

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_user():
    return User.objects.create_user(username="staff@example.com", email="staff@example.com", is_staff=True)


def _make_source(staff_user, scenario_id: str, **overrides):
    fields = {
        "scenario_id": scenario_id,
        "contract_kind": "raes",
        "contract_profile": "shifter",
        "package_ref": f"scenario-dev/{scenario_id}",
        "package_version": "1.0.0",
        "package_digest": "sha256:" + "a" * 64,
        "conformance_status": "passed",
        "registered_by": staff_user,
    }
    fields.update(overrides)
    return RaesPackageSource.objects.create(**fields)


def test_catalog_contains_only_registered_raes_sources(staff_user):
    _make_source(staff_user, "polaris")
    assert [entry["id"] for entry in list_all_scenarios()] == ["polaris"]
    entry = get_catalog_entry("polaris")
    assert entry["scenario_type"] == "raes"
    assert entry["source_kind"] == "repo"
    assert entry["launchable"] is True


def test_pending_source_is_visible_but_not_launchable(staff_user):
    _make_source(staff_user, "pending", conformance_status="pending")
    assert get_catalog_entry("pending")["launchable"] is False
    assert is_scenario_launchable("pending") is False
    assert list_launchable_scenarios(workflow=ScenarioWorkflow.RANGE_LAUNCH) == []


def test_metadata_overlay_filters_non_staff(staff_user):
    source = _make_source(staff_user, "polaris")
    ScenarioMetadata.objects.create(
        scenario_id=source.scenario_id,
        enabled=False,
        staff_only=True,
        updated_by=staff_user,
    )
    assert get_scenario_detail("polaris")["enabled"] is False
    regular = User.objects.create_user(username="reader@example.com")
    assert list_all_scenarios(user=regular) == []


def test_unknown_catalog_entry_fails_closed():
    assert get_catalog_entry("missing") is None
    with pytest.raises(ValueError, match="not found"):
        get_scenario_detail("missing")
