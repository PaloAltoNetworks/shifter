"""Read-only ACES catalog presentation in the scenario editor (issue #1254)."""

from __future__ import annotations

import pytest

from cms.models import AcesPackageSource, ScenarioMetadata

# staff_user / staff_client / regular_client / threat_research_client come from conftest.py

VIEW_BASE = "/scenario-editor/"

pytestmark = pytest.mark.django_db


def _make_aces_source(staff_user, scenario_id="polaris-aces", **overrides):
    fields = {
        "scenario_id": scenario_id,
        "contract_kind": "aces",
        "contract_profile": "shifter",
        "package_ref": "scenario-dev/polaris/content-packages/polaris",
        "package_version": "1.0.0",
        "package_digest": "sha256:" + "a" * 64,
        "conformance_status": "passed",
        "conformance_report_ref": "reports/polaris-conformance.json",
        "provenance": {"repo": "acme/aces", "commit": "c" * 40},
        "registered_by": staff_user,
    }
    fields.update(overrides)
    return AcesPackageSource.objects.create(**fields)


class TestAcesDetailPresentation:
    def test_aces_detail_renders_read_only_metadata(self, staff_client, staff_user):
        _make_aces_source(staff_user)

        response = staff_client.get(f"{VIEW_BASE}polaris-aces/")

        assert response.status_code == 200
        body = response.content.decode()
        assert "polaris-aces" in body
        assert "shifter" in body  # contract_profile
        assert "sha256:" + "a" * 64 in body  # package_digest

    def test_aces_detail_omits_authoring_actions(self, staff_client, staff_user):
        _make_aces_source(staff_user)

        response = staff_client.get(f"{VIEW_BASE}polaris-aces/")

        body = response.content.decode()
        assert f"{VIEW_BASE}polaris-aces/edit/" not in body
        assert f"{VIEW_BASE}polaris-aces/editor/" not in body
        assert f"{VIEW_BASE}polaris-aces/clone/" not in body
        assert f"{VIEW_BASE}polaris-aces/delete/" not in body
        assert f"{VIEW_BASE}polaris-aces/export/" not in body

    def test_aces_detail_does_not_leak_raw_provenance_object(self, staff_client, staff_user):
        _make_aces_source(staff_user)

        response = staff_client.get(f"{VIEW_BASE}polaris-aces/")

        body = response.content.decode()
        # Bounded summary values are shown; internal model attrs are not dumped.
        assert "registered_by" not in body


class TestAcesListPresentation:
    def test_aces_row_has_view_but_no_authoring_actions(self, staff_client, staff_user):
        _make_aces_source(staff_user)

        response = staff_client.get(VIEW_BASE)

        body = response.content.decode()
        assert f"{VIEW_BASE}polaris-aces/edit/" not in body
        assert f"{VIEW_BASE}polaris-aces/clone/" not in body
        assert f"{VIEW_BASE}polaris-aces/delete/" not in body
        assert f"{VIEW_BASE}polaris-aces/export/" not in body
        # The read-only detail link is still present.
        assert f"{VIEW_BASE}polaris-aces/" in body

    def test_legacy_row_keeps_authoring_actions(self, staff_client, staff_user, valid_definition):
        from cms.models import Scenario

        Scenario.objects.create(
            scenario_id="legacy-custom",
            name="Legacy Custom",
            description="legacy",
            definition=valid_definition,
            created_by=staff_user,
            updated_by=staff_user,
        )

        response = staff_client.get(VIEW_BASE)

        body = response.content.decode()
        assert f"{VIEW_BASE}legacy-custom/clone/" in body
        assert f"{VIEW_BASE}legacy-custom/export/" in body


class TestAcesMetadataToggle:
    def test_staff_can_toggle_aces_enabled(self, staff_client, staff_user):
        _make_aces_source(staff_user)

        response = staff_client.post(f"{VIEW_BASE}polaris-aces/toggle-enabled/")

        assert response.status_code == 302
        meta = ScenarioMetadata.objects.get(scenario_id="polaris-aces")
        assert meta.enabled is False

    def test_staff_can_toggle_aces_staff_only(self, staff_client, staff_user):
        _make_aces_source(staff_user)

        response = staff_client.post(f"{VIEW_BASE}polaris-aces/toggle-staff-only/")

        assert response.status_code == 302
        meta = ScenarioMetadata.objects.get(scenario_id="polaris-aces")
        assert meta.staff_only is True


class TestLegacyDetailUnchanged:
    def test_legacy_default_detail_still_renders_yaml(self, staff_client):
        response = staff_client.get(f"{VIEW_BASE}basic/")

        assert response.status_code == 200
        body = response.content.decode()
        assert "YAML Definition" in body
