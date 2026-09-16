"""Tests for the SPA session bootstrap endpoint (#1300)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

BOOTSTRAP_URL = "/api/v1/bootstrap/"


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


def test_bootstrap_has_no_rollout_feature_flags(user):
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert "feature_flags" not in body


def test_user_admin_capabilities_false_without_model_permissions(user):
    # A staff user without the auth model permissions gets no advisory admin caps.
    client = APIClient()
    client.force_authenticate(user=user)
    permissions = client.get(BOOTSTRAP_URL).json()["permissions"]
    assert permissions["can_view_users"] is False
    assert permissions["can_change_users"] is False
    assert permissions["can_delete_users"] is False


def test_user_admin_capabilities_reflect_model_permissions(django_user_model):
    # A superuser implicitly holds every model permission, so all caps are True.
    superuser = django_user_model.objects.create_superuser(username="root", email="root@example.com", password="pw")
    client = APIClient()
    client.force_authenticate(user=superuser)
    permissions = client.get(BOOTSTRAP_URL).json()["permissions"]
    assert permissions["can_view_users"] is True
    assert permissions["can_change_users"] is True
    assert permissions["can_delete_users"] is True


def test_modes_default_operator_for_non_participant(user):
    client = APIClient()
    client.force_authenticate(user=user)
    modes = client.get(BOOTSTRAP_URL).json()["modes"]
    # A staff user who is not a CTF-participant-only account is operator-eligible
    # and defaults to operator mode. Mode is advisory UX, not authorization.
    assert modes["operator"] is True
    assert modes["participant"] is False
    assert modes["default"] == "operator"


def test_permissions_include_advisory_ctf_flags(user):
    client = APIClient()
    client.force_authenticate(user=user)
    permissions = client.get(BOOTSTRAP_URL).json()["permissions"]
    assert permissions["is_ctf_organizer"] is False
    assert permissions["is_ctf_participant"] is False


def test_modes_participant_for_ctf_participant_only(user, monkeypatch):
    # Exercise the participant/true side: a CTF-participant-only account is
    # participant-eligible, not operator-eligible, and defaults to participant.
    monkeypatch.setattr("config.api_bootstrap.is_ctf_participant", lambda _u: True)
    monkeypatch.setattr("config.api_bootstrap.is_ctf_participant_only", lambda _u: True)
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["modes"] == {"participant": True, "operator": False, "default": "participant"}
    assert body["permissions"]["is_ctf_participant"] is True


def test_permissions_ctf_organizer_true(user, monkeypatch):
    monkeypatch.setattr("config.api_bootstrap.is_ctf_organizer", lambda _u: True)
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["permissions"]["is_ctf_organizer"] is True
