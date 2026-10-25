"""Prepared principal memberships and ownership; membership never grants policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast, overload
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from shared.audit import AuditAction, AuditEntityType, AuditEvent, RequestAudit, audit_log
from shared.authorization import AuthorizationProvider, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef, ResourceScope
from shared.principal_port import resolve_principal, resolve_principal_uuid
from workspaces.models import Organization, OrganizationMembership, Workspace, WorkspaceMembership, WorkspaceOwnership

from ._account import AccountScopeError, hierarchy_target_scope
from ._account_policy_admin import AccountMemberPage, AccountMemberView, _require_action, _valid_account_page
from ._memberships import MembershipAuditContext, WorkspaceMembershipError, raise_member_seats_exhausted
from ._quota import WorkspaceQuotaAuditContext, WorkspaceQuotaRejected, admit_workspace_member_seat

_SCOPE_UNAVAILABLE = "Scope unavailable"
_TRANSFER_ACTION = "workspace.transfer"
_WorkspaceOwnershipBlockReason = Literal["archived", "no_membership"]


@dataclass(frozen=True, slots=True)
class WorkspaceOwnershipCandidate:
    """A preauthorized ownership fact with a precise planning rejection."""

    workspace_uuid: UUID
    blocked_reason: _WorkspaceOwnershipBlockReason | None = None


def _authorize_scope_member(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    target_type: str,
    target_uuid: UUID,
) -> ResourceScope:
    """Resolve the registered scope and require its exact membership action."""
    if target_type not in {"organization", "workspace"}:
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    scope = hierarchy_target_scope(target_type, target_uuid)
    _require_action(
        actor,
        provider,
        f"{target_type}.manage_members",
        TargetRef(cast(Literal["organization", "workspace"], target_type), target_uuid),
        scope,
    )
    return scope


@overload
def _locked_scope(target_type: Literal["organization"], scope: ResourceScope) -> Organization:
    """Lock the exact persisted organization."""
    ...


@overload
def _locked_scope(target_type: Literal["workspace"], scope: ResourceScope) -> Workspace:
    """Lock the exact persisted workspace."""
    ...


@overload
def _locked_scope(target_type: str, scope: ResourceScope) -> Organization | Workspace:
    """Lock one of the two registered membership parents."""
    ...


def _locked_scope(target_type: str, scope: ResourceScope) -> Organization | Workspace:
    """Recheck authorized ancestry/lifecycle under the owning row mutex."""
    if scope.account_uuid is None or scope.organization_uuid is None:
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    row: Organization | Workspace | None
    if target_type == "organization":
        row = (
            Organization.objects.select_for_update(of=("self",))
            .filter(
                uuid=scope.organization_uuid,
                account__uuid=scope.account_uuid,
            )
            .first()
        )
    else:
        if target_type != "workspace" or scope.workspace_uuid is None:
            raise AccountScopeError(_SCOPE_UNAVAILABLE)
        row = (
            Workspace.objects.select_for_update(of=("self",))
            .filter(
                uuid=scope.workspace_uuid,
                organization__uuid=scope.organization_uuid,
                organization__account__uuid=scope.account_uuid,
                archived_at__isnull=True,
            )
            .first()
        )
    if row is None:
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    return row


def _members(parent: Organization | Workspace) -> QuerySet[OrganizationMembership] | QuerySet[WorkspaceMembership]:
    """Use the incumbent membership storage, excluding unmapped legacy rows."""
    if isinstance(parent, Organization):
        return OrganizationMembership.objects.filter(organization=parent, principal_uuid__isnull=False)
    return WorkspaceMembership.objects.filter(workspace=parent, principal_uuid__isnull=False)


def _membership_audit(
    parent: Organization | Workspace,
    actor: CredentialContext,
    action: str,
    principal_uuid: UUID,
    request: RequestAudit | None,
    *,
    context: str = "scope_membership",
    source_uuid: UUID | None = None,
) -> None:
    """Strict evidence shares the SQL mutation's transaction and principal identity."""
    attribution = request or RequestAudit()
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.ORGANIZATION if isinstance(parent, Organization) else AuditEntityType.WORKSPACE,
            entity_id=parent.pk,
            action=action,
            actor_type="principal",
            actor_principal_uuid=actor.principal.uuid,
            previous_state={"principal_uuid": str(source_uuid)} if source_uuid is not None else None,
            new_state={"principal_uuid": str(principal_uuid)},
            context=context,
            source_ip=attribution.source_ip,
            user_agent=attribution.user_agent[:500],
            request_id=attribution.request_id[:64],
        ),
        strict=True,
    )


