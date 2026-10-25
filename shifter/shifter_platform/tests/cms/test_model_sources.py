"""Source administration uses session authority and secret-free readback."""

import json

import pytest
from rest_framework.test import APIClient

from tests.engine.services.test_model_sources import configuration, source_tenant

__all__ = ["source_tenant"]

pytestmark = pytest.mark.django_db


def test_source_api_registers_lists_and_conflicts_without_echoing_credentials(source_tenant):
    admin, member, org, _store = source_tenant
    client = APIClient()
    client.force_authenticate(user=admin)
    url = f"/api/v1/cms/organizations/{org.uuid}/model-sources/"
    payload = {"configuration": configuration(), "credential": {"api_key": "synthetic-secret"}}
    response = client.post(url, payload, format="json")
    assert response.status_code == 201
    assert "synthetic-secret" not in response.content.decode()
    source_id = response.json()["id"]
    assert len(client.get(url).json()["results"]) == 1
    edited = client.put(f"{url}{source_id}/", {"expected_revision": 0, "configuration": configuration()}, format="json")
    assert edited.status_code == 409
    client.force_authenticate(user=member)
    assert client.post(url, payload, format="json").status_code == 403
    assert client.get(url).status_code == 403
    assert client.get(f"{url}available/").json()["results"] == []


def test_source_api_rejects_duplicate_and_unknown_members_before_mutation(source_tenant):
    admin, _, org, store = source_tenant
    client = APIClient()
    client.force_authenticate(user=admin)
    url = f"/api/v1/cms/organizations/{org.uuid}/model-sources/"
    raw = '{"configuration":' + json.dumps(configuration()) + ',"configuration":{}}'
    assert client.post(url, raw, content_type="application/json").status_code == 400
    assert client.post(url, {"configuration": configuration(), "owner_id": 99}, format="json").status_code == 400
    store.create_owned_secret.assert_not_called()


def test_credential_cleanup_is_tenant_admin_only_and_has_no_client_secret_reference(source_tenant):
    from uuid import uuid4

    from engine.services import create_model_source

    admin, member, org, store = source_tenant
    source = create_model_source(admin, org.uuid, configuration(), credential={"api_key": "synthetic-secret"})
    client = APIClient()
    url = f"/api/v1/cms/organizations/{org.uuid}/model-sources/{source.id}/retire-credentials/"
    client.force_authenticate(user=member)
    assert client.post(url, {}, format="json").status_code == 403
    client.force_authenticate(user=admin)
    assert client.post(url.replace(str(org.uuid), str(uuid4())), {}, format="json").status_code == 403
    assert client.post(url, {"credential_reference": "foreign-secret"}, format="json").status_code == 400
    result = client.post(url, {}, format="json")
    assert result.status_code == 200 and result.json() == {"retired": 0}
    store.retire_owned_secret.assert_not_called()


def test_source_user_directory_is_tenant_scoped_and_rechecks_active_admin(source_tenant):
    from django.contrib.auth.models import User

    from workspaces.models import Organization, Workspace, WorkspaceMembership

    admin, member, org, _ = source_tenant
    foreign = User.objects.create_user(username="foreign-source-user")
    foreign_workspace = Workspace.objects.create(
        name="Foreign", organization=Organization.objects.create(name="Foreign")
    )
    WorkspaceMembership.objects.create(user=foreign, workspace=foreign_workspace, role="member")
    client = APIClient()
    url = f"/api/v1/cms/organizations/{org.uuid}/model-source-users/"
    client.force_authenticate(user=member)
    assert client.get(url).status_code == 403
    client.force_authenticate(user=admin)
    response = client.get(url)
    assert response.status_code == 200
    assert {row["id"] for row in response.json()["results"]} == {admin.pk, member.pk}
    User.objects.filter(pk=admin.pk).update(is_active=False)
    assert client.get(url).status_code == 403


def test_usable_source_metadata_does_not_disclose_other_users(source_tenant):
    from engine.services import create_model_source

    admin, member, org, _ = source_tenant
    create_model_source(
        admin,
        org.uuid,
        configuration(allowed_user_ids=[admin.pk, member.pk]),
        credential={"api_key": "synthetic-secret"},
    )
    client = APIClient()
    client.force_authenticate(user=member)
    response = client.get(f"/api/v1/cms/organizations/{org.uuid}/model-sources/available/")
    assert response.status_code == 200
    assert response.json()["results"][0]["configuration"]["allowed_user_ids"] == []
