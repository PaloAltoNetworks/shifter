"""Policy-aware account hierarchy commands prepared for the S8 cutover."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from shared.audit import AuditAction, AuditEntityType, AuditEvent, RequestAudit, audit_log
from shared.authorization import AuthorizationProvider, AuthorizationRequest, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef, ResourceScope
from shared.principal_port import resolve_principal
from workspaces.models import Account, AccountMembership

from ._account import (
    AccountScopeError,
    AccountView,
    OrganizationView,
    WorkspaceView,
    add_account_member,
    create_account,
    create_account_organization,
    create_account_workspace,
    hierarchy_target_scope,
)
from ._egress import _set_egress_policy_unchecked
from ._lifecycle import WorkspaceAuditContext, WorkspaceProjection
from ._quota import WorkspaceQuotaAuditContext
from ._quota_admin import WorkspaceResourceUsage, _set_quota_policy_unchecked

_DENIED = "Scope unavailable"
_LIST_BATCH_SIZE = 100
_MANAGE_ACCOUNTS = "installation.manage_accounts"
_READ_ACCOUNT = "account.read"
_MANAGE_MEMBERS = "account.manage_members"


@dataclass(frozen=True, slots=True)
class AccountAdminView:
    """Bounded public account identity for policy-authorized administration."""

    uuid: UUID
    name: str
    kind: str


@dataclass(frozen=True, slots=True)
class AccountAdminPage:
    """A page whose count includes only policy-visible accounts."""

    count: int
    results: tuple[AccountAdminView, ...]


@dataclass(frozen=True, slots=True)
class AccountMemberView:
    """One account membership fact without policy or contact information."""

    principal_uuid: UUID


@dataclass(frozen=True, slots=True)
class AccountMemberPage:
    """A bounded page of explicit account membership facts."""

    count: int
    results: tuple[AccountMemberView, ...]


def _active_actor(actor: CredentialContext) -> None:
    """Require a currently active non-participant principal."""
    try:
        if actor.kind == "temporary":
            raise AccountScopeError(_DENIED)
        resolve_principal(actor.principal)
    except Exception as exc:
        raise AccountScopeError(_DENIED) from exc


def _require_action(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    action: str,
    target: TargetRef,
    scope: ResourceScope,
) -> None:
    """Resolve durable identity and policy for each direct service invocation."""
    try:
        _active_actor(actor)
        request = AuthorizationRequest(actor.principal, action, target, scope, actor.ceiling)
        if not provider.check(request).allowed:
            raise AccountScopeError(_DENIED)
    except Exception as exc:
        raise AccountScopeError(_DENIED) from exc


def admin_create_account(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    *,
    kind: str,
    name: str,
    owner: PrincipalRef | None = None,
    audit: RequestAudit | None = None,
) -> AccountView:
    """Create an account after installation authority and owner identity checks."""
    _require_action(
        actor,
        provider,
        _MANAGE_ACCOUNTS,
        TargetRef("installation"),
        ResourceScope("installation"),
    )
    if owner is not None:
        try:
            resolve_principal(owner)
        except Exception as exc:
            raise AccountScopeError(_DENIED) from exc
    return create_account(kind=kind, name=name, owner=owner, audit_actor=actor.principal, request_audit=audit)


def admin_create_organization(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    *,
    name: str,
    audit: RequestAudit | None = None,
) -> OrganizationView:
    """Create a real subdivision after exact account authority and ancestry checks."""
    try:
        scope = hierarchy_target_scope("account", account_uuid)
    except AccountScopeError as exc:
        raise AccountScopeError(_DENIED) from exc
    _require_action(actor, provider, "account.manage_organizations", TargetRef("account", account_uuid), scope)
    return create_account_organization(account_uuid, name, audit_actor=actor.principal, request_audit=audit)


def admin_create_workspace(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    organization_uuid: UUID,
    *,
    name: str,
    audit: RequestAudit | None = None,
) -> WorkspaceView:
    """Create a workspace only beneath the authorized parent organization."""
    try:
        scope = hierarchy_target_scope("organization", organization_uuid)
        if scope.account_uuid != account_uuid:
            raise AccountScopeError(_DENIED)
    except AccountScopeError as exc:
        raise AccountScopeError(_DENIED) from exc
    _require_action(
        actor,
        provider,
        "organization.manage_workspaces",
        TargetRef("organization", organization_uuid),
        scope,
    )
    return create_account_workspace(
        account_uuid, organization_uuid, name, audit_actor=actor.principal, request_audit=audit
    )


def admin_individual_account(actor: CredentialContext, provider: AuthorizationProvider) -> AccountAdminView:
    """Resolve a human's individual account without an organization selector."""
    _active_actor(actor)
    if actor.principal.kind != "human":
        raise AccountScopeError(_DENIED)
    account = Account.objects.filter(
        kind=Account.Kind.INDIVIDUAL, individual_principal_uuid=actor.principal.uuid
    ).first()
    if account is None:
        raise AccountScopeError(_DENIED)
    _require_action(
        actor,
        provider,
        _READ_ACCOUNT,
        TargetRef("account", account.uuid),
        hierarchy_target_scope("account", account.uuid),
    )
    return AccountAdminView(account.uuid, account.name, account.kind)


