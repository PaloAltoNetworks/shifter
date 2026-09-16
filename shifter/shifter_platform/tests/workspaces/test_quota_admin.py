"""Tests for the superuser-only quota policy Django-admin escape hatch (PLAT-239)."""

from __future__ import annotations

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from workspaces.admin import WorkspaceQuotaPolicyAdmin
from workspaces.models import (
    QUOTA_MODE_ENFORCING,
    QUOTA_RESOURCE_MEMBER_SEATS,
    Organization,
    Workspace,
    WorkspaceQuotaPolicy,
)

User = get_user_model()


def _admin() -> WorkspaceQuotaPolicyAdmin:
    return WorkspaceQuotaPolicyAdmin(WorkspaceQuotaPolicy, AdminSite())


def _request(user):
    request = RequestFactory().post("/admin/")
    request.user = user
    return request


def test_identity_fields_are_editable_on_add():
    request = RequestFactory().get("/admin/")
    readonly = _admin().get_readonly_fields(request, None)
    assert "workspace" not in readonly
    assert "resource" not in readonly


def test_identity_fields_are_immutable_on_change():
    # save_model upserts by (workspace, resource); editing them on an existing row
    # would silently target a different policy, so they must be read-only on change.
    request = RequestFactory().get("/admin/")
    readonly = _admin().get_readonly_fields(request, WorkspaceQuotaPolicy())
    assert "workspace" in readonly
    assert "resource" in readonly


@pytest.mark.django_db
def test_save_model_routes_through_the_audited_service():
    superuser = User.objects.create_user(username="qa-su@e.com", email="qa-su@e.com", is_superuser=True, is_staff=True)
    workspace = Workspace.objects.create(organization=Organization.objects.create(name="Lab"), name="Team")
    obj = WorkspaceQuotaPolicy(
        workspace=workspace, resource=QUOTA_RESOURCE_MEMBER_SEATS, limit=3, mode=QUOTA_MODE_ENFORCING
    )

    _admin().save_model(_request(superuser), obj, form=None, change=False)

    persisted = WorkspaceQuotaPolicy.objects.get(workspace=workspace, resource=QUOTA_RESOURCE_MEMBER_SEATS)
    assert persisted.limit == 3
    assert persisted.mode == QUOTA_MODE_ENFORCING
    # The admin object reflects the persisted row so the change log resolves.
    assert obj.pk == persisted.pk
    assert obj.revision == persisted.revision


@pytest.mark.django_db
def test_permissions_are_superuser_only():
    admin = _admin()
    superuser = User.objects.create_user(
        username="qa-su2@e.com", email="qa-su2@e.com", is_superuser=True, is_staff=True
    )
    staff = User.objects.create_user(username="qa-staff@e.com", email="qa-staff@e.com", is_staff=True)
    su_req = _request(superuser)
    staff_req = _request(staff)

    assert admin.has_module_permission(su_req)
    assert admin.has_view_permission(su_req)
    assert admin.has_add_permission(su_req)
    assert admin.has_change_permission(su_req)
    assert admin.has_delete_permission(su_req) is False  # deletion disabled to keep changes audited

    assert not admin.has_module_permission(staff_req)
    assert not admin.has_add_permission(staff_req)
    assert not admin.has_change_permission(staff_req)