def admin_list_scope_members(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    target_type: str,
    target_uuid: UUID,
    *,
    offset: int = 0,
    limit: int = 50,
) -> AccountMemberPage:
    """Authorize the exact parent before counting or paging membership facts."""
    _valid_account_page(offset, limit)
    _authorize_scope_member(actor, provider, target_type, target_uuid)
    parent = (
        Organization.objects.get(uuid=target_uuid)
        if target_type == "organization"
        else Workspace.objects.get(uuid=target_uuid)
    )
    rows = _members(parent).order_by("pk")
    return AccountMemberPage(
        rows.count(), tuple(AccountMemberView(cast(UUID, row.principal_uuid)) for row in rows[offset : offset + limit])
    )


def _add_scope_member_locked(
    parent: Organization | Workspace,
    subject: PrincipalRef,
    actor: CredentialContext,
    audit: RequestAudit | None,
) -> None:
    """Insert only a fact, with the incumbent locked seat admission and audit."""
    query = _members(parent)
    if query.filter(principal_uuid=subject.uuid).exists():
        return
    if isinstance(parent, Workspace):
        attribution = audit or RequestAudit()
        admit_workspace_member_seat(
            parent.pk,
            WorkspaceQuotaAuditContext(
                actor_type="principal",
                actor_id=None,
                actor_principal_uuid=actor.principal.uuid,
                source_ip=attribution.source_ip,
                user_agent=attribution.user_agent,
                request_id=attribution.request_id,
            ),
        )
        WorkspaceMembership.objects.create(workspace=parent, principal_uuid=subject.uuid, role="")
    else:
        OrganizationMembership.objects.create(organization=parent, principal_uuid=subject.uuid, role="")
    _membership_audit(parent, actor, AuditAction.CREATE, subject.uuid, audit)


def admin_add_scope_member(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    target_type: str,
    target_uuid: UUID,
    principal: PrincipalRef,
    *,
    audit: RequestAudit | None = None,
) -> None:
    """Add an active human/service principal without synthesizing user or policy."""
    scope = _authorize_scope_member(actor, provider, target_type, target_uuid)
    try:
        subject = resolve_principal(principal)
    except Exception as exc:
        raise AccountScopeError(_SCOPE_UNAVAILABLE) from exc
    try:
        with transaction.atomic():
            _add_scope_member_locked(_locked_scope(target_type, scope), subject, actor, audit)
    except WorkspaceQuotaRejected as rejected:
        attribution = audit or RequestAudit()
        raise_member_seats_exhausted(
            rejected,
            MembershipAuditContext(
                actor_type="principal",
                actor_id=None,
                actor_principal_uuid=actor.principal.uuid,
                source_ip=attribution.source_ip,
                user_agent=attribution.user_agent,
                request_id=attribution.request_id,
            ),
        )


def admin_remove_scope_member(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    target_type: str,
    target_uuid: UUID,
    principal_uuid: UUID,
    *,
    audit: RequestAudit | None = None,
) -> None:
    """Remove exactly one fact, preserving the independent workspace owner."""
    scope = _authorize_scope_member(actor, provider, target_type, target_uuid)
    with transaction.atomic():
        parent = _locked_scope(target_type, scope)
        if isinstance(parent, Workspace) and parent.ownerships.filter(principal_uuid=principal_uuid).exists():
            raise AccountScopeError(_SCOPE_UNAVAILABLE)
        membership = _members(parent).select_for_update().filter(principal_uuid=principal_uuid).first()
        if membership is None:
            raise AccountScopeError(_SCOPE_UNAVAILABLE)
        _membership_audit(parent, actor, AuditAction.DELETE, principal_uuid, audit)
        membership.delete()


