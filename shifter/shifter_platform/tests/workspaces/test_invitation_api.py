"""Session-only admin boundary tests for workspace invitations (#1942)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from workspaces.models import Organization, Workspace, WorkspaceInvitation, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db


def _user(django_user_model, suffix: str, *, staff: bool = True):
    return django_user_model.objects.create_user(
        username=f"invitation-api-{suffix}@example.com",
        email=f"invitation-api-{suffix}@example.com",
        is_staff=staff,
    )


@pytest.fixture
def invitation_workspace(django_user_model):
    owner = _user(django_user_model, "owner")
    workspace = Workspace.objects.create(
        organization=Organization.objects.create(name="Invitation API Lab"),
        name="Invitation API Workspace",
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role=WorkspaceRole.OWNER)
    return workspace, owner


def _urls(workspace):
    base = f"/api/v1/workspaces/{workspace.uuid}/invitations/"
    return {
        "collection": base,
        "resend": lambda invitation_uuid: f"{base}{invitation_uuid}/resend/",
        "revoke": lambda invitation_uuid: f"{base}{invitation_uuid}/revoke/",
    }


def _session_client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_staff_owner_can_issue_list_resend_and_revoke(invitation_workspace, settings):
    settings.SITE_URL = "https://shifter.example.test"
    workspace, owner = invitation_workspace
    urls = _urls(workspace)
    client = _session_client(owner)

    issued = client.post(
        urls["collection"],
        {"email": "New.Member@Example.com", "role": WorkspaceRole.ADMIN},
        format="json",
    )
    invitation_uuid = issued.json()["invitation_uuid"]
    listed = client.get(urls["collection"])
    resent = client.post(urls["resend"](invitation_uuid), {}, format="json")
    revoked = client.post(urls["revoke"](invitation_uuid), {}, format="json")

    assert issued.status_code == 201
    assert set(issued.json()) == {
        "invitation_uuid",
        "workspace_uuid",
        "email",
        "role",
        "status",
        "expires_at",
        "created_at",
        "updated_at",
    }
    assert issued.json()["email"] == "new.member@example.com"
    assert listed.status_code == 200
    assert [row["invitation_uuid"] for row in listed.json()] == [invitation_uuid]
    assert resent.status_code == 200
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"


def test_invitation_admin_is_additively_staff_and_workspace_authorized(
    invitation_workspace, django_user_model, settings
):
    settings.SITE_URL = "https://shifter.example.test"
    workspace, owner = invitation_workspace
    nonstaff_admin = _user(django_user_model, "nonstaff", staff=False)
    unrelated_staff = _user(django_user_model, "unrelated")
    WorkspaceMembership.objects.create(workspace=workspace, user=nonstaff_admin, role=WorkspaceRole.ADMIN)

    assert _session_client(nonstaff_admin).get(_urls(workspace)["collection"]).status_code == 403
    denied = _session_client(unrelated_staff).get(_urls(workspace)["collection"])
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "workspace_access_denied"
    assert _session_client(owner).get(_urls(workspace)["collection"]).status_code == 200


def test_platform_api_token_is_rejected_even_for_staff_owner(invitation_workspace):
    workspace, owner = invitation_workspace
    _token, raw = ApiToken.create_token(
        name="must-not-administer-invitations",
        created_by=owner,
        scopes=[scopes.WORKSPACES_MEMBERSHIP_WRITE],
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.get(_urls(workspace)["collection"])

    assert response.status_code == 403


def test_issue_validation_and_duplicate_have_bounded_errors(invitation_workspace, settings):
    settings.SITE_URL = "https://shifter.example.test"
    workspace, owner = invitation_workspace
    client = _session_client(owner)

    malformed = client.post(
        _urls(workspace)["collection"],
        {"email": "not-an-email", "role": "root"},
        format="json",
    )
    first = client.post(
        _urls(workspace)["collection"],
        {"email": "duplicate@example.com", "role": WorkspaceRole.MEMBER},
        format="json",
    )
    duplicate = client.post(
        _urls(workspace)["collection"],
        {"email": "DUPLICATE@example.com", "role": WorkspaceRole.MEMBER},
        format="json",
    )

    assert malformed.status_code == 400
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "invitation_exists"
    assert WorkspaceInvitation.objects.filter(workspace=workspace).count() == 1
