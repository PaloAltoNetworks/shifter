"""End-to-end API-token tests for the Mission Control DRF API (PLAT-106)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from rest_framework.test import APIClient

from cms.assets.upload_token import generate_upload_token
from mission_control.models import GuacamoleBootstrapRequest
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken

pytestmark = pytest.mark.django_db

RANGE_URL = "/api/v1/mission-control/range/"
UPLOAD_INITIATE_URL = "/api/v1/mission-control/upload/initiate/"
UPLOAD_CANCEL_URL = "/api/v1/mission-control/upload/cancel/"
NGFW_LIST_URL = "/api/v1/mission-control/ngfw/list/"
GUACAMOLE_RDP_URL = "/api/v1/mission-control/guacamole/rdp-url/"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="mc-token@example.com", email="mc-token@example.com")


@pytest.fixture
def client():
    return APIClient()


def _bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def _token(user, *granted_scopes: str) -> str:
    _, raw = ApiToken.create_token(name="mission-control", created_by=user, scopes=list(granted_scopes))
    return raw


def _upload_token(user) -> str:
    return generate_upload_token(
        user_id=user.id,
        s3_key=f"agents/{user.id}/agent.msi",
        name="Agent",
        filename="agent.msi",
        os_slug="windows",
        file_size=100,
    )


class TestRangeTokenAccess:
    def test_range_read_token_can_read_current_range(self, client, user):
        raw = _token(user, scopes.MISSION_CONTROL_RANGE_READ)

        response = _bearer(client, raw).get(RANGE_URL)

        assert response.status_code == 200
        assert response.json() == {
            "has_range": False,
            "range": None,
            "connection_urls": [],
            "aces_projection": None,
            "aces_participant_runtime": None,
        }

    def test_token_without_range_read_scope_is_forbidden(self, client, user):
        raw = _token(user, scopes.MISSION_CONTROL_UPLOAD_WRITE)

        response = _bearer(client, raw).get(RANGE_URL)

        assert response.status_code == 403


class TestUploadTokenAccess:
    def test_upload_requires_upload_write_scope(self, client, user):
        raw = _token(user, scopes.MISSION_CONTROL_RANGE_WRITE)

        response = _bearer(client, raw).post(
            UPLOAD_INITIATE_URL,
            {"name": "Agent", "filename": "agent.msi", "file_size": 10},
            format="json",
        )

        assert response.status_code == 403

    def test_upload_write_token_reaches_upload_validation(self, client, user):
        raw = _token(user, scopes.MISSION_CONTROL_UPLOAD_WRITE)

        response = _bearer(client, raw).post(
            UPLOAD_INITIATE_URL,
            {"name": "", "filename": "agent.msi", "file_size": 10},
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid"

    def test_upload_write_token_can_cancel_without_csrf(self, client, settings, user):
        settings.AWS_S3_BUCKET_NAME = "test-bucket"
        settings.AGENT_UPLOAD_URL_EXPIRES = 900
        raw = _token(user, scopes.MISSION_CONTROL_UPLOAD_WRITE)

        with patch("boto3.client", return_value=MagicMock()):
            response = _bearer(client, raw).post(
                UPLOAD_CANCEL_URL,
                {"upload_token": _upload_token(user)},
                format="json",
            )

        assert response.status_code == 200
        assert response.json() == {"success": True}


class TestSubsurfaceTokenAccess:
    def test_ngfw_read_scope_can_list_ngfws(self, client, user):
        raw = _token(user, scopes.MISSION_CONTROL_NGFW_READ)

        response = _bearer(client, raw).get(NGFW_LIST_URL)

        assert response.status_code == 200
        assert response.json() == {"ngfws": []}

    def test_ngfw_list_rejects_range_read_scope(self, client, user):
        raw = _token(user, scopes.MISSION_CONTROL_RANGE_READ)

        response = _bearer(client, raw).get(NGFW_LIST_URL)

        assert response.status_code == 403

    def test_guacamole_bootstrap_response_uses_canonical_urls(self, client, monkeypatch, user):
        request_id = UUID("00000000-0000-0000-0000-000000000001")
        monkeypatch.setattr("mission_control.api.views._get_guac_settings", lambda protocol: object())
        monkeypatch.setattr(
            "mission_control.views._guacamole_bootstrap.enqueue_guacamole_bootstrap",
            lambda **kwargs: SimpleNamespace(id=request_id, status=GuacamoleBootstrapRequest.Status.PENDING),
        )
        raw = _token(user, scopes.MISSION_CONTROL_GUACAMOLE_READ)

        response = _bearer(client, raw).post(GUACAMOLE_RDP_URL, {"instance_uuid": "instance-1"}, format="json")

        assert response.status_code == 202
        assert response["Location"] == f"/api/v1/mission-control/guacamole/bootstrap/{request_id}/"
        assert response.json()["status_url"] == f"/api/v1/mission-control/guacamole/bootstrap/{request_id}/"
        assert response.json()["url"] == f"/api/v1/mission-control/guacamole/bootstrap/{request_id}/open/"
