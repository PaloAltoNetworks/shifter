"""DRF boundary coverage for the read-only CMS catalog API (issue #1254)."""

from __future__ import annotations

import importlib

import pytest
from django.contrib.auth.models import Group
from django.urls import clear_url_caches
from rest_framework.test import APIClient

from cms.models import AcesPackageSource, ScenarioMetadata
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.auth import THREAT_RESEARCH_GROUP

pytestmark = pytest.mark.django_db

CATALOG_LIST_URL = "/api/v1/cms/catalog/"


def _catalog_detail_url(scenario_id: str) -> str:
    return f"/api/v1/cms/catalog/{scenario_id}/"


@pytest.fixture(autouse=True)
def _restore_urlconf() -> None:
    yield
    _reload_urlconfs()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username="catalog-api-staff@example.com",
        email="catalog-api-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def threat_research_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="catalog-api-threat@example.com",
        email="catalog-api-threat@example.com",
    )
    group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
    user.groups.add(group)
    return user


def _bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def _token(user, *granted_scopes: str) -> str:
    _, raw = ApiToken.create_token(name="catalog-api", created_by=user, scopes=list(granted_scopes))
    return raw


def _reload_urlconfs() -> None:
    import cms.api.urls
    import config.api_urls
    import config.urls

    clear_url_caches()
    importlib.reload(cms.api.urls)
    importlib.reload(config.api_urls)
    importlib.reload(config.urls)
    clear_url_caches()


def _make_aces_source(staff_user, scenario_id, **overrides):
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


class TestCatalogListAPI:
    def test_session_actor_lists_catalog_with_aces_entry(self, api_client, threat_research_user, staff_user):
        _make_aces_source(staff_user, "polaris-aces")
        api_client.force_authenticate(user=threat_research_user)

        response = api_client.get(CATALOG_LIST_URL)

        assert response.status_code == 200
        by_id = {entry["id"]: entry for entry in response.json()}
        assert "basic" in by_id
        assert by_id["basic"]["aces"] is None
        aces = by_id["polaris-aces"]["aces"]
        assert aces["contract_kind"] == "aces"
        assert aces["package_digest"] == "sha256:" + "a" * 64

    def test_read_token_can_list_catalog(self, api_client, staff_user):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)

        response = _bearer(api_client, raw).get(CATALOG_LIST_URL)

        assert response.status_code == 200

    def test_token_without_cms_read_scope_is_forbidden(self, api_client, staff_user):
        raw = _token(staff_user, scopes.RISK_READ)  # valid token, wrong scope

        response = _bearer(api_client, raw).get(CATALOG_LIST_URL)

        assert response.status_code == 403

    def test_malformed_bearer_fails_closed_over_session(self, api_client, staff_user):
        api_client.force_login(staff_user)
        api_client.credentials(HTTP_AUTHORIZATION="Bearer shf_missing.invalid")

        response = api_client.get(CATALOG_LIST_URL)

        assert response.status_code == 401


class TestCatalogDetailAPI:
    def test_detail_returns_allowlisted_aces_fields(self, api_client, staff_user):
        _make_aces_source(staff_user, "polaris-aces")
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)

        response = _bearer(api_client, raw).get(_catalog_detail_url("polaris-aces"))

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == "polaris-aces"
        assert payload["scenario_type"] == "aces"
        assert set(payload["aces"]) == {
            "source_kind",
            "contract_kind",
            "contract_profile",
            "package_ref",
            "package_version",
            "package_digest",
            "lock_ref",
            "lock_digest",
            "conformance_status",
            "conformance_report_ref",
            "provenance_summary",
        }

    def test_detail_unknown_returns_shared_error_envelope(self, api_client, staff_user):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)

        response = _bearer(api_client, raw).get(_catalog_detail_url("does-not-exist"))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_detail_carries_only_bounded_provenance_summary(self, api_client, staff_user):
        # A row whose provenance is the bounded allowlist; a secret-shaped value
        # is impossible to persist (validated at the model boundary), so the API
        # can only ever surface allowlisted reference keys.
        _make_aces_source(
            staff_user,
            "polaris-aces",
            provenance={"repo": "acme/aces", "notes": "public reference only"},
        )
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)

        response = _bearer(api_client, raw).get(_catalog_detail_url("polaris-aces"))

        aces = response.json()["aces"]
        # The API exposes only the bounded summary — never a raw `provenance`
        # field that could carry a widened/unbounded dict verbatim.
        assert "provenance" not in aces
        summary = aces["provenance_summary"]
        assert summary == {"repo": "acme/aces", "notes": "public reference only"}
        assert set(summary).issubset(
            {"repo", "commit", "ref", "tool", "tool_version", "conformance_report", "generated_at", "notes"}
        )
        body = response.content.decode()
        # No raw model payload fields leak into the response.
        assert "registered_by" not in body
        assert "definition" not in body


class TestCatalogAccessOverlay:
    def test_authoring_read_surface_reports_staff_only_overlay(self, api_client, staff_user, threat_research_user):
        _make_aces_source(staff_user, "polaris-aces")
        ScenarioMetadata.objects.create(
            scenario_id="polaris-aces",
            staff_only=True,
            updated_by=staff_user,
        )
        # The authoring read surface is the unfiltered staff-review projection
        # (like the scenario-editor list); it reports the access overlay rather
        # than hiding entries, so a Threat Research actor can inspect and toggle
        # it. User-facing / launch filtering stays in the registry (covered by
        # the registry and presentation tests).
        raw = _token(threat_research_user, scopes.CMS_AUTHORING_READ)

        response = _bearer(api_client, raw).get(CATALOG_LIST_URL)

        assert response.status_code == 200
        by_id = {entry["id"]: entry for entry in response.json()}
        assert by_id["polaris-aces"]["staff_only"] is True
