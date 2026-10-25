"""Scoped authorization delegation responsibilities (ADR-066, #2315)."""

from __future__ import annotations

from uuid import UUID

from django.db.models import Model, QuerySet

from shared.authorization import (
    ACTION_CATALOG,
    AdministrativeRoleChange,
    AuthorizationRequest,
    GroupMembershipChange,
    PolicyEffect,
    RelationshipSubject,
    TargetRef,
    action_definition,
    predefined_policy_definition,
    resolve_authorization_descendants,
    resolve_authorization_event_scope,
    resolve_authorization_nonworkspace_events,
)
from shared.identity_scope import PrincipalRef, ResourceScope
from shared.principal_port import resolve_principal
from shared.principal_port import resolve_principal_uuid as directory_resolve_principal_uuid
from workspaces.models import (
    Account,
    AuthorizationGroup,
    AuthorizationPolicy,
    Organization,
    Workspace,
)

from ._account import hierarchy_target_scope, resolve_resource_scope
from ._authorization_commands import (
    AuthorizationMutationConflict,
    NativeRelationshipMutationRequest,
    PolicyMutationRequest,
)

_MAX_DELEGATION_DESCENDANTS = 1_000
_SUBJECT_UNAVAILABLE = "authorization subject is unavailable"
_TARGET_UNAVAILABLE = "authorization target is unavailable"


def _management_action(target_type: str) -> str:
    """Select the management permission required for the concrete target type."""
    return {
        "installation": "installation.manage_authorization",
        "account": "account.manage_authorization",
        "organization": "organization.manage_authorization",
        "workspace": "workspace.manage_authorization",
        "event": "event.manage",
        "range": "range.manage",
    }[target_type]


def _delegation_requests(request: PolicyMutationRequest) -> tuple[AuthorizationRequest, AuthorizationRequest]:
    """Require both the delegated permission and authority to edit the target."""
    if not action_definition(request.action).delegable:
        raise AuthorizationMutationConflict("authorization action cannot be delegated")
    return (
        AuthorizationRequest(request.actor, request.action, request.target, request.scope, request.credential),
        AuthorizationRequest(
            request.actor,
            _management_action(request.target.type),
            request.target,
            request.scope,
            request.credential,
        ),
    )


def _scope_target(scope: ResourceScope) -> TargetRef:
    """Choose the most specific target in the trusted SQL ancestry."""
    candidates = (
        TargetRef("workspace", scope.workspace_uuid) if scope.workspace_uuid else None,
        TargetRef("organization", scope.organization_uuid) if scope.organization_uuid else None,
        TargetRef("account", scope.account_uuid) if scope.account_uuid else None,
    )
    for target in candidates:
        if target is not None:
            return target
    return TargetRef("installation")


def _bounded_rows[T: Model](query: QuerySet[T], remaining: int) -> tuple[T, ...]:
    """Read one extra ordered row to reject incomplete descendant inventories."""
    rows = tuple(query.order_by("uuid")[: remaining + 1])
    if len(rows) > remaining:
        raise AuthorizationMutationConflict("authorization descendant limit exceeded")
    return rows


def _descendant_queries(
    target: TargetRef,
) -> tuple[QuerySet[Account], QuerySet[Organization], QuerySet[Workspace]]:
    """Select only descendants of the concrete target."""
    account_query = Account.objects.none()
    organization_query = Organization.objects.none()
    workspace_query = Workspace.objects.none()
    if target.type == "installation":
        account_query = Account.objects.all()
        organization_query = Organization.objects.filter(account__isnull=False)
        workspace_query = Workspace.objects.filter(organization__account__isnull=False)
    elif target.uuid is None:
        raise AuthorizationMutationConflict(_TARGET_UNAVAILABLE)
    elif target.type == "account":
        organization_query = Organization.objects.filter(account__uuid=target.uuid)
        workspace_query = Workspace.objects.filter(organization__account__uuid=target.uuid)
    elif target.type == "organization":
        workspace_query = Workspace.objects.filter(organization__uuid=target.uuid)
    elif target.type == "workspace":
        workspace_query = Workspace.objects.filter(uuid=target.uuid)
    return account_query, organization_query, workspace_query


