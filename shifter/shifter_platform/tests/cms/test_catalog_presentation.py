"""Tests for the read-only catalog presentation DTO (issue #1254)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from cms.models import RaesPackageSource, ScenarioMetadata
from cms.scenarios.catalog_presentation import (
    PROVENANCE_SUMMARY_KEYS,
    get_catalog_presentation,
    list_catalog_presentations,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_user():
    return User.objects.create_user(
        username="cat-staff@example.com",
        email="cat-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def regular_user():
    return User.objects.create_user(
        username="cat-regular@example.com",
        email="cat-regular@example.com",
        is_staff=False,
    )


def _make_raes_source(staff_user, scenario_id, **overrides):
    fields = {
        "scenario_id": scenario_id,
        "contract_kind": "raes",
        "contract_profile": "shifter",
        "package_ref": "scenario-dev/polaris/content-packages/polaris",
        "package_version": "1.0.0",
        "package_digest": "sha256:" + "a" * 64,
        "lock_ref": "scenario-dev/polaris/content-packages/polaris.lock",
        "lock_digest": "sha256:" + "b" * 64,
        "conformance_status": "passed",
        "conformance_report_ref": "reports/polaris-conformance.json",
        "provenance": {"repo": "acme/raes", "commit": "c" * 40, "tool": "raes-cli"},
        "registered_by": staff_user,
    }
    fields.update(overrides)
    return RaesPackageSource.objects.create(**fields)


class TestRaesPresentation:
    def test_raes_entry_exposes_allowlisted_fields(self, staff_user):
        _make_raes_source(staff_user, "polaris-raes")

        entry = get_catalog_presentation("polaris-raes")

        assert entry is not None
        assert entry["id"] == "polaris-raes"
        assert entry["scenario_type"] == "raes"
        assert entry["is_default"] is False
        assert entry["launchable"] is True
        raes = entry["raes"]
        assert raes["source_kind"] == "repo"
        assert raes["contract_kind"] == "raes"
        assert raes["contract_profile"] == "shifter"
        assert raes["package_ref"] == "scenario-dev/polaris/content-packages/polaris"
        assert raes["package_version"] == "1.0.0"
        assert raes["package_digest"] == "sha256:" + "a" * 64
        assert raes["lock_ref"].endswith(".lock")
        assert raes["lock_digest"] == "sha256:" + "b" * 64
        assert raes["conformance_status"] == "passed"
        assert raes["conformance_report_ref"] == "reports/polaris-conformance.json"

    def test_provenance_summary_only_carries_allowlisted_keys(self, staff_user):
        _make_raes_source(staff_user, "polaris-raes")

        entry = get_catalog_presentation("polaris-raes")

        summary = entry["raes"]["provenance_summary"]
        assert summary == {"repo": "acme/raes", "commit": "c" * 40, "tool": "raes-cli"}
        assert set(summary).issubset(set(PROVENANCE_SUMMARY_KEYS))

    def test_projection_drops_non_allowlisted_provenance_keys(self, staff_user):
        """The presentation allowlist must actively drop non-allowlisted keys.

        The model boundary already rejects non-allowlisted provenance on save,
        so bypass it with a raw ``update()`` to simulate a widened / unexpected
        persisted provenance. The presentation layer is the defense-in-depth
        redaction boundary and must still strip keys outside
        ``PROVENANCE_SUMMARY_KEYS`` — a passthrough no-op would leak them.
        """
        _make_raes_source(staff_user, "polaris-raes")
        RaesPackageSource.objects.filter(scenario_id="polaris-raes").update(
            provenance={"repo": "acme/raes", "leaked_token": "SECRET", "sdl": "print('x')"}
        )

        entry = get_catalog_presentation("polaris-raes")

        summary = entry["raes"]["provenance_summary"]
        assert summary == {"repo": "acme/raes"}
        assert "leaked_token" not in summary
        assert "sdl" not in summary

    def test_access_overlay_applies_to_raes(self, staff_user):
        _make_raes_source(staff_user, "polaris-raes")
        ScenarioMetadata.objects.create(
            scenario_id="polaris-raes",
            enabled=False,
            staff_only=True,
            updated_by=staff_user,
        )

        entry = get_catalog_presentation("polaris-raes")

        assert entry["enabled"] is False
        assert entry["staff_only"] is True


class TestMissingPresentation:
    def test_unknown_scenario_returns_none(self, db):
        assert get_catalog_presentation("does-not-exist") is None


class TestListPresentation:
    def test_list_contains_only_registered_raes_sources(self, staff_user):
        _make_raes_source(staff_user, "polaris-raes")

        entries = list_catalog_presentations()

        by_id = {e["id"]: e for e in entries}
        assert set(by_id) == {"polaris-raes"}
        assert by_id["polaris-raes"]["raes"] is not None

    def test_non_staff_listing_preserves_access_filtering(self, staff_user, regular_user):
        _make_raes_source(staff_user, "polaris-raes")
        ScenarioMetadata.objects.create(
            scenario_id="polaris-raes",
            staff_only=True,
            updated_by=staff_user,
        )

        ids = [e["id"] for e in list_catalog_presentations(user=regular_user)]

        assert "polaris-raes" not in ids
