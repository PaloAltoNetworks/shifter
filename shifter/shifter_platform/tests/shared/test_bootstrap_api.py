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


def test_platform_spa_feature_flag_reported(user, settings):
    settings.PLATFORM_SPA_ENABLED = True
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["platform_spa"] is True


def test_mission_control_spa_feature_flag_reported(user, settings):
    settings.MISSION_CONTROL_SPA_ENABLED = True
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["mission_control_spa"] is True


def test_mission_control_spa_feature_flag_default_false(user, settings):
    settings.MISSION_CONTROL_SPA_ENABLED = False
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["mission_control_spa"] is False


def test_scenario_editor_spa_feature_flag_reported(user, settings):
    settings.SCENARIO_EDITOR_SPA_ENABLED = True
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["scenario_editor_spa"] is True


def test_scenario_editor_spa_feature_flag_default_false(user, settings):
    settings.SCENARIO_EDITOR_SPA_ENABLED = False
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["scenario_editor_spa"] is False


def test_ctf_workspace_spa_feature_flag_reported(user, settings):
    settings.CTF_WORKSPACE_SPA_ENABLED = True
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["ctf_workspace_spa"] is True


def test_ctf_workspace_spa_feature_flag_default_false(user, settings):
    settings.CTF_WORKSPACE_SPA_ENABLED = False
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["ctf_workspace_spa"] is False


def test_aces_native_provisioning_feature_flag_reported(user, settings):
    settings.ACES_NATIVE_PROVISIONING_ENABLED = True
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["aces_native_provisioning"] is True


def test_aces_native_provisioning_feature_flag_default_false(user, settings):
    settings.ACES_NATIVE_PROVISIONING_ENABLED = False
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["aces_native_provisioning"] is False


def test_administer_spa_feature_flag_reported(user, settings):
    settings.ADMINISTER_SPA_ENABLED = True
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["administer_spa"] is True


def test_administer_spa_feature_flag_default_false(user, settings):
    settings.ADMINISTER_SPA_ENABLED = False
    client = APIClient()
    client.force_authenticate(user=user)
    body = client.get(BOOTSTRAP_URL).json()
    assert body["feature_flags"]["administer_spa"] is False


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