def _workspace_descendants(
    target_type: str, workspaces: tuple[Workspace, ...], remaining: int
) -> tuple[tuple[TargetRef, ResourceScope], ...]:
    """Include workspace targets before their bounded event/range leaves."""
    descendants: list[tuple[TargetRef, ResourceScope]] = []
    for workspace in workspaces:
        scope = ResourceScope(
            "account", _organization_account_uuid(workspace.organization), workspace.organization.uuid, workspace.uuid
        )
        if target_type != "workspace":
            descendants.append((TargetRef("workspace", workspace.uuid), scope))
    remaining -= len(descendants)
    for workspace in workspaces:
        scope = ResourceScope(
            "account", _organization_account_uuid(workspace.organization), workspace.organization.uuid, workspace.uuid
        )
        external = resolve_authorization_descendants((workspace.pk,), remaining)
        descendants.extend((item, scope) for item in external)
        remaining -= len(external)
    return tuple(descendants)


def _nonworkspace_event_descendants(target: TargetRef, remaining: int) -> tuple[tuple[TargetRef, ResourceScope], ...]:
    """Include account and organization events outside workspaces."""
    if target.type not in {"installation", "account", "organization"}:
        return ()
    if target.type == "installation":
        parent_scope = ResourceScope("installation")
    else:
        if target.uuid is None:
            raise AuthorizationMutationConflict(_TARGET_UNAVAILABLE)
        parent_scope = hierarchy_target_scope(target.type, target.uuid)
    return resolve_authorization_nonworkspace_events(parent_scope, remaining)


def _authoritative_descendant_targets(target: TargetRef) -> tuple[tuple[TargetRef, ResourceScope], ...]:
    """Resolve a bounded complete descendant set from SQL-owning domains."""
    if target.type in {"event", "range"}:
        return ()

    account_query, organization_query, workspace_query = _descendant_queries(target)

    remaining = _MAX_DELEGATION_DESCENDANTS
    descendants: list[tuple[TargetRef, ResourceScope]] = []
    if target.type == "installation":
        accounts = _bounded_rows(account_query, remaining)
        descendants.extend((TargetRef("account", item.uuid), ResourceScope("account", item.uuid)) for item in accounts)
        remaining -= len(accounts)
    if target.type in {"installation", "account"}:
        organizations = _bounded_rows(organization_query.select_related("account"), remaining)
        descendants.extend(
            (
                TargetRef("organization", item.uuid),
                ResourceScope("account", _organization_account_uuid(item), item.uuid),
            )
            for item in organizations
        )
        remaining -= len(organizations)
    workspaces = _bounded_rows(workspace_query.select_related("organization__account"), remaining)
    descendants.extend(_workspace_descendants(target.type, workspaces, remaining))
    remaining = _MAX_DELEGATION_DESCENDANTS - len(descendants)
    descendants.extend(_nonworkspace_event_descendants(target, remaining))
    return tuple(descendants)


def _organization_account_uuid(organization: Organization) -> UUID:
    """Reject incomplete ancestry rather than manufacturing an authorization scope."""
    account = organization.account
    if account is None:
        raise AuthorizationMutationConflict("authorization account ancestry is unavailable")
    return account.uuid


def _native_delegation_requests(request: NativeRelationshipMutationRequest) -> tuple[AuthorizationRequest, ...]:
    """Require complete administrative authority at the native object's exact scope.

    Native membership can amplify every role currently or subsequently assigned
    to the group. Requiring the full delegable set at and below that scope is
    intentionally stronger than a single manage-members check and prevents a
    partial administrator from using membership as a privilege-escalation path.
    """
    if isinstance(request.change, AdministrativeRoleChange):
        definition = predefined_policy_definition(request.change.policy_code)
        target = request.change.target
        actions = definition.actions
    elif isinstance(request.change, GroupMembershipChange):
        target = _scope_target(request.scope)
        hierarchy = ("installation", "account", "organization", "workspace", "event", "range")
        root_index = hierarchy.index(target.type)
        actions = frozenset(
            item.code
            for item in ACTION_CATALOG
            if hierarchy.index(item.target_type) >= root_index and (item.delegable or item.requires_administrator)
        )
    else:
        target = _scope_target(request.scope)
        actions = frozenset(item.code for item in ACTION_CATALOG if item.target_type == target.type)
    if not actions.issubset(request.credential.actions):
        return ()

    action_definitions = tuple(action_definition(action) for action in sorted(actions))
    needs_descendants = any(item.target_type != target.type for item in action_definitions)
    concrete_targets: tuple[tuple[TargetRef, ResourceScope], ...] = ((target, request.scope),)
    if needs_descendants:
        concrete_targets += _authoritative_descendant_targets(target)
    return tuple(
        AuthorizationRequest(request.actor, definition.code, concrete_target, concrete_scope, request.credential)
        for definition in action_definitions
        for concrete_target, concrete_scope in concrete_targets
        if concrete_target.type == definition.target_type
    )


