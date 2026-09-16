"""Integration tests for the range-to-workspace scope administration API (#1944).

Drives the real DRF endpoints. Authority is the conjunction of a staff session
and workspace owner/admin role; authorization, the public-UUID contract, the
error envelope, and the audit are asserted against real rows.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from engine.models import Range as EngineRange
from engine.models import Request as EngineRequest
from shared.enums import RangeSource, RequestType, ResourceStatus
from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db

User = get_user_model()


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _items(resp) -> list:
    body = resp.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _list_url(workspace: Workspace) -> str:
    return f"/api/v1/cms/workspaces/{workspace.uuid}/range-scoping/"


def _rebind_url(request_id) -> str:
    return f"/api/v1/cms/ranges/{request_id}/workspace/"


@pytest.fixture
def aggregate_guard():
    """Expose the shared aggregate-guard seam, restoring the registry afterwards."""
    import shared.range_workspace_aggregate as agg

    saved = list(agg._guards)
    try:
        yield agg
    finally:
        agg._guards[:] = saved


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="API scope org")


@pytest.fixture
def staff_admin(db):
    return User.objects.create_user(username="api-staff@example.com", email="api-staff@example.com", is_staff=True)


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="api-owner@example.com", email="api-owner@example.com")


def _workspace(organization, name: str) -> Workspace:
    return Workspace.objects.create(organization=organization, name=name)


def _member(workspace, user, role: WorkspaceRole) -> None:
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role.value)


def _range(*, owner, workspace, range_source=RangeSource.MISSION_CONTROL.value) -> RangeInstance:
    request_id = uuid4()
    cms_request = CmsRequest.objects.create(
        workspace_id=workspace.id, request_id=request_id, request_type=RequestType.RANGE.value, user=owner
    )
    engine_request = EngineRequest.objects.create(
        request_id=request_id, request_type=RequestType.RANGE.value, user=owner
    )
    EngineRange.objects.create(
        workspace_id=workspace.id,
        uuid=uuid4(),
        user=owner,
        request=engine_request,
        cms_user_id=owner.id,
        status=EngineRange.Status.READY,
        subnet_index=EngineRange.allocate_subnet_index(),
    )
    return RangeInstance.objects.create(
        workspace_id=workspace.id,
        request=cms_request,
        scenario_id="basic",
        user_id=owner.id,
        range_source=range_source,
        status=ResourceStatus.READY.value,
    )


class TestRangeScopeListEndpoint:
    def test_staff_owner_lists_ranges(self, organization, staff_admin, owner):
        workspace = _workspace(organization, "Source")
        _member(workspace, staff_admin, WorkspaceRole.OWNER)
        _member(workspace, owner, WorkspaceRole.MEMBER)
        instance = _range(owner=owner, workspace=workspace)

        resp = _client(staff_admin).get(_list_url(workspace))

        assert resp.status_code == 200
        items = _items(resp)
        assert len(items) == 1
        row = items[0]
        assert row["request_id"] == str(instance.request.request_id)
        assert row["owner_id"] == owner.id
        assert row["range_source"] == RangeSource.MISSION_CONTROL.value
        assert row["is_reassignable"] is True
        # No internal ids or range detail leak.
        assert "workspace_id" not in row
        assert "range_spec" not in row
        assert "id" not in row

    def test_non_staff_is_forbidden_even_as_owner(self, organization, owner):
        workspace = _workspace(organization, "Source")
        _member(workspace, owner, WorkspaceRole.OWNER)

        resp = _client(owner).get(_list_url(workspace))

        assert resp.status_code == 403

    def test_staff_non_member_is_not_found(self, organization, staff_admin):
        workspace = _workspace(organization, "Source")

        resp = _client(staff_admin).get(_list_url(workspace))

        assert resp.status_code == 404


class TestRangeScopeRebindEndpoint:
    def _authorized(self, organization, staff_admin, owner):
        source = _workspace(organization, "Source")
        target = _workspace(organization, "Target")
        _member(source, staff_admin, WorkspaceRole.ADMIN)
        _member(target, staff_admin, WorkspaceRole.ADMIN)
        _member(source, owner, WorkspaceRole.MEMBER)
        _member(target, owner, WorkspaceRole.MEMBER)
        return source, target

    def test_staff_admin_rebinds_range(self, organization, staff_admin, owner):
        source, target = self._authorized(organization, staff_admin, owner)
        instance = _range(owner=owner, workspace=source)

        resp = _client(staff_admin).post(
            _rebind_url(instance.request.request_id),
            {"target_workspace_uuid": str(target.uuid)},
            format="json",
        )

        assert resp.status_code == 200
        assert resp.json()["changed"] is True
        assert RangeInstance.objects.get(pk=instance.pk).workspace_id == target.id

    def test_non_staff_is_forbidden(self, organization, owner):
        source = _workspace(organization, "Source")
        target = _workspace(organization, "Target")
        _member(source, owner, WorkspaceRole.OWNER)
        _member(target, owner, WorkspaceRole.OWNER)
        instance = _range(owner=owner, workspace=source)

        resp = _client(owner).post(
            _rebind_url(instance.request.request_id),
            {"target_workspace_uuid": str(target.uuid)},
            format="json",
        )

        assert resp.status_code == 403

    def test_malformed_target_uuid_is_400(self, organization, staff_admin, owner):
        source, _target = self._authorized(organization, staff_admin, owner)
        instance = _range(owner=owner, workspace=source)

        resp = _client(staff_admin).post(
            _rebind_url(instance.request.request_id),
            {"target_workspace_uuid": "not-a-uuid"},
            format="json",
        )

        assert resp.status_code == 400

    def test_domain_aggregate_bound_range_is_conflict(self, organization, staff_admin, owner, aggregate_guard):
        # A range the aggregate seam owns is refused with a bounded 409, keyed on
        # the authoritative guard rather than provenance (the range is MC-sourced).
        source, target = self._authorized(organization, staff_admin, owner)
        instance = _range(owner=owner, workspace=source, range_source=RangeSource.MISSION_CONTROL.value)
        bound_pk = instance.pk
        aggregate_guard.register_range_aggregate_guard(lambda pairs: {rid for _req, rid in pairs if rid == bound_pk})

        resp = _client(staff_admin).post(
            _rebind_url(instance.request.request_id),
            {"target_workspace_uuid": str(target.uuid)},
            format="json",
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "not_reassignable"

    def test_target_only_authority_is_conflict(self, organization, staff_admin, owner):
        source = _workspace(organization, "Source")
        target = _workspace(organization, "Target")
        _member(source, staff_admin, WorkspaceRole.ADMIN)  # source only
        _member(source, owner, WorkspaceRole.MEMBER)
        _member(target, owner, WorkspaceRole.MEMBER)
        instance = _range(owner=owner, workspace=source)

        resp = _client(staff_admin).post(
            _rebind_url(instance.request.request_id),
            {"target_workspace_uuid": str(target.uuid)},
            format="json",
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "target_denied"

    def test_unknown_range_is_not_found(self, organization, staff_admin, owner):
        _source, target = self._authorized(organization, staff_admin, owner)

        resp = _client(staff_admin).post(
            _rebind_url(uuid4()),
            {"target_workspace_uuid": str(target.uuid)},
            format="json",
        )

        assert resp.status_code == 404
