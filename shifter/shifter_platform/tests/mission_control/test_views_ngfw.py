"""Behavior tests for the NGFW JSON API views.

Drives the real views → real ``cms.services`` NGFW entrypoints (``list_ngfws`` /
``get_ngfw`` / ``create_ngfw`` / ``destroy_ngfw`` / ``list_credentials``) against
real ``App`` / ``Instance`` / ``Request`` / ``Credential`` rows → real JSON,
instead of patching the CMS service functions.
Engine NGFW provisioning is a no-op because ECS is unconfigured in test
settings, so no cloud mock is required.
"""

from __future__ import annotations

import json
import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="ngfw-views@example.com", email="ngfw-views@example.com")


@pytest.fixture
def client_for(db):
    def _make(user):
        client = Client()
        client.force_login(user)
        session = client.session
        session["oidc_id_token_expiration"] = time.time() + 3600
        session.save()
        return client

    return _make


def _json(response):
    return json.loads(response.content)


# ---------------------------------------------------------------------------
# api_ngfw_create
# ---------------------------------------------------------------------------


class TestApiNGFWCreate:
    def _create(self, client, payload):
        return client.post(
            reverse("v1:mission_control:ngfw-create"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_creates_ngfw_and_returns_201(self, user, client_for, ngfw_catalog, ngfw_credentials):
        from cms.models import App

        deployment_profile, scm_credential = ngfw_credentials(user)
        response = self._create(
            client_for(user),
            {
                "name": "My NGFW",
                "deployment_profile_id": str(deployment_profile.id),
                "registration_method": "pin",
                "scm_credential_id": str(scm_credential.id),
            },
        )

        assert response.status_code == 201
        assert _json(response)["status"] == "provisioning"
        assert App.objects.filter(name="My NGFW", instance__request__user=user).exists()

    def test_returns_400_for_invalid_json(self, user, client_for):
        response = client_for(user).post(
            reverse("v1:mission_control:ngfw-create"), data="not json", content_type="application/json"
        )
        assert response.status_code == 400
        assert _json(response)["error"]["code"] == "parse_error"

    def test_returns_400_when_user_already_has_active_ngfw(
        self, user, client_for, ngfw_catalog, ngfw_credentials, cms_ngfw_app
    ):
        cms_ngfw_app(user, name="Existing")  # an active NGFW already exists
        deployment_profile, scm_credential = ngfw_credentials(user)

        response = self._create(
            client_for(user),
            {
                "name": "Second NGFW",
                "deployment_profile_id": str(deployment_profile.id),
                "registration_method": "pin",
                "scm_credential_id": str(scm_credential.id),
            },
        )

        assert response.status_code == 400
        assert "error" in _json(response)

    def test_returns_400_for_missing_name(self, user, client_for, ngfw_catalog, ngfw_credentials):
        deployment_profile, _scm = ngfw_credentials(user)
        response = self._create(
            client_for(user),
            {"name": "", "deployment_profile_id": str(deployment_profile.id), "registration_method": "otp"},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# api_ngfw_list (JSON)
# ---------------------------------------------------------------------------


class TestApiNGFWList:
    def test_returns_serialized_ngfws(self, user, client_for, cms_ngfw_app):
        cms_ngfw_app(user, name="JsonNGFW", serial="SER-123")

        response = client_for(user).get(reverse("v1:mission_control:ngfw-list"))

        assert response.status_code == 200
        ngfws = _json(response)["ngfws"]
        assert len(ngfws) == 1
        assert ngfws[0]["name"] == "JsonNGFW"
        assert ngfws[0]["serial_number"] == "SER-123"


# ---------------------------------------------------------------------------
# api_ngfw_destroy
# ---------------------------------------------------------------------------


class TestApiNGFWDestroy:
    def _destroy(self, client, app_id, confirm_name):
        return client.post(
            reverse("v1:mission_control:ngfw-destroy", kwargs={"app_id": str(app_id)}),
            data=json.dumps({"confirm_name": confirm_name}),
            content_type="application/json",
        )

    def test_destroys_ngfw_on_matching_name(self, user, client_for, cms_ngfw_app):
        from shared.enums import ResourceStatus

        app = cms_ngfw_app(user, name="KillMe")

        response = self._destroy(client_for(user), app.id, "KillMe")

        assert response.status_code == 200
        assert _json(response)["status"] == "deprovisioning"
        app.refresh_from_db()
        assert app.status == ResourceStatus.DESTROYING.value

    def test_returns_400_for_invalid_json(self, user, client_for):
        from uuid import uuid4

        response = client_for(user).post(
            reverse("v1:mission_control:ngfw-destroy", kwargs={"app_id": str(uuid4())}),
            data="x",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_returns_404_when_missing(self, user, client_for):
        from uuid import uuid4

        response = self._destroy(client_for(user), uuid4(), "anything")
        assert response.status_code == 404

    def test_returns_400_on_name_mismatch(self, user, client_for, cms_ngfw_app):
        app = cms_ngfw_app(user, name="RealName")

        response = self._destroy(client_for(user), app.id, "WrongName")

        assert response.status_code == 400