def admin_transfer_workspace_principal(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
    source_principal_uuid: UUID | None,
    destination_principal_uuid: UUID,
    *,
    audit: RequestAudit | None = None,
) -> None:
    """Compare source ownership and destination membership under the workspace lock."""
    scope = hierarchy_target_scope("workspace", workspace_uuid)
    _require_action(actor, provider, _TRANSFER_ACTION, TargetRef("workspace", workspace_uuid), scope)
    try:
        destination = resolve_principal_uuid(destination_principal_uuid)
    except Exception as exc:
        raise AccountScopeError(_SCOPE_UNAVAILABLE) from exc
    if source_principal_uuid == destination.uuid:
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    with transaction.atomic():
        parent = _locked_scope("workspace", scope)
        if parent.personal_for_user_id is not None:
            raise AccountScopeError(_SCOPE_UNAVAILABLE)
        source = _workspace_transfer_source(parent, source_principal_uuid)
        if not _members(parent).filter(principal_uuid=destination.uuid).exists():
            raise AccountScopeError(_SCOPE_UNAVAILABLE)
        WorkspaceOwnership.objects.get_or_create(workspace=parent, principal_uuid=destination.uuid)
        if source is not None:
            source.delete()
        _membership_audit(
            parent,
            actor,
            AuditAction.UPDATE,
            destination.uuid,
            audit,
            context="workspace_ownership",
            source_uuid=source_principal_uuid,
        )


def admin_add_workspace_owner(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
    principal_uuid: UUID,
    *,
    audit: RequestAudit | None = None,
) -> None:
    """Add an ownership fact; no policy or legacy role is manufactured."""
    scope = hierarchy_target_scope("workspace", workspace_uuid)
    _require_action(actor, provider, _TRANSFER_ACTION, TargetRef("workspace", workspace_uuid), scope)
    principal = resolve_principal_uuid(principal_uuid)
    with transaction.atomic():
        workspace = _locked_scope("workspace", scope)
        if (
            workspace.personal_for_user_id is not None
            or not _members(workspace).filter(principal_uuid=principal.uuid).exists()
        ):
            raise AccountScopeError(_SCOPE_UNAVAILABLE)
        _, created = WorkspaceOwnership.objects.get_or_create(workspace=workspace, principal_uuid=principal.uuid)
        if created:
            _membership_audit(
                workspace, actor, AuditAction.CREATE, principal.uuid, audit, context="workspace_ownership"
            )


def admin_remove_workspace_owner(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
    principal_uuid: UUID,
    *,
    audit: RequestAudit | None = None,
) -> None:
    """Remove an explicit owner only while at least one other owner remains."""
    scope = hierarchy_target_scope("workspace", workspace_uuid)
    _require_action(actor, provider, _TRANSFER_ACTION, TargetRef("workspace", workspace_uuid), scope)
    with transaction.atomic():
        workspace = _locked_scope("workspace", scope)
        ownership = workspace.ownerships.filter(principal_uuid=principal_uuid).first()
        if workspace.personal_for_user_id is not None or ownership is None or workspace.ownerships.count() <= 1:
            raise AccountScopeError(_SCOPE_UNAVAILABLE)
        _membership_audit(workspace, actor, AuditAction.DELETE, principal_uuid, audit, context="workspace_ownership")
        ownership.delete()


def policy_owned_workspace_candidates(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    source_principal_uuid: UUID,
    destination_principal_uuid: UUID,
) -> tuple[WorkspaceOwnershipCandidate, ...]:
    """Preauthorize a complete bounded offboarding plan before the first effect."""
    from ._authorization_delegation import _MAX_DELEGATION_DESCENDANTS

    _require_action(
        actor, provider, "installation.manage_principals", TargetRef("installation"), ResourceScope("installation")
    )
    rows = tuple(
        Workspace.objects.filter(ownerships__principal_uuid=source_principal_uuid, personal_for_user__isnull=True)
        .select_related("organization")
        .order_by("pk")[: _MAX_DELEGATION_DESCENDANTS + 1]
    )
    if len(rows) > _MAX_DELEGATION_DESCENDANTS:
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    candidates = []
    for row in rows:
        # Archived ownership remains visible to offboarding. Resolve its
        # validated parent as the restore command does; mutation still requires
        # an active workspace under the owning row lock.
        parent = hierarchy_target_scope("organization", row.organization.uuid)
        scope = ResourceScope("account", parent.account_uuid, parent.organization_uuid, row.uuid)
        _require_action(actor, provider, _TRANSFER_ACTION, TargetRef("workspace", row.uuid), scope)
        reason: _WorkspaceOwnershipBlockReason | None = None
        if row.archived_at is not None:
            reason = "archived"
        elif not _members(row).filter(principal_uuid=destination_principal_uuid).exists():
            reason = "no_membership"
        candidates.append(WorkspaceOwnershipCandidate(row.uuid, reason))
    return tuple(candidates)


