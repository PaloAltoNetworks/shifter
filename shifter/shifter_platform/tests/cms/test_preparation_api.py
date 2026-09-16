"""HTTP admission does not confuse content authoring with executable authority."""

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from engine.models import PreparationAdapter
from shared.api_tokens.models import ApiToken
from tests.engine.services.test_preparation_adapters import administrator, grant
from tests.shared.raes.test_preparation_contract import manifest_payload

pytestmark = pytest.mark.django_db
__all__ = ["administrator", "grant"]
URL = "/api/v1/cms/preparation-adapters/"


def body(grant):
    return {"grant_id": str(grant.id), "manifest": manifest_payload()}


def test_staff_session_cannot_install_or_inspect_private_adapters(grant):
    client = APIClient()
    client.force_authenticate(user=User.objects.create_user(username="ordinary-staff", is_staff=True))
    assert client.post(URL, body(grant), format="json").status_code == 403
    assert client.get(URL).status_code == 403
    assert not PreparationAdapter.objects.exists()


def test_explicit_administrator_installs_and_retires_without_platform_release(administrator, grant):
    client = APIClient()
    client.force_authenticate(user=administrator)
    installed = client.post(URL, body(grant), format="json")
    assert installed.status_code == 201
    identity = installed.json()["id"]
    response = client.post(f"{URL}{identity}/state/", {"state": "retired"}, format="json")
    assert response.status_code == 200
    assert response.json()["state"] == "retired"
    assert PreparationAdapter.objects.get(pk=identity).manifest["worker_image"].endswith("b" * 64)


def test_content_authoring_token_does_not_authorize_adapter_installation(administrator, grant):
    _, raw = ApiToken.create_token(name="content-only", created_by=administrator, scopes=["cms:authoring:write"])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert client.post(URL, body(grant), format="json").status_code == 403
    assert not PreparationAdapter.objects.exists()


def test_dedicated_token_scope_and_actor_permission_are_both_required(administrator, grant):
    _, raw = ApiToken.create_token(
        name="adapter-installer", created_by=administrator, scopes=["cms:preparation-adapters:write"]
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert client.post(URL, body(grant), format="json").status_code == 201
    administrator.user_permissions.clear()
    assert client.post(URL, body(grant), format="json").status_code == 403


def test_session_mutation_requires_csrf(administrator, grant):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(administrator)
    assert client.post(URL, body(grant), format="json").status_code == 403
    assert not PreparationAdapter.objects.exists()


def test_installer_cannot_supply_a_job_command_or_service_account(administrator, grant):
    client = APIClient()
    client.force_authenticate(user=administrator)
    request = body(grant)
    request["service_account"] = "platform-controller"
    assert client.post(URL, request, format="json").status_code == 400
    assert not PreparationAdapter.objects.exists()


def test_install_audit_uses_canonical_vocabulary_and_token_attribution(administrator, grant):
    from shared.models import AuditLog

    token, raw = ApiToken.create_token(
        name="attributed-installer", created_by=administrator, scopes=["cms:preparation-adapters:write"]
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert client.post(URL, body(grant), format="json").status_code == 201
    event = AuditLog.objects.get(entity_type="preparation_adapter")
    assert event.actor_type == "apikey"
    assert event.actor_id == token.id
    assert event.request_id
    event.full_clean()