def admin_add_account_member(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    principal: PrincipalRef,
    *,
    audit: RequestAudit | None = None,
) -> None:
    """Add an active principal as a fact, without issuing an authority grant."""
    try:
        scope = hierarchy_target_scope("account", account_uuid)
    except AccountScopeError as exc:
        raise AccountScopeError(_DENIED) from exc
    _require_action(actor, provider, _MANAGE_MEMBERS, TargetRef("account", account_uuid), scope)
    try:
        resolve_principal(principal)
    except Exception as exc:
        raise AccountScopeError(_DENIED) from exc
    add_account_member(account_uuid, principal, audit_actor=actor.principal, request_audit=audit)


def admin_list_account_members(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    *,
    offset: int = 0,
    limit: int = 50,
) -> AccountMemberPage:
    """Page facts only after authority over the exact account is established."""
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
    ):
        raise AccountScopeError(_DENIED)
    scope = hierarchy_target_scope("account", account_uuid)
    _require_action(actor, provider, _MANAGE_MEMBERS, TargetRef("account", account_uuid), scope)
    queryset = AccountMembership.objects.filter(account__uuid=account_uuid).order_by("pk")
    count = queryset.count()
    rows = queryset[offset : offset + limit]
    return AccountMemberPage(count, tuple(AccountMemberView(row.principal_uuid) for row in rows))


def admin_remove_account_member(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    principal_uuid: UUID,
    *,
    audit: RequestAudit | None = None,
) -> None:
    """Remove only the selected account's membership fact with strict evidence."""
    scope = hierarchy_target_scope("account", account_uuid)
    _require_action(actor, provider, _MANAGE_MEMBERS, TargetRef("account", account_uuid), scope)
    request_audit = audit or RequestAudit()
    with transaction.atomic():
        account = Account.objects.select_for_update().filter(uuid=account_uuid).first()
        if account is None:
            raise AccountScopeError(_DENIED)
        membership = (
            AccountMembership.objects.select_for_update().filter(account=account, principal_uuid=principal_uuid).first()
        )
        if membership is None:
            raise AccountScopeError(_DENIED)
        membership_id = membership.pk
        membership.delete()
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.ACCOUNT_MEMBERSHIP,
                entity_id=membership_id,
                action=AuditAction.DELETE,
                previous_state={"account_id": account.pk},
                context="account_hierarchy",
                actor_type="principal",
                actor_principal_uuid=actor.principal.uuid,
                source_ip=request_audit.source_ip,
                user_agent=request_audit.user_agent[:500],
                request_id=request_audit.request_id[:64],
            ),
            strict=True,
        )


def admin_set_workspace_quota_policy(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
    resource: str,
    limit: int,
    mode: str,
    *,
    audit: RequestAudit | None = None,
) -> WorkspaceResourceUsage:
    """Authorize quota authoring for a human or service application admin."""
    try:
        scope = hierarchy_target_scope("workspace", workspace_uuid)
    except AccountScopeError as exc:
        raise AccountScopeError(_DENIED) from exc
    _require_action(actor, provider, "workspace.manage_quota", TargetRef("workspace", workspace_uuid), scope)
    request_audit = audit or RequestAudit()
    return _set_quota_policy_unchecked(
        workspace_uuid,
        resource,
        limit,
        mode,
        audit=WorkspaceQuotaAuditContext(
            actor_type="principal",
            actor_id=None,
            actor_principal_uuid=actor.principal.uuid,
            source_ip=request_audit.source_ip,
            user_agent=request_audit.user_agent,
            request_id=request_audit.request_id,
        ),
        actor_id=None,
    )