def scope_has_principal_member(scope: ResourceScope, principal: PrincipalRef, *, lock: bool = False) -> bool:
    """SQL eligibility fact for an independently authorized owning-domain effect."""
    from workspaces.models import Account, AccountMembership

    from ._account import resolve_resource_scope

    resolved = resolve_resource_scope(scope)
    resolve_principal(principal)
    if scope.kind == "installation":
        return True
    if resolved.workspace_id is not None:
        if lock:
            _locked_scope("workspace", scope)
        result = WorkspaceMembership.objects.filter(
            workspace_id=resolved.workspace_id, principal_uuid=principal.uuid
        ).exists()
    elif resolved.organization_id is not None:
        if lock:
            _locked_scope("organization", scope)
        result = OrganizationMembership.objects.filter(
            organization_id=resolved.organization_id, principal_uuid=principal.uuid
        ).exists()
    else:
        if resolved.account_id is None:
            raise AccountScopeError(_SCOPE_UNAVAILABLE)
        query = Account.objects.select_for_update() if lock else Account.objects
        account = query.get(pk=resolved.account_id)
        result = (
            account.individual_principal_uuid == principal.uuid
            if account.kind == Account.Kind.INDIVIDUAL
            else AccountMembership.objects.filter(account=account, principal_uuid=principal.uuid).exists()
        )
    return result


def policy_self_workspace_membership(
    actor: CredentialContext, provider: AuthorizationProvider, workspace_uuid: UUID
) -> AccountMemberView:
    """Read the caller's fact under live scope policy, without a roster grant."""
    scope = hierarchy_target_scope("workspace", workspace_uuid)
    _require_action(actor, provider, "workspace.read", TargetRef("workspace", workspace_uuid), scope)
    if not WorkspaceMembership.objects.filter(
        workspace__uuid=workspace_uuid, principal_uuid=actor.principal.uuid
    ).exists():
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    return AccountMemberView(actor.principal.uuid)


def policy_leave_workspace(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
    *,
    audit: RequestAudit | None = None,
) -> None:
    """The self command never accepts a subject and cannot abandon the last owner."""
    scope = hierarchy_target_scope("workspace", workspace_uuid)
    _require_action(actor, provider, "workspace.leave", TargetRef("workspace", workspace_uuid), scope)
    with transaction.atomic():
        workspace = _locked_scope("workspace", scope)
        owners = WorkspaceOwnership.objects.filter(workspace=workspace)
        if owners.filter(principal_uuid=actor.principal.uuid).exists():
            if owners.count() <= 1:
                raise WorkspaceMembershipError("last_owner", "The last owner cannot leave")
            owners.filter(principal_uuid=actor.principal.uuid).delete()
        removed, _ = WorkspaceMembership.objects.filter(
            workspace=workspace, principal_uuid=actor.principal.uuid
        ).delete()
        if removed:
            _membership_audit(workspace, actor, AuditAction.DELETE, actor.principal.uuid, audit)


def _workspace_transfer_source(workspace: Workspace, source_uuid: UUID | None) -> WorkspaceOwnership | None:
    """Check the original source fact while the workspace mutex is held."""
    source = workspace.ownerships.filter(principal_uuid=source_uuid).first() if source_uuid is not None else None
    if source_uuid is not None and source is None:
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    if source_uuid is None and workspace.ownerships.exists():
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    return source
