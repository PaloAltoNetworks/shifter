"""Administer API tests for runtime Mission Control lease policy (#2169)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from cms.models import MissionControlGroupLeasePolicy, MissionControlTenantLeasePolicy
from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import MISSION_CONTROL_RANGE_READ
from shared.audit import AuditAction, AuditEntityType
from shared.models import AuditLog

pytestmark = pytest.mark.django_db

User = get_user_model()
SETTINGS_URL = "/api/v1/administer/mission-control/lease-policy/"


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _body(*, expected_revision=0, initial=14, extension=7, maximum=90, enabled=True):
    return {
        "expected_revision": expected_revision,
        "initial_days": initial,
        "extension_days": extension,
        "maximum_days": maximum,
        "extensions_enabled": enabled,
    }


@pytest.fixture
def admin():
    return User.objects.create_superuser(username="lease-api-admin", email="lease-api-admin@example.com", password="pw")


def test_settings_projection_shows_baseline_precedence_and_eligible_groups(admin):
    eligible = Group.objects.create(name="Range Operators")
    Group.objects.get_or_create(name="CTF Participant")

    response = _client(admin).get(SETTINGS_URL)

    assert response.status_code == 200
    payload = response.json()
    assert {key: payload[key] for key in ("baseline", "tenant_override", "effective_tenant", "effective_source")} == {
        "baseline": {
            "initial_days": 30,
            "extension_days": 30,
            "maximum_days": 365,
            "extensions_enabled": True,
        },
        "tenant_override": None,
        "effective_tenant": {
            "initial_days": 30,
            "extension_days": 30,
            "maximum_days": 365,
            "extensions_enabled": True,
        },
        "effective_source": "deployment",
    }
    assert payload["tenant_revision"] == 0
    assert {group["id"] for group in payload["groups"]} >= {eligible.pk}
    assert all(group["name"] != "CTF Participant" for group in payload["groups"])
    assert next(group for group in payload["groups"] if group["id"] == eligible.pk) == {
        "id": eligible.pk,
        "name": eligible.name,
        "revision": 0,
        "override": None,
    }


def test_superuser_can_replace_and_reset_tenant_policy_with_strict_audit(admin):
    client = _client(admin)

    replaced = client.put(f"{SETTINGS_URL}tenant/", _body(), format="json", HTTP_X_REQUEST_ID="req-api-2169")

    assert replaced.status_code == 200
    assert replaced.json()["tenant_override"] == {
        "policy": {
            "initial_days": 14,
            "extension_days": 7,
            "maximum_days": 90,
            "extensions_enabled": True,
        },
        "revision": 1,
    }
    row = MissionControlTenantLeasePolicy.objects.get()
    audit = AuditLog.objects.get(
        entity_type=AuditEntityType.CONFIG,
        entity_id=row.pk,
        action=AuditAction.UPDATE,
        context="mission_control_tenant_lease_policy",
    )
    assert audit.actor_id == admin.pk
    assert audit.request_id == "req-api-2169"

    reset = client.post(f"{SETTINGS_URL}tenant/reset/", {"expected_revision": 1}, format="json")
    assert reset.status_code == 200
    assert reset.json()["tenant_override"] is None
    assert reset.json()["tenant_revision"] == 2
    assert not MissionControlTenantLeasePolicy.objects.exists()


def test_superuser_can_replace_and_reset_eligible_group_policy(admin):
    group = Group.objects.create(name="Blue Team")
    client = _client(admin)

    replaced = client.put(f"{SETTINGS_URL}groups/{group.pk}/", _body(maximum=60), format="json")

    assert replaced.status_code == 200
    group_state = replaced.json()["groups"][0]
    assert group_state["id"] == group.pk
    assert group_state["revision"] == 1
    assert group_state["override"]["revision"] == 1
    assert group_state["override"]["policy"]["maximum_days"] == 60
    assert MissionControlGroupLeasePolicy.objects.filter(group=group).exists()

    reset = client.post(
        f"{SETTINGS_URL}groups/{group.pk}/reset/",
        {"expected_revision": 1},
        format="json",
    )
    assert reset.status_code == 200
    assert reset.json()["groups"][0]["override"] is None
    assert reset.json()["groups"][0]["revision"] == 2


def test_group_policy_above_the_tenant_maximum_is_rejected(admin):
    group = Group.objects.create(name="Bounded API group")

    response = _client(admin).put(
        f"{SETTINGS_URL}groups/{group.pk}/",
        _body(maximum=366),
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_policy"
    assert not MissionControlGroupLeasePolicy.objects.filter(group=group).exists()


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", "groups/999999/", _body()),
        ("post", "groups/999999/reset/", {"expected_revision": 0}),
    ],
)
def test_group_policy_endpoints_return_not_found_for_a_missing_group(admin, method, path, body):
    response = getattr(_client(admin), method)(f"{SETTINGS_URL}{path}", body, format="json")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "group_not_found"


@pytest.mark.parametrize(
    "body",
    [
        _body(initial="14"),
        _body(enabled=1),
        _body(initial=91, maximum=90),
        {**_body(), "deadline": "2099-01-01T00:00:00Z"},
        {"expected_revision": 0, "initial_days": 14},
        [],
    ],
)
def test_policy_commands_reject_coerced_partial_unknown_and_non_object_input(admin, body):
    response = _client(admin).put(f"{SETTINGS_URL}tenant/", body, format="json")

    assert response.status_code == 400
    assert not MissionControlTenantLeasePolicy.objects.exists()


def test_stale_revision_maps_to_stable_conflict_envelope(admin):
    client = _client(admin)
    assert client.put(f"{SETTINGS_URL}tenant/", _body(), format="json").status_code == 200

    response = client.put(f"{SETTINGS_URL}tenant/", _body(expected_revision=0, initial=10), format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "revision_conflict"
    assert "refresh" in response.json()["error"]["message"].lower()


def test_only_active_superuser_sessions_can_use_the_surface(admin):
    staff = User.objects.create_user(username="staff", is_staff=True)
    regular = User.objects.create_user(username="regular")
    assert APIClient().get(SETTINGS_URL).status_code in (401, 403)
    assert _client(regular).get(SETTINGS_URL).status_code == 403
    assert _client(staff).get(SETTINGS_URL).status_code == 403

    admin.is_active = False
    admin.save(update_fields=["is_active"])
    assert _client(admin).get(SETTINGS_URL).status_code == 403


def test_platform_api_token_is_rejected(admin):
    _token, raw = ApiToken.create_token(
        name="lease-read-token",
        created_by=admin,
        scopes=[MISSION_CONTROL_RANGE_READ],
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    assert client.get(SETTINGS_URL).status_code == 403


def test_real_session_requires_csrf_for_mutation(admin):
    client = APIClient(enforce_csrf_checks=True)
    assert client.login(username=admin.username, password="pw")

    response = client.put(f"{SETTINGS_URL}tenant/", _body(), format="json")

    assert response.status_code == 403
    assert not MissionControlTenantLeasePolicy.objects.exists()
