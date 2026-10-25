"""DRF boundary coverage for the tenant RAES image registry API (#1566).

Drives the real ``/api/v1/cms/raes-image-mappings/`` endpoints against a real
database and the real ``engine.services`` write path: register/upsert, list with
the allowlisted projection, soft-disable, and CMS-authoring authorization.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from engine.models import RaesImageMapping
from engine.services import RaesImageMappingOptions, upsert_raes_image_mapping
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.auth import THREAT_RESEARCH_GROUP

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("personal_token_use_grant")]

LIST_CREATE_URL = "/api/v1/cms/raes-image-mappings/"
DISABLE_URL = "/api/v1/cms/raes-image-mappings/disable/"

_VIEW_FIELDS = {
    "id",
    "provider",
    "source_name",
    "source_version",
    "image_ref",
    "machine_type",
    "disk_size_gb",
    "disk_type",
    "management_ssh_port",
    "management_ssh_username",
    "image_kind",
    "bootstrap_capability",
    "participant_container_name",
    "participant_username",
    "participant_readiness_contract",
    "participant_readiness_manifest_sha256",
    "enabled",
    "notes",
    "artifact_id",
    "artifact_version",
    "artifact_digest",
    "media_type",
    "integrity_ref",
    "provenance_ref",
    "created_at",
    "updated_at",
}


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username="raes-img-staff@example.com",
        email="raes-img-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def threat_research_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="raes-img-threat@example.com",
        email="raes-img-threat@example.com",
    )
    group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
    user.groups.add(group)
    return user


@pytest.fixture
def non_authoring_user(django_user_model):
    return django_user_model.objects.create_user(
        username="raes-img-viewer@example.com",
        email="raes-img-viewer@example.com",
    )


def _token(user, *granted: str) -> str:
    _, raw = ApiToken.create_token(name="raes-img", created_by=user, scopes=list(granted))
    return raw


def _bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


class TestRegister:
    def test_registers_preconfigured_machine_host_profile(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {
                "provider": "gce",
                "source_name": "nested-host",
                "image_ref": "projects/example/global/machineImages/nested-host-v1",
                "image_kind": "machine-image",
                "bootstrap_capability": "preconfigured-machine-host",
                "management_ssh_username": "host-admin",
                "participant_container_name": "participant-desktop",
                "participant_username": "student",
                "participant_readiness_contract": "participant-readiness/v1",
                "participant_readiness_manifest_sha256": "a" * 64,
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["image_kind"] == "machine-image"
        assert response.json()["participant_container_name"] == "participant-desktop"

    def test_management_port_survives_registration_and_list(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        body = {
            "provider": "gce",
            "source_name": "container-host",
            "image_ref": "projects/x/global/images/host",
            "management_ssh_port": 2222,
            "management_ssh_username": "image-admin",
        }
        response = api_client.post(LIST_CREATE_URL, body, format="json")
        assert response.status_code == 200
        assert response.json()["management_ssh_port"] == 2222
        assert response.json()["management_ssh_username"] == "image-admin"
        assert api_client.get(LIST_CREATE_URL).json()[0]["management_ssh_port"] == 2222
        for invalid in (0, 65536, -1):
            response = api_client.post(LIST_CREATE_URL, {**body, "management_ssh_port": invalid}, format="json")
            assert response.status_code == 400
        assert RaesImageMapping.objects.get(source_name="container-host").management_ssh_port == 2222

    def test_register_creates_mapping(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {
                "provider": "gce",
                "source_name": "alpine",
                "image_ref": "projects/x/global/images/alpine-3-19",
                "source_version": "3.19",
                "disk_size_gb": 20,
            },
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "gce"
        assert body["source_name"] == "alpine"
        assert body["enabled"] is True
        assert set(body) == _VIEW_FIELDS
        assert RaesImageMapping.objects.count() == 1

    def test_register_is_idempotent_upsert(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        payload = {"provider": "gce", "source_name": "kali", "image_ref": "img-a"}
        api_client.post(LIST_CREATE_URL, payload, format="json")
        response = api_client.post(LIST_CREATE_URL, {**payload, "image_ref": "img-b"}, format="json")
        assert response.status_code == 200
        assert response.json()["image_ref"] == "img-b"
        assert RaesImageMapping.objects.count() == 1

    def test_invalid_provider_is_domain_400(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {"provider": "azure", "source_name": "kali", "image_ref": "img"},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid"

    _PORTABLE = {
        "artifact_id": "img-kali",
        "artifact_version": "1.0.0",
        "artifact_digest": "sha256:" + "a" * 64,
        "media_type": "application/vnd.raes.image",
        "integrity_ref": "integrity-1",
        "provenance_ref": "provenance-1",
    }

    def test_register_full_portable_identity_persists(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img", **self._PORTABLE},
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["artifact_digest"] == self._PORTABLE["artifact_digest"]
        assert body["artifact_version"] == "1.0.0"
        row = RaesImageMapping.objects.get(provider="gce", source_name="kali")
        assert row.artifact_digest == self._PORTABLE["artifact_digest"]
        assert row.integrity_ref == "integrity-1"

    def test_register_half_populated_portable_identity_is_domain_400(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img", **{**self._PORTABLE, "provenance_ref": ""}},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid"
        assert "provenance_ref" in response.json()["error"]["message"]
        assert RaesImageMapping.objects.count() == 0

    def test_register_non_canonical_digest_is_domain_400(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {
                "provider": "gce",
                "source_name": "kali",
                "image_ref": "img",
                **{**self._PORTABLE, "artifact_digest": "deadbeef"},
            },
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid"
        assert RaesImageMapping.objects.count() == 0

    def test_missing_required_field_is_shape_400(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(LIST_CREATE_URL, {"provider": "gce"}, format="json")
        assert response.status_code == 400

    def test_non_positive_disk_size_is_shape_400(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img", "disk_size_gb": 0},
            format="json",
        )
        assert response.status_code == 400

    def test_write_token_can_register(self, api_client, staff_user):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ, scopes.CMS_AUTHORING_WRITE)
        response = _bearer(api_client, raw).post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img"},
            format="json",
        )
        assert response.status_code == 200

    def test_read_only_token_cannot_register(self, api_client, staff_user):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)
        response = _bearer(api_client, raw).post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img"},
            format="json",
        )
        assert response.status_code == 403

    def test_authenticated_non_authoring_user_cannot_register(self, api_client, non_authoring_user):
        api_client.force_authenticate(user=non_authoring_user)

        response = api_client.post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img"},
            format="json",
        )

        assert response.status_code == 403
        assert not RaesImageMapping.objects.exists()


class TestList:
    def test_lists_rows_with_allowlisted_fields(self, api_client, threat_research_user):
        upsert_raes_image_mapping(provider="gce", source_name="alpine", image_ref="img-any")
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.get(LIST_CREATE_URL)
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1
        assert set(results[0]) == _VIEW_FIELDS

    def test_include_disabled_false_filters_disabled(self, api_client, threat_research_user):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img")
        upsert_raes_image_mapping(
            provider="gce",
            source_name="ubuntu",
            image_ref="img",
            options=RaesImageMappingOptions(enabled=False),
        )
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.get(LIST_CREATE_URL, {"include_disabled": "false"})
        assert [r["source_name"] for r in response.json()] == ["kali"]

    def test_read_token_can_list(self, api_client, staff_user):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)
        response = _bearer(api_client, raw).get(LIST_CREATE_URL)
        assert response.status_code == 200

    def test_wrong_scope_forbidden(self, api_client, staff_user):
        raw = _token(staff_user, scopes.MISSION_CONTROL_RANGE_READ)  # valid token, wrong scope
        response = _bearer(api_client, raw).get(LIST_CREATE_URL)
        assert response.status_code == 403

    def test_authenticated_non_authoring_user_cannot_list(self, api_client, non_authoring_user):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img")
        api_client.force_authenticate(user=non_authoring_user)

        response = api_client.get(LIST_CREATE_URL)

        assert response.status_code == 403


class TestDisable:
    def test_disable_sets_enabled_false_preserving_image_ref(self, api_client, threat_research_user):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img-keep")
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(DISABLE_URL, {"provider": "gce", "source_name": "kali"}, format="json")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["image_ref"] == "img-keep"
        assert RaesImageMapping.objects.get(source_name="kali").enabled is False

    def test_disable_missing_mapping_is_domain_400(self, api_client, threat_research_user):
        api_client.force_authenticate(user=threat_research_user)
        response = api_client.post(DISABLE_URL, {"provider": "gce", "source_name": "absent"}, format="json")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid"

    def test_read_only_token_cannot_disable(self, api_client, staff_user):
        raw = _token(staff_user, scopes.CMS_AUTHORING_READ)
        response = _bearer(api_client, raw).post(
            DISABLE_URL,
            {"provider": "gce", "source_name": "kali"},
            format="json",
        )
        assert response.status_code == 403

    def test_authenticated_non_authoring_user_cannot_disable(self, api_client, non_authoring_user):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img")
        api_client.force_authenticate(user=non_authoring_user)

        response = api_client.post(DISABLE_URL, {"provider": "gce", "source_name": "kali"}, format="json")

        assert response.status_code == 403
        assert RaesImageMapping.objects.get(source_name="kali").enabled is True


class TestAuthentication:
    def test_anonymous_cannot_list(self, api_client):
        assert api_client.get(LIST_CREATE_URL).status_code in {401, 403}

    def test_anonymous_cannot_register(self, api_client):
        response = api_client.post(
            LIST_CREATE_URL,
            {"provider": "gce", "source_name": "kali", "image_ref": "img"},
            format="json",
        )

        assert response.status_code in {401, 403}
        assert not RaesImageMapping.objects.exists()

    def test_anonymous_cannot_disable(self, api_client):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img")

        response = api_client.post(DISABLE_URL, {"provider": "gce", "source_name": "kali"}, format="json")

        assert response.status_code in {401, 403}
        assert RaesImageMapping.objects.get(source_name="kali").enabled is True


def test_registry_validation_response_uses_public_message(api_client, staff_user, monkeypatch):
    from engine.services import RaesImageMappingError

    class DiagnosticError(RaesImageMappingError):
        def __str__(self):
            return "internal-storage-diagnostic"

    def reject(**kwargs):
        raise DiagnosticError("Unsupported image provider")

    monkeypatch.setattr("cms.api.raes_image_registry.list_raes_image_mappings", reject)
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(LIST_CREATE_URL)
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Unsupported image provider"
    assert "internal-storage-diagnostic" not in response.content.decode()
