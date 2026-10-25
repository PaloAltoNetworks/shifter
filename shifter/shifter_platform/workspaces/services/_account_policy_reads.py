"""Policy-filtered account subdivision reads prepared for the S8 cutover."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from django.db.models import Model, QuerySet

from shared.authorization import AuthorizationProvider, AuthorizationRequest, TargetRef
from shared.credentials import CredentialContext
from workspaces.models import Account, Organization, Workspace

from ._account import AccountScopeError, hierarchy_target_scope
from ._account_policy_admin import AccountAdminView, _active_actor, _require_action
from ._account_policy_lifecycle import _scope_for_lifecycle

_DENIED = "Scope unavailable"
_BATCH_SIZE = 100
_READ_ORGANIZATION = "organization.read"
_READ_WORKSPACE = "workspace.read"


@dataclass(frozen=True, slots=True)
class OrganizationAdminView:
    """One organization visible to the current principal."""

    uuid: UUID
    name: str
    is_default: bool


@dataclass(frozen=True, slots=True)
class OrganizationAdminPage:
    """A count and page computed after policy filtering."""

    count: int
    results: tuple[OrganizationAdminView, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceAdminView:
    """One live workspace visible to the current principal."""

    uuid: UUID
    name: str
    is_default: bool
    archived_at: datetime | None = None
    egress_policy: str = "status-quo"
    owner_principal_uuids: tuple[UUID, ...] = ()


def _workspace_view(row: Workspace) -> WorkspaceAdminView:
    """One canonical prepared workspace response including lifecycle/owner facts."""
    return WorkspaceAdminView(
        row.uuid,
        row.name,
        row.is_default,
        row.archived_at,
        row.egress_policy,
        tuple(item.principal_uuid for item in row.ownerships.all()),
    )


@dataclass(frozen=True, slots=True)
class WorkspaceAdminPage:
    """A count and page computed after policy filtering."""

    count: int
    results: tuple[WorkspaceAdminView, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceAdminFilters:
    """Closed workspace discovery filters, applied before authorization paging."""

    include_archived: bool = False
    search: str = ""


_DEFAULT_WORKSPACE_FILTERS = WorkspaceAdminFilters()


def _workspace_filters(filters: WorkspaceAdminFilters) -> tuple[bool, str]:
    """Validate query intent independently of the authorized SQL selection."""
    if not isinstance(filters, WorkspaceAdminFilters) or not isinstance(filters.include_archived, bool):
        raise AccountScopeError(_DENIED)
    if not isinstance(filters.search, str) or len(filters.search) > 200:
        raise AccountScopeError(_DENIED)
    return filters.include_archived, filters.search.strip()


def admin_get_account(
    actor: CredentialContext, provider: AuthorizationProvider, account_uuid: UUID
) -> AccountAdminView:
    """Read one exact account after current policy and SQL identity checks."""
    scope = hierarchy_target_scope("account", account_uuid)
    _require_action(actor, provider, "account.read", TargetRef("account", account_uuid), scope)
    account = Account.objects.filter(uuid=account_uuid).first()
    if account is None:
        raise AccountScopeError(_DENIED)
    return AccountAdminView(account.uuid, account.name, account.kind)


def admin_get_organization(
    actor: CredentialContext, provider: AuthorizationProvider, account_uuid: UUID, organization_uuid: UUID
) -> OrganizationAdminView:
    """Read one organization only beneath its persisted account parent."""
    scope = hierarchy_target_scope("organization", organization_uuid)
    if scope.account_uuid != account_uuid:
        raise AccountScopeError(_DENIED)
    _require_action(actor, provider, _READ_ORGANIZATION, TargetRef("organization", organization_uuid), scope)
    organization = Organization.objects.filter(uuid=organization_uuid).first()
    if organization is None:
        raise AccountScopeError(_DENIED)
    return OrganizationAdminView(organization.uuid, organization.name, organization.is_default)


def admin_get_workspace(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    organization_uuid: UUID,
    workspace_uuid: UUID,
    *,
    include_archived: bool = False,
) -> WorkspaceAdminView:
    """Read one live workspace only beneath both persisted parents."""
    scope = _scope_for_lifecycle(workspace_uuid, restore=include_archived)
    if scope.account_uuid != account_uuid or scope.organization_uuid != organization_uuid:
        raise AccountScopeError(_DENIED)
    _require_action(actor, provider, _READ_WORKSPACE, TargetRef("workspace", workspace_uuid), scope)
    query = Workspace.objects.filter(uuid=workspace_uuid)
    if not include_archived:
        query = query.filter(archived_at__isnull=True)
    workspace = query.first()
    if workspace is None:
        raise AccountScopeError(_DENIED)
    return _workspace_view(workspace)


def _valid_page(offset: int, limit: int) -> None:
    """Reject unbounded or malformed collection windows."""
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
    ):
        raise AccountScopeError(_DENIED)


def _allowed_batch(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    action: str,
    target_type: Literal["organization", "workspace"],
    uuids: tuple[UUID, ...],
) -> tuple[bool, ...]:
    """Require complete policy results for SQL-owned targets before exposing them."""
    try:
        requests = tuple(
            AuthorizationRequest(
                actor.principal,
                action,
                TargetRef(target_type, uuid),
                _scope_for_lifecycle(uuid, restore=True)
                if target_type == "workspace"
                else hierarchy_target_scope(target_type, uuid),
                actor.ceiling,
            )
            for uuid in uuids
        )
        decisions = provider.batch_check(requests)
        if len(decisions) != len(requests) or any(decision.kind == "evaluator_error" for decision in decisions):
            raise AccountScopeError(_DENIED)
        return tuple(decision.allowed for decision in decisions)
    except Exception as exc:
        raise AccountScopeError(_DENIED) from exc


def _collection_ceiling(
    actor: CredentialContext, action: str, target_type: Literal["organization", "workspace"]
) -> tuple[bool, UUID | None]:
    """Identify the exact credential target without widening an invalid proof."""
    if action not in actor.ceiling.actions:
        return False, None
    target = actor.ceiling.target
    if target is None:
        return True, None
    permitted = target.type == target_type and target.uuid is not None
    return permitted, target.uuid if permitted else None


def _visible_page[T: Model](
    queryset: QuerySet[T],
    actor: CredentialContext,
    provider: AuthorizationProvider,
    action: str,
    target_type: Literal["organization", "workspace"],
    uuid_of: Callable[[T], UUID],
    *,
    window: tuple[int, int],
) -> tuple[int, tuple[T, ...]]:
    """Batch-check every candidate before computing a visible count or page."""
    offset, limit = window
    count = cursor = 0
    results: list[T] = []
    while True:
        batch = tuple(queryset.filter(pk__gt=cursor).order_by("pk")[:_BATCH_SIZE])
        if not batch:
            break
        cursor = batch[-1].pk
        allowed = _allowed_batch(actor, provider, action, target_type, tuple(uuid_of(row) for row in batch))
        for row, visible in zip(batch, allowed, strict=True):
            if not visible:
                continue
            if offset <= count < offset + limit:
                results.append(row)
            count += 1
    return count, tuple(results)


def admin_list_organizations(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    *,
    offset: int = 0,
    limit: int = 50,
) -> OrganizationAdminPage:
    """Page only organizations readable beneath the exact persisted account."""
    _active_actor(actor)
    _valid_page(offset, limit)
    hierarchy_target_scope("account", account_uuid)
    account = Account.objects.filter(uuid=account_uuid).first()
    if account is None or account.kind == Account.Kind.INDIVIDUAL:
        raise AccountScopeError(_DENIED)
    permitted, exact_uuid = _collection_ceiling(actor, _READ_ORGANIZATION, "organization")
    if not permitted:
        return OrganizationAdminPage(0, ())
    query = Organization.objects.filter(account=account)
    if exact_uuid is not None:
        query = query.filter(uuid=exact_uuid)
    count, rows = _visible_page(
        query, actor, provider, _READ_ORGANIZATION, "organization", lambda row: row.uuid, window=(offset, limit)
    )
    return OrganizationAdminPage(
        count, tuple(OrganizationAdminView(row.uuid, row.name, row.is_default) for row in rows)
    )


def admin_list_workspaces(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    organization_uuid: UUID,
    *,
    offset: int = 0,
    limit: int = 50,
    filters: WorkspaceAdminFilters = _DEFAULT_WORKSPACE_FILTERS,
) -> WorkspaceAdminPage:
    """Page authorized workspaces beneath the exact parent organization."""
    _active_actor(actor)
    _valid_page(offset, limit)
    include_archived, search = _workspace_filters(filters)
    scope = hierarchy_target_scope("organization", organization_uuid)
    if scope.account_uuid != account_uuid:
        raise AccountScopeError(_DENIED)
    organization = Organization.objects.filter(uuid=organization_uuid).first()
    if organization is None:
        raise AccountScopeError(_DENIED)
    permitted, exact_uuid = _collection_ceiling(actor, _READ_WORKSPACE, "workspace")
    if not permitted:
        return WorkspaceAdminPage(0, ())
    query = Workspace.objects.filter(organization=organization, name__icontains=search).prefetch_related("ownerships")
    if not include_archived:
        query = query.filter(archived_at__isnull=True)
    if exact_uuid is not None:
        query = query.filter(uuid=exact_uuid)
    count, rows = _visible_page(
        query, actor, provider, _READ_WORKSPACE, "workspace", lambda row: row.uuid, window=(offset, limit)
    )
    return WorkspaceAdminPage(count, tuple(_workspace_view(row) for row in rows))
