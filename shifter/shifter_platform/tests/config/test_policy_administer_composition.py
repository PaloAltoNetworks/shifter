"""Prepared composed user administration uses root and effect-specific policy."""

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from tests.cms.test_policy_offboarding import owned_resources as _owned_resources
from tests.workspaces.test_account_policy_admin import Provider

owned_resources = _owned_resources

pytestmark = pytest.mark.django_db


def test_service_administrator_offboarding_adapter_has_no_superuser_veto(owned_resources, monkeypatch):
    from config.api_account_administration import PolicyAdministerTransferOwnershipView

    actor, source, destination, workspace, *_ = owned_resources
    monkeypatch.setattr("config.api_account_administration.configured_authorization_provider", Provider)
    request = APIRequestFactory().post(
        "/api/v1/administer/users/transfer-ownership/",
        {"replacement_user_id": destination.pk, "resource_kinds": ["workspaces"]},
        format="json",
    )
    request.credential_context = actor
    force_authenticate(request, token=actor)
    response = PolicyAdministerTransferOwnershipView.as_view()(request, pk=source.pk)
    assert response.status_code == 200 and response.data["workspaces_transferred"] == 1
    workspace.refresh_from_db()
    assert workspace.ownerships.get().principal_uuid != actor.principal.uuid
