"""Tests for the SPA session bootstrap endpoint (#1300 / #1302)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from management.services import get_user_profile

pytestmark = pytest.mark.django_db

BOOTSTRAP_URL = "/api/v1/bootstrap/"
ALLOWED_GROUPS = ["security"]


@pytest.fixture(autouse=True)
def _allowed_groups(settings):
    settings.RISK_REGISTER_ALLOWED_COGNITO_GROUPS = ALLOWED_GROUPS


def _grant(user, groups=None):
    profile = get_user_profile(user)
    profile.cognito_groups = list(groups if groups is not None else ALLOWED_GROUPS)
    profile.save(update_fields=["cognito_groups"])
    return profile


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="pw",
        is_staff=True,
    )


def test_anonymous_is_401():
    assert APIClient().get(BOOTSTRAP_URL).status_code == 401


def test_authenticated_returns_principal(user):
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()

    principal = body["principal"]
    assert principal["id"] == user.id
    assert principal["username"] == "alice"
    assert principal["is_authenticated"] is True
    assert principal["is_staff"] is True
    assert principal["is_superuser"] is False


def test_risk_register_access_reflects_group_membership(user):
    _grant(user)
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["permissions"]["can_access_risk_register"] is True


def test_risk_register_access_denied_without_group(user):
    _grant(user, groups=["other-group"])
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["permissions"]["can_access_risk_register"] is False


def test_feature_flag_reported(user, settings):
    settings.RISK_REGISTER_SPA_ENABLED = True
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["risk_register_spa"] is True


def test_feature_flag_default_false(user, settings):
    settings.RISK_REGISTER_SPA_ENABLED = False
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["risk_register_spa"] is False
