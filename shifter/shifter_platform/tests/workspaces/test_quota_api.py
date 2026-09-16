"""DRF boundary tests for the workspace quota surface (PLAT-239, issue #1946).

Drives the real read endpoint through its authority boundary (owner/admin read;
plain member and non-member denied) and proves the member-seat hard cap surfaces
as a 409 on the membership API.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from workspaces.models import (
    QUOTA_MODE_ENFORCING,
    QUOTA_RESOURCE_MEMBER_SEATS,
    Organization,
    Workspace,
    WorkspaceMembership,
    WorkspaceQuotaPolicy,
)
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db


def _quota_url(workspace_uuid) -> str:
    return f"/api/v1/workspaces/{workspace_uuid}/quota/"


def _user(django_user_model, suffix):
    return django_user_model.objects.create_user(username=f"wq-api-{suffix}@e.com", email=f"wq-api-{suffix}@e.com")


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _workspace(owner) -> Workspace:
    workspace = Workspace.objects.create(organization=Organization.objects.create(name="Lab"), name="Team")
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role=WorkspaceRole.OWNER.value)
    return workspace


def test_owner_reads_quota_usage(django_user_model):
    owner = _user(django_user_model, "owner")
    workspace = _workspace(owner)
    WorkspaceQuotaPolicy.objects.create(
        workspace=workspace, resource=QUOTA_RESOURCE_MEMBER_SEATS, limit=3, mode=QUOTA_MODE_ENFORCING
    )

    response = _client(owner).get(_quota_url(workspace.uuid))

    assert response.status_code == 200
    body = response.json()
    assert body["workspace_uuid"] == str(workspace.uuid)
    seats = next(r for r in body["resources"] if r["resource"] == QUOTA_RESOURCE_MEMBER_SEATS)
    assert seats["usage"] == 1
    assert seats["limit"] == 3
    assert seats["mode"] == QUOTA_MODE_ENFORCING


def test_plain_member_cannot_read_quota(django_user_model):
    owner = _user(django_user_model, "owner")
    member = _user(django_user_model, "member")
    workspace = _workspace(owner)
    WorkspaceMembership.objects.create(workspace=workspace, user=member, role=WorkspaceRole.MEMBER.value)

    response = _client(member).get(_quota_url(workspace.uuid))
    assert response.status_code == 403


def test_anonymous_cannot_read_quota(django_user_model):
    workspace = _workspace(_user(django_user_model, "owner"))
    response = APIClient().get(_quota_url(workspace.uuid))
    assert response.status_code in (401, 403)


def test_seat_hard_cap_surfaces_as_409_on_membership_add(django_user_model):
    owner = _user(django_user_model, "owner")
    workspace = _workspace(owner)  # 1 seat (owner)
    WorkspaceQuotaPolicy.objects.create(
        workspace=workspace, resource=QUOTA_RESOURCE_MEMBER_SEATS, limit=1, mode=QUOTA_MODE_ENFORCING
    )
    target = _user(django_user_model, "target")

    response = _client(owner).post(
        f"/api/v1/workspaces/{workspace.uuid}/memberships/",
        {"email": target.email, "role": WorkspaceRole.MEMBER.value},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "workspace_member_seats_exhausted"
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=target).exists()
