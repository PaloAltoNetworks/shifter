"""S8 policy-aware workspace lifecycle commands using the incumbent locked writer."""

from __future__ import annotations

from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction

from shared.audit import RequestAudit
from shared.authorization import AuthorizationProvider, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from shared.principal_port import PrincipalResolutionError, principal_identity_for_user
from workspaces.models import Workspace

from ._account import AccountScopeError, hierarchy_target_scope
from ._account_policy_admin import _require_action
from ._lifecycle import (
    WorkspaceAuditContext,
    WorkspaceProjection,
    _archive_workspace_locked,
    _error,
    _projection,
    _rename_workspace_locked,
    _restore_workspace_locked,
    _validate_name,
)
from ._policy_memberships import admin_transfer_workspace_principal

_DENIED = "Scope unavailable"


def _scope_for_lifecycle(workspace_uuid: UUID, *, restore: bool) -> ResourceScope:
    """Resolve archived state only for the operation that can restore it."""
    if not restore:
        return hierarchy_target_scope("workspace", workspace_uuid)
    workspace = Workspace.objects.select_related("organization__account").filter(uuid=workspace_uuid).first()
    if workspace is None or workspace.organization.account is None:
        raise AccountScopeError(_DENIED)
    parent = hierarchy_target_scope("organization", workspace.organization.uuid)
    return ResourceScope("account", parent.account_uuid, parent.organization_uuid, workspace.uuid)


def _audit(actor: CredentialContext, request: RequestAudit | None) -> WorkspaceAuditContext:
    """Carry canonical principal and request attribution into the locked writer."""
    attribution = request or RequestAudit()
    return WorkspaceAuditContext(
        actor_type="principal",
        actor_id=None,
        actor_principal_uuid=actor.principal.uuid,
        source_ip=attribution.source_ip,
        user_agent=attribution.user_agent,
        request_id=attribution.request_id,
    )


def _locked_workspace(workspace_uuid: UUID, scope: ResourceScope) -> Workspace:
    """Recheck the resolved target's persisted ancestry while holding its row lock."""
    if scope.organization_uuid is None:
        raise AccountScopeError(_DENIED)
    workspace = (
        Workspace.objects.select_related("organization")
        .select_for_update()
        .filter(uuid=workspace_uuid, organization__uuid=scope.organization_uuid)
        .first()
    )
    if workspace is None:
        raise AccountScopeError(_DENIED)
    return workspace


def admin_rename_workspace(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
    name: str,
    *,
    audit: RequestAudit | None = None,
) -> WorkspaceProjection:
    """Rename one active workspace after exact policy and locked state checks."""
    cleaned = _validate_name(name)
    scope = _scope_for_lifecycle(workspace_uuid, restore=False)
    _require_action(actor, provider, "workspace.update", TargetRef("workspace", workspace_uuid), scope)
    with transaction.atomic():
        workspace = _locked_workspace(workspace_uuid, scope)
        if workspace.archived_at is not None:
            raise AccountScopeError(_DENIED)
        return _rename_workspace_locked(workspace, cleaned, _audit(actor, audit), None)


def admin_archive_workspace(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
    *,
    audit: RequestAudit | None = None,
) -> WorkspaceProjection:
    """Archive one active non-default workspace after exact policy checks."""
    scope = _scope_for_lifecycle(workspace_uuid, restore=False)
    _require_action(actor, provider, "workspace.archive", TargetRef("workspace", workspace_uuid), scope)
    with transaction.atomic():
        workspace = _locked_workspace(workspace_uuid, scope)
        if workspace.archived_at is not None:
            raise AccountScopeError(_DENIED)
        return _archive_workspace_locked(workspace, _audit(actor, audit), None)


def admin_restore_workspace(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
    *,
    audit: RequestAudit | None = None,
) -> WorkspaceProjection:
    """Restore one archived workspace under its exact persisted ancestry."""
    scope = _scope_for_lifecycle(workspace_uuid, restore=True)
    _require_action(actor, provider, "workspace.restore", TargetRef("workspace", workspace_uuid), scope)
    with transaction.atomic():
        workspace = _locked_workspace(workspace_uuid, scope)
        return _restore_workspace_locked(workspace, _audit(actor, audit), None)


def policy_transfer_workspace_ownership(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
    source_user_id: int,
    new_owner_user_id: int,
    *,
    audit: RequestAudit | None = None,
) -> WorkspaceProjection:
    """Transfer one existing owner to an existing member under exact policy."""
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in (source_user_id, new_owner_user_id)
    ):
        raise _error("owner_invalid", "A valid owner is required")
    if source_user_id == new_owner_user_id:
        raise _error("same_user", "The replacement account must differ from the departing account")
    scope = _scope_for_lifecycle(workspace_uuid, restore=False)
    _require_action(actor, provider, "workspace.transfer", TargetRef("workspace", workspace_uuid), scope)
    users = get_user_model().objects.in_bulk((source_user_id, new_owner_user_id))
    if len(users) != 2:
        raise AccountScopeError(_DENIED)
    try:
        source = principal_identity_for_user(users[source_user_id])
        destination = principal_identity_for_user(users[new_owner_user_id])
    except PrincipalResolutionError as exc:
        raise AccountScopeError(_DENIED) from exc
    admin_transfer_workspace_principal(actor, provider, workspace_uuid, source.uuid, destination.uuid, audit=audit)
    return _projection(Workspace.objects.select_related("organization").get(uuid=workspace_uuid))
