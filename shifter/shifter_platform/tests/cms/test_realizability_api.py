"""DRF boundary coverage for the Scenario Editor realizability endpoint (#1581).

ADR-034-R3 requires non-realizability to be surfaced to the author. These tests
pin the API contract the editor renders:

- an expected negative assessment is a typed **2xx** result, not an HTTP error --
  "this pack cannot be realized" is a domain answer, not a server failure;
- only genuine failures (unauthenticated, unknown scenario) use the shared error
  envelope;
- the payload is bounded: stable codes and addresses, never SDL bodies,
  authored values, provider detail, or local filesystem paths.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from cms.scenarios.pack_validation import pack_digest
from cms.services import PackRegistrationRequest, register_pack
from engine.services import RaesImageMappingOptions, upsert_raes_image_mapping
from shared.raes.realizability import RealizabilityOutcome
from tests.cms.conftest import IMAGELESS_PACK_SDL

pytestmark = pytest.mark.django_db

_GCE = "gce"


def _url(scenario_id: str) -> str:
    return f"/api/v1/cms/scenarios/{scenario_id}/realizability/"


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username="realizability-api@example.com",
        email="realizability-api@example.com",
        is_staff=True,
    )


@pytest.fixture
def non_authoring_user(django_user_model):
    return django_user_model.objects.create_user(
        username="realizability-viewer@example.com",
        email="realizability-viewer@example.com",
    )


@pytest.fixture(autouse=True)
def _gcp_target(monkeypatch):
    monkeypatch.setattr(settings, "CLOUD_PROVIDER", "gcp")


@pytest.fixture
def registered_pack(staff_user, make_pack, tmp_path, monkeypatch):
    root = make_pack(tmp_path / "packs" / "imageless", name="imageless", sdl=IMAGELESS_PACK_SDL)
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
    register_pack(
        user=staff_user,
        request=PackRegistrationRequest(
            scenario_id="imageless",
            source_kind="repo",
            contract_kind="raes",
            contract_profile="shifter",
            package_ref="packs/imageless",
            package_version="0.1.0",
            package_digest=pack_digest(root),
            provenance={"repo": "acme/example", "commit": "c" * 40},
        ),
    )
    return root


class TestAuthorization:
    """A realizability badge is never authorization; the read is scoped."""

    def test_anonymous_is_rejected(self, api_client, registered_pack):
        response = api_client.get(_url("imageless"))
        assert response.status_code in (401, 403)

    def test_staff_may_read(self, api_client, staff_user, registered_pack):
        api_client.force_authenticate(user=staff_user)
        assert api_client.get(_url("imageless")).status_code == 200

    def test_authenticated_non_authoring_user_is_rejected(self, api_client, non_authoring_user, registered_pack):
        api_client.force_authenticate(user=non_authoring_user)
        assert api_client.get(_url("imageless")).status_code == 403


class TestNegativeAssessmentIsATypedResult:
    """A non-realizable pack is a 200 domain answer, not an exception."""

    def test_missing_image_mapping_returns_200_not_realizable(self, api_client, staff_user, registered_pack):
        api_client.force_authenticate(user=staff_user)

        response = api_client.get(_url("imageless"))

        assert response.status_code == 200
        assert response.data["outcome"] == RealizabilityOutcome.NOT_REALIZABLE
        assert response.data["gaps"], "the author must be told what the gap is"

    def test_realizable_pack_reports_no_gaps(self, api_client, staff_user, registered_pack):
        upsert_raes_image_mapping(
            provider=_GCE,
            source_name="linux",
            image_ref="projects/p/global/images/base-linux",
            options=RaesImageMappingOptions(source_version=""),
        )
        api_client.force_authenticate(user=staff_user)

        response = api_client.get(_url("imageless"))

        assert response.status_code == 200
        assert response.data["outcome"] == RealizabilityOutcome.REALIZABLE
        assert response.data["gaps"] == []
        assert response.data["target_id"] == _GCE


class TestErrorEnvelope:
    """Genuine failures still use the shared sanitized envelope."""

    def test_unknown_scenario_is_404(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(_url("no-such-scenario"))
        assert response.status_code == 404


class TestBoundedPayload:
    """Nothing beyond bounded identity crosses the boundary."""

    def test_gap_shape_is_closed(self, api_client, staff_user, registered_pack):
        api_client.force_authenticate(user=staff_user)

        gaps = api_client.get(_url("imageless")).data["gaps"]

        assert gaps
        for gap in gaps:
            assert set(gap) == {"code", "address", "category", "message"}

    def test_payload_carries_no_paths_or_sdl(self, api_client, staff_user, registered_pack, tmp_path):
        api_client.force_authenticate(user=staff_user)

        body = str(api_client.get(_url("imageless")).data)

        assert str(tmp_path) not in body
        assert "infrastructure:" not in body, "SDL bodies must not reach the author payload"
