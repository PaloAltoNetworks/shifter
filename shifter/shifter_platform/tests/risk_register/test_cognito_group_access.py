"""Cognito group authorization for the risk register (issue #151)."""

from __future__ import annotations

import pytest
from django.test import Client, override_settings
from rest_framework.test import APIClient

from config.cognito_groups import sync_cognito_groups_from_claims
from config.oidc import ShifterOIDCBackend
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken

from .conftest import ALLOWED_GROUPS, grant_risk_register_access

pytestmark = pytest.mark.django_db

RISKS_URL = "/api/v1/risks/"
RISK_LIST_URL = "/risk-register/"


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def authorized_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="security-user",
        email="security@example.com",
        password="pw",
        is_staff=True,
    )
    grant_risk_register_access(user)
    return user


@pytest.fixture
def unauthorized_user(django_user_model):
    return django_user_model.objects.create_user(
        username="plain-staff",
        email="plain@example.com",
        password="pw",
        is_staff=True,
    )


class TestAccessPolicy:
    def test_staff_without_group_is_denied(self, client, unauthorized_user):
        client.force_login(unauthorized_user)
        assert client.get(RISK_LIST_URL).status_code == 403

    def test_staff_with_group_is_allowed(self, client, authorized_user):
        client.force_login(authorized_user)
        assert client.get(RISK_LIST_URL).status_code == 200

    @override_settings(RISK_REGISTER_ALLOWED_COGNITO_GROUPS=[])
    def test_empty_config_fails_closed(self, client, authorized_user):
        client.force_login(authorized_user)
        assert client.get(RISK_LIST_URL).status_code == 403


class TestApiAccess:
    def test_token_owner_without_group_is_403(self, api_client, unauthorized_user):
        _, raw = ApiToken.create_token(name="r", created_by=unauthorized_user, scopes=[scopes.RISK_READ])
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert api_client.get(RISKS_URL).status_code == 403

    def test_token_owner_with_group_is_200(self, api_client, authorized_user):
        _, raw = ApiToken.create_token(name="r", created_by=authorized_user, scopes=[scopes.RISK_READ])
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert api_client.get(RISKS_URL).status_code == 200


class TestOidcGroupCapture:
    def test_sync_persists_groups_on_profile(self, django_user_model):
        user = django_user_model.objects.create_user(username="oidc", email="oidc@example.com", password="pw")
        sync_cognito_groups_from_claims(user, {"cognito:groups": ["security", "other"]})
        user.profile.refresh_from_db()
        assert user.profile.cognito_groups == ["security", "other"]

    def test_backend_update_user_syncs_groups(self, django_user_model):
        user = django_user_model.objects.create_user(username="oidc2", email="oidc2@example.com", password="pw")
        backend = ShifterOIDCBackend()
        backend.update_user(user, {"cognito:groups": ALLOWED_GROUPS})
        user.profile.refresh_from_db()
        assert user.profile.cognito_groups == ALLOWED_GROUPS


class TestSessionPreference:
    def test_session_groups_take_precedence_over_stale_profile(self, client, authorized_user):
        client.force_login(authorized_user)
        session = client.session
        session["cognito_groups"] = ["other-group"]
        session.save()
        assert client.get(RISK_LIST_URL).status_code == 403