def _scope_lookup(scope: ResourceScope) -> dict[str, object]:
    """Match active metadata against every SQL-owned ancestry component."""
    return {
        "scope_kind": scope.kind,
        "account_uuid": scope.account_uuid,
        "organization_uuid": scope.organization_uuid,
        "workspace_uuid": scope.workspace_uuid,
        "is_active": True,
    }


def _resolve_principal_uuid(principal_uuid: UUID) -> None:
    """Require an active durable identity from the owning principal directory."""
    directory_resolve_principal_uuid(principal_uuid)


def _resolve_concrete_target(target: TargetRef, scope: ResourceScope) -> None:
    """Verify leaf ownership in SQL before trusting a provider decision."""
    if target.type not in {"event", "range"}:
        return
    if target.uuid is None:
        raise AuthorizationMutationConflict(_TARGET_UNAVAILABLE)
    if target.type == "event":
        if resolve_authorization_event_scope(target.uuid) != scope:
            raise AuthorizationMutationConflict(_TARGET_UNAVAILABLE)
        return
    resolved = resolve_resource_scope(scope)
    if resolved.workspace_id is None or target not in resolve_authorization_descendants(
        (resolved.workspace_id,), _MAX_DELEGATION_DESCENDANTS
    ):
        raise AuthorizationMutationConflict(_TARGET_UNAVAILABLE)


def _resolve_native_change(request: NativeRelationshipMutationRequest) -> None:
    """Re-resolve durable identities and exact SQL-owned metadata ancestry."""
    resolve_principal(request.actor)
    change = request.change
    if isinstance(change, GroupMembershipChange):
        _resolve_assignment_subject(
            RelationshipSubject("principal", change.principal_uuid),
            change.effect,
            request.actor,
            request.scope,
        )
        if not AuthorizationGroup.objects.filter(uuid=change.group_uuid, **_scope_lookup(request.scope)).exists():
            raise AuthorizationMutationConflict("authorization group is unavailable")
    else:
        _resolve_assignment_subject(change.subject, change.effect, request.actor, request.scope)
        if isinstance(change, AdministrativeRoleChange):
            predefined_policy_definition(change.policy_code)
            _resolve_concrete_target(change.target, request.scope)
        elif not AuthorizationPolicy.objects.filter(
            uuid=change.role_uuid,
            predefined_code="",
            **_scope_lookup(request.scope),
        ).exists():
            raise AuthorizationMutationConflict("authorization policy is unavailable")


def _resolve_assignment_subject(
    subject: RelationshipSubject,
    effect: PolicyEffect,
    actor: PrincipalRef,
    scope: ResourceScope,
) -> None:
    """Validate active, exactly scoped subjects and reject self-grants."""
    if subject.kind == "principal":
        _resolve_principal_uuid(subject.uuid)
        if effect == PolicyEffect.GRANT and subject.uuid == actor.uuid:
            raise AuthorizationMutationConflict("self-assignment is not permitted")
    elif subject.kind == "group":
        if not AuthorizationGroup.objects.filter(uuid=subject.uuid, **_scope_lookup(scope)).exists():
            raise AuthorizationMutationConflict(_SUBJECT_UNAVAILABLE)
    elif not AuthorizationPolicy.objects.filter(
        uuid=subject.uuid,
        predefined_code="",
        **_scope_lookup(scope),
    ).exists():
        raise AuthorizationMutationConflict(_SUBJECT_UNAVAILABLE)


def _resolve_policy_change(request: PolicyMutationRequest) -> None:
    """Validate actor, target ownership, and the assignment subject in SQL."""
    resolve_principal(request.actor)
    _resolve_concrete_target(request.target, request.scope)
    _resolve_assignment_subject(request.subject, request.effect, request.actor, request.scope)
