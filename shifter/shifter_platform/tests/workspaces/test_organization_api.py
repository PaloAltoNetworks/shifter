"""DRF boundary tests for the organization profile API (ADR-048, PLAT-232).

Drives the real endpoint through its authority boundary: only a session-
authenticated organization admin or Django superuser may read/update; tokens and
anonymous callers are refused; the wire carries the public UUID only; and the
opaque denial hides the missing-versus-forbidden distinction.
"""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from workspaces.models import Organization, OrganizationMembership
from workspaces.roles import OrganizationRole

pytestmark = pytest.mark.django_db


def _user(django_user_model, suffix: str, *, is_superuser: bool = False):
    return django_user_model.objects.create_user(
        username=f"org-api-{suffix}@example.com",
        email=f"org-api-{suffix}@example.com",
        is_superuser=is_superuser,
        is_staff=is_superuser,
    )


@pytest.fixture
def organization():
    return Organization.objects.create(name="API Lab", description="orig")


def _admin(django_user_model, organization, suffix="admin"):
    actor = _user(django_user_model, suffix)
    OrganizationMembership.objects.create(organization=organization, user=actor, role=OrganizationRole.ADMIN)
    return actor


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _url(org_uuid) -> str:
    return f"/api/v1/workspaces/organizations/{org_uuid}/"


_LIST_URL = "/api/v1/workspaces/organizations/"


def test_anonymous_request_is_denied(organization):
    response = APIClient().get(_url(organization.uuid))

    assert response.status_code == 401


def test_platform_token_is_rejected(organization, django_user_model):
    admin = _admin(django_user_model, organization)
    _, raw = ApiToken.create_token(name="org-api", created_by=admin, scopes=[scopes.WORKSPACES_MEMBERSHIP_READ])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.get(_url(organization.uuid))

    # The endpoint is session-only; a valid token principal is refused even when
    # its owner is an organization admin.
    assert response.status_code in (401, 403)


def test_admin_reads_the_profile_with_uuid_only_on_the_wire(organization, django_user_model):
    admin = _admin(django_user_model, organization)

    response = _client(admin).get(_url(organization.uuid))

    assert response.status_code == 200
    body = response.json()
    assert body["uuid"] == str(organization.uuid)
    assert body["name"] == "API Lab"
    assert body["description"] == "orig"
    assert set(body) == {"uuid", "name", "description", "support_email", "support_url", "created_at", "updated_at"}
    # The internal integer primary key must never appear on the public surface.
    assert "id" not in body
    assert str(organization.pk) not in {str(body["uuid"]), body["name"]}


def test_superuser_reads_any_organization(organization, django_user_model):
    superuser = _user(django_user_model, "root", is_superuser=True)

    response = _client(superuser).get(_url(organization.uuid))

    assert response.status_code == 200


def test_non_admin_read_is_forbidden(organization, django_user_model):
    outsider = _user(django_user_model, "outsider")

    response = _client(outsider).get(_url(organization.uuid))

    assert response.status_code == 403


def test_missing_and_forbidden_are_indistinguishable(organization, django_user_model):
    outsider = _user(django_user_model, "outsider")

    missing = _client(outsider).get(_url(uuid.uuid4()))
    forbidden = _client(outsider).get(_url(organization.uuid))

    assert missing.status_code == forbidden.status_code == 403
    # Same code and message either way (only the per-request request_id differs),
    # so the response cannot reveal whether the organization exists.
    assert missing.json()["error"]["code"] == forbidden.json()["error"]["code"]
    assert missing.json()["error"]["message"] == forbidden.json()["error"]["message"]


def test_admin_updates_supplied_fields(organization, django_user_model):
    admin = _admin(django_user_model, organization)

    response = _client(admin).patch(
        _url(organization.uuid),
        {"description": "updated", "support_email": "h@e.com"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["description"] == "updated"
    assert response.json()["support_email"] == "h@e.com"
    organization.refresh_from_db()
    assert organization.description == "updated"


def test_update_rejects_a_malformed_email(organization, django_user_model):
    admin = _admin(django_user_model, organization)

    response = _client(admin).patch(_url(organization.uuid), {"support_email": "not-an-email"}, format="json")

    assert response.status_code == 400
    organization.refresh_from_db()
    assert organization.support_email == ""


def test_update_rejects_an_unknown_field(organization, django_user_model):
    admin = _admin(django_user_model, organization)

    response = _client(admin).patch(_url(organization.uuid), {"is_superuser": True}, format="json")

    assert response.status_code == 400


def test_non_admin_update_is_forbidden(organization, django_user_model):
    outsider = _user(django_user_model, "outsider")

    response = _client(outsider).patch(_url(organization.uuid), {"description": "hacked"}, format="json")

    assert response.status_code == 403
    organization.refresh_from_db()
    assert organization.description == "orig"


def test_administrable_list_returns_only_the_actor_admin_organizations(organization, django_user_model):
    admin = _admin(django_user_model, organization)
    Organization.objects.create(name="Unadministered")

    response = _client(admin).get(_LIST_URL)

    assert response.status_code == 200
    uuids = [row["uuid"] for row in response.json()["results"]]
    assert uuids == [str(organization.uuid)]


def test_administrable_list_is_anonymous_denied(organization):
    assert APIClient().get(_LIST_URL).status_code == 401
