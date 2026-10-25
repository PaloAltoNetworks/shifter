"""Prepared workspace lifecycle commands enforce application policy directly."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from management.models import Principal
from shared.authorization import AuthorizationDecision, CredentialCeiling, DecisionKind
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef
from shared.models import AuditLog
from workspaces import services
from workspaces.models import Organization, Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db


class Provider:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.requests = []

    def check(self, request):
        self.requests.append(request)
        return AuthorizationDecision(
            DecisionKind.ALLOWED if self.allowed else DecisionKind.DENIED,
            "policy_allowed" if self.allowed else "policy_denied",
        )


def _actor():
    principal = Principal.objects.create(kind="service", name="Administrator")
    return CredentialContext(
        PrincipalRef(principal.uuid, "service"),
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"workspace.update", "workspace.archive", "workspace.restore"})),
        frozenset(),
    )


def test_service_admin_renames_archives_and_restores_with_policy_and_audit():
    account = services.create_account(kind="team", name="Customer")
    organization = Organization.objects.get(account_id=account.id, is_default=True)
    workspace = Workspace.objects.create(organization=organization, name="Extra")
    actor = _actor()
    provider = Provider()

    renamed = services.admin_rename_workspace(actor, provider, workspace.uuid, "Renamed")
    archived = services.admin_archive_workspace(actor, provider, workspace.uuid)
    restored = services.admin_restore_workspace(actor, provider, workspace.uuid)

    assert renamed.name == "Renamed"
    assert archived.is_archived
    assert not restored.is_archived
    assert [request.action for request in provider.requests] == [
        "workspace.update",
        "workspace.archive",
        "workspace.restore",
    ]
    assert (
        AuditLog.objects.filter(
            entity_type="workspace", entity_id=workspace.id, actor_principal_uuid=actor.principal.uuid
        ).count()
        == 3
    )


def test_workspace_lifecycle_denial_and_default_archive_leave_state_unchanged():
    account = services.create_account(kind="team", name="Customer")
    workspace = Workspace.objects.get(organization__account_id=account.id, is_default=True)
    actor = _actor()

    with pytest.raises(services.AccountScopeError):
        services.admin_rename_workspace(actor, Provider(allowed=False), workspace.uuid, "Nope")
    with pytest.raises(services.WorkspaceLifecycleError):
        services.admin_archive_workspace(actor, Provider(), workspace.uuid)
    workspace.refresh_from_db()
    assert workspace.name == "Default"
    assert workspace.archived_at is None


def test_service_admin_workspace_lifecycle_http_adapters(monkeypatch):
    from workspaces.api.account_admin_views import (
        AccountWorkspaceArchiveView,
        AccountWorkspaceRenameView,
        AccountWorkspaceRestoreView,
    )

    account = services.create_account(kind="team", name="Customer")
    organization = Organization.objects.get(account_id=account.id, is_default=True)
    workspace = Workspace.objects.create(organization=organization, name="Extra")
    actor = _actor()
    monkeypatch.setattr("workspaces.api.account_admin_views.configured_authorization_provider", Provider)

    def invoke(view, data):
        request = APIRequestFactory().post("/api/v1/accounts/workspace/", data, format="json")
        request.credential_context = actor
        force_authenticate(request, token=actor)
        return view.as_view()(request, workspace_uuid=workspace.uuid)

    renamed = invoke(AccountWorkspaceRenameView, {"name": "Renamed"})
    archived = invoke(AccountWorkspaceArchiveView, {})
    restored = invoke(AccountWorkspaceRestoreView, {})

    assert renamed.status_code == 200 and renamed.data["name"] == "Renamed"
    assert archived.status_code == 200 and archived.data["is_archived"]
    assert restored.status_code == 200 and not restored.data["is_archived"]


def test_integer_owner_bridge_changes_principal_facts_without_role_grants():
    account = services.create_account(kind="team", name="Customer")
    organization = Organization.objects.get(account_id=account.id, is_default=True)
    workspace = Workspace.objects.create(organization=organization, name="Extra")
    source = get_user_model().objects.create_user(username=f"source-{uuid4()}")
    target = get_user_model().objects.create_user(username=f"target-{uuid4()}")
    WorkspaceMembership.objects.create(workspace=workspace, user=source, role="owner")
    WorkspaceMembership.objects.create(workspace=workspace, user=target, role="admin")
    actor = _actor()
    actor = CredentialContext(
        actor.principal,
        actor.kind,
        actor.credential_uuid,
        CredentialCeiling(frozenset({"workspace.transfer"})),
        actor.scopes,
    )
    from workspaces.models import WorkspaceOwnership

    for user in (source, target):
        WorkspaceMembership.objects.create(workspace=workspace, principal_uuid=user.identity_principal.uuid, role="")
    WorkspaceOwnership.objects.create(workspace=workspace, principal_uuid=source.identity_principal.uuid)
    provider = Provider()

    result = services.policy_transfer_workspace_ownership(actor, provider, workspace.uuid, source.pk, target.pk)

    assert result.uuid == workspace.uuid
    assert WorkspaceMembership.objects.get(workspace=workspace, user=target).role == "admin"
    assert WorkspaceMembership.objects.get(workspace=workspace, user=source).role == "owner"
    assert provider.requests[0].action == "workspace.transfer"
    assert provider.requests[0].target.uuid == workspace.uuid
    assert AuditLog.objects.filter(
        entity_type="workspace", entity_id=workspace.pk, actor_principal_uuid=actor.principal.uuid
    ).exists()

    assert WorkspaceOwnership.objects.get(workspace=workspace).principal_uuid == target.identity_principal.uuid


def test_service_admin_transfer_requires_policy_and_existing_target_membership():
    account = services.create_account(kind="team", name="Customer")
    organization = Organization.objects.get(account_id=account.id, is_default=True)
    workspace = Workspace.objects.create(organization=organization, name="Extra")
    source = get_user_model().objects.create_user(username=f"source-{uuid4()}")
    target = get_user_model().objects.create_user(username=f"target-{uuid4()}")
    WorkspaceMembership.objects.create(workspace=workspace, user=source, role="owner")
    actor = _actor()
    actor = CredentialContext(
        actor.principal,
        actor.kind,
        actor.credential_uuid,
        CredentialCeiling(frozenset({"workspace.transfer"})),
        actor.scopes,
    )

    with pytest.raises(services.AccountScopeError):
        services.policy_transfer_workspace_ownership(
            actor, Provider(allowed=False), workspace.uuid, source.pk, target.pk
        )
    with pytest.raises(services.AccountScopeError):
        services.policy_transfer_workspace_ownership(actor, Provider(), workspace.uuid, source.pk, target.pk)
    assert WorkspaceMembership.objects.get(workspace=workspace, user=source).role == "owner"
