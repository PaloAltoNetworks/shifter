"""DRF boundary tests for the current-principal workspace context endpoint (#1938).

The console read is staff-session-only and rejects platform API tokens (unlike
the token-capable membership API). It is a side-effect-free projection of the
caller's existing memberships. Each test drives the boundary and asserts the
enforcement effect, so it goes red if the staff gate, the token rejection, or
the read-only guarantee is removed.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceOperation, WorkspaceRole

pytestmark = pytest.mark.django_db

CONTEXT_URL = "/api/v1/workspaces/context/"


def _user(django_user_model, suffix, *, is_staff=False):
    return django_user_model.objects.create_user(
        username=f"ctx-api-{suffix}@example.com",
        email=f"ctx-api-{suffix}@example.com",
        is_staff=is_staff,
    )


def _session_client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _token_client(user, *granted_scopes) -> APIClient:
    _, raw = ApiToken.create_token(name="ctx-api", created_by=user, scopes=list(granted_scopes))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def _workspace(org_name, ws_name, *, personal_for=None):
    return Workspace.objects.create(
        organization=Organization.objects.create(name=org_name),
        name=ws_name,
        personal_for_user=personal_for,
    )


def test_anonymous_is_denied():
    response = APIClient().get(CONTEXT_URL)

    assert response.status_code == 401


def test_non_staff_session_is_denied(django_user_model):
    user = _user(django_user_model, "member")
    workspace = _workspace("Acme", "Blue")
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role=WorkspaceRole.OWNER)

    response = _session_client(user).get(CONTEXT_URL)

    assert response.status_code == 403


def test_valid_staff_owned_token_is_rejected(django_user_model):
    # A valid platform token owned by a staff user must still be rejected: the
    # console read is session-only and never token-capable.
    staff = _user(django_user_model, "staff-token", is_staff=True)

    response = _token_client(staff, scopes.WORKSPACES_MEMBERSHIP_READ).get(CONTEXT_URL)

    assert response.status_code == 403


def test_staff_with_no_membership_gets_empty_projection(django_user_model):
    staff = _user(django_user_model, "empty", is_staff=True)

    response = _session_client(staff).get(CONTEXT_URL)

    assert response.status_code == 200
    assert response.json()["results"] == []
    # The read manufactured no personal workspace.
    assert Workspace.objects.filter(personal_for_user=staff).count() == 0


def test_staff_projection_spans_multiple_organizations(django_user_model):
    staff = _user(django_user_model, "multi", is_staff=True)
    ws_a = _workspace("Acme", "Blue", personal_for=staff)
    ws_b = _workspace("Beta", "Green")
    WorkspaceMembership.objects.create(workspace=ws_a, user=staff, role=WorkspaceRole.OWNER)
    WorkspaceMembership.objects.create(workspace=ws_b, user=staff, role=WorkspaceRole.MEMBER)

    response = _session_client(staff).get(CONTEXT_URL)

    assert response.status_code == 200
    results = response.json()["results"]
    assert [row["organization"]["name"] for row in results] == ["Acme", "Beta"]
    acme = results[0]
    assert acme["organization"]["uuid"] == str(ws_a.organization.uuid)
    assert acme["workspace_uuid"] == str(ws_a.uuid)
    assert acme["workspace_name"] == "Blue"
    assert acme["is_personal"] is True
    assert acme["role"] == WorkspaceRole.OWNER.value
    # An owner advertises membership-management capabilities; a member does not.
    assert WorkspaceOperation.ADD_MEMBER.value in acme["capabilities"]
    beta = results[1]
    assert beta["is_personal"] is False
    assert WorkspaceOperation.ADD_MEMBER.value not in beta["capabilities"]


def test_response_leaks_no_internal_identifiers(django_user_model):
    staff = _user(django_user_model, "leak", is_staff=True)
    workspace = _workspace("Acme", "Blue")
    WorkspaceMembership.objects.create(workspace=workspace, user=staff, role=WorkspaceRole.ADMIN)

    row = _session_client(staff).get(CONTEXT_URL).json()["results"][0]

    # Public UUIDs only: no internal PKs, emails, or rosters.
    assert "id" not in row
    assert "id" not in row["organization"]
    assert "user_id" not in row
    assert "email" not in str(row)


def test_ordering_query_param_does_not_error(django_user_model):
    # The view returns a materialized list, so the globally configured ordering
    # backend must not apply; an advertised ?ordering= request must not 500.
    staff = _user(django_user_model, "ordering", is_staff=True)
    workspace = _workspace("Acme", "Blue")
    WorkspaceMembership.objects.create(workspace=workspace, user=staff, role=WorkspaceRole.MEMBER)

    response = _session_client(staff).get(CONTEXT_URL, {"ordering": "workspace_name", "search": "x"})

    assert response.status_code == 200
    assert len(response.json()["results"]) == 1


def test_get_queryset_returns_empty_without_an_actor(rf, monkeypatch):
    # Defensive branch: IsStaffSession guarantees an actor in the real flow, but
    # get_queryset fails closed to an empty projection if none is resolved.
    from workspaces.api import views as views_module

    monkeypatch.setattr(views_module, "active_actor_user", lambda request: None)
    view = views_module.PrincipalWorkspaceContextView()
    view.request = rf.get(CONTEXT_URL)

    assert view.get_queryset() == []


def test_get_creates_no_tenancy_rows(django_user_model):
    staff = _user(django_user_model, "sidefx", is_staff=True)
    workspace = _workspace("Acme", "Blue")
    WorkspaceMembership.objects.create(workspace=workspace, user=staff, role=WorkspaceRole.MEMBER)
    before = (Organization.objects.count(), Workspace.objects.count(), WorkspaceMembership.objects.count())

    _session_client(staff).get(CONTEXT_URL)

    after = (Organization.objects.count(), Workspace.objects.count(), WorkspaceMembership.objects.count())
    assert before == after