def admin_set_workspace_egress_policy(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
    egress_policy: str,
    *,
    audit: RequestAudit | None = None,
) -> WorkspaceProjection:
    """Set a workspace egress selector after exact live policy and SQL scope checks."""
    try:
        scope = hierarchy_target_scope("workspace", workspace_uuid)
    except AccountScopeError as exc:
        raise AccountScopeError(_DENIED) from exc
    _require_action(actor, provider, "workspace.manage_egress", TargetRef("workspace", workspace_uuid), scope)
    request_audit = audit or RequestAudit()
    return _set_egress_policy_unchecked(
        workspace_uuid,
        egress_policy,
        audit=WorkspaceAuditContext(
            actor_type="principal",
            actor_id=None,
            actor_principal_uuid=actor.principal.uuid,
            source_ip=request_audit.source_ip,
            user_agent=request_audit.user_agent,
            request_id=request_audit.request_id,
        ),
    )


def _read_batch(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    accounts: tuple[Account, ...],
) -> tuple[bool, ...]:
    """Check every SQL-owned target without trusting partial provider results."""
    try:
        requests = tuple(
            AuthorizationRequest(
                actor.principal,
                _READ_ACCOUNT,
                TargetRef("account", account.uuid),
                hierarchy_target_scope("account", account.uuid),
                actor.ceiling,
            )
            for account in accounts
        )
        decisions = provider.batch_check(requests)
        if len(decisions) != len(requests) or any(decision.kind == "evaluator_error" for decision in decisions):
            raise AccountScopeError(_DENIED)
        return tuple(decision.allowed for decision in decisions)
    except Exception as exc:
        raise AccountScopeError(_DENIED) from exc


def _valid_account_page(offset: int, limit: int) -> None:
    """Bound count and page work before reading customer records."""
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
    ):
        raise AccountScopeError(_DENIED)


def _installation_list_access(actor: CredentialContext, provider: AuthorizationProvider) -> bool:
    """Use a global account list only with live installation authority."""
    if not actor.ceiling.permits(_MANAGE_ACCOUNTS, TargetRef("installation")):
        return False
    try:
        request = AuthorizationRequest(
            actor.principal,
            _MANAGE_ACCOUNTS,
            TargetRef("installation"),
            ResourceScope("installation"),
            actor.ceiling,
        )
        decision = provider.check(request)
        if decision.kind == "evaluator_error":
            raise AccountScopeError(_DENIED)
        return decision.allowed
    except Exception as exc:
        raise AccountScopeError(_DENIED) from exc


def _account_batches(exact_uuid: UUID | None, search: str = "") -> Iterator[tuple[Account, ...]]:
    """Read bounded SQL batches while retaining a stable count cursor."""
    cursor = 0
    while True:
        query = Account.objects.filter(pk__gt=cursor)
        if search:
            query = query.filter(name__icontains=search)
        if exact_uuid is not None:
            query = query.filter(uuid=exact_uuid)
        batch = tuple(query.order_by("pk")[:_LIST_BATCH_SIZE])
        if not batch:
            return
        cursor = batch[-1].pk
        yield batch


def _page_account_rows(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    *,
    global_access: bool,
    exact_uuid: UUID | None,
    offset: int,
    limit: int,
    search: str = "",
) -> AccountAdminPage:
    """Count and slice only accounts allowed by the live batch decisions."""
    count = 0
    results: list[AccountAdminView] = []
    for batch in _account_batches(exact_uuid, search):
        visible = (True,) * len(batch) if global_access else _read_batch(actor, provider, batch)
        for account, allowed in zip(batch, visible, strict=True):
            if not allowed:
                continue
            if offset <= count < offset + limit:
                results.append(AccountAdminView(account.uuid, account.name, account.kind))
            count += 1
    return AccountAdminPage(count, tuple(results))


def admin_list_accounts(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    *,
    offset: int = 0,
    limit: int = 50,
    search: str = "",
) -> AccountAdminPage:
    """Filter account authority before counting or slicing a collection."""
    _active_actor(actor)
    _valid_account_page(offset, limit)
    if not isinstance(search, str) or len(search) > 200:
        raise AccountScopeError(_DENIED)
    global_access = _installation_list_access(actor, provider)
    if not global_access and _READ_ACCOUNT not in actor.ceiling.actions:
        return AccountAdminPage(0, ())
    exact_target = actor.ceiling.target if not global_access else None
    if exact_target is not None and (exact_target.type != "account" or exact_target.uuid is None):
        return AccountAdminPage(0, ())
    exact_uuid = exact_target.uuid if exact_target is not None else None
    return _page_account_rows(
        actor, provider, global_access=global_access, exact_uuid=exact_uuid, offset=offset, limit=limit, search=search
    )
