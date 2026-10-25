"""Scoped authorization metadata administration (#2315)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction

from shared.audit import AuditAction, AuditEntityType, AuditEvent, RequestAudit, audit_log
from shared.authorization import (
    PREDEFINED_POLICIES,
    AuthorizationProvider,
    AuthorizationRequest,
    CredentialCeiling,
    TargetRef,
)
from shared.identity_scope import PrincipalRef, ResourceScope
from shared.principal_port import resolve_principal
from workspaces.models import AuthorizationGroup, AuthorizationOperation, AuthorizationPolicy, Workspace

from ._account import resolve_resource_scope


class AuthorizationAdminError(RuntimeError):
    """Opaque authorization administration failure."""


class AuthorizationAdminValidationError(AuthorizationAdminError):
    """Closed metadata input is malformed."""


class AuthorizationAdminConflict(AuthorizationAdminError):
    """Scoped metadata conflicts with an existing identity."""


@dataclass(frozen=True, slots=True)
class AuthorizationMetadataView:
    """Display-only scoped group or policy metadata, never effective grants."""

    uuid: UUID
    name: str
    description: str
    predefined_code: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class AuthorizationOperationView:
    """Sanitized durable mutation status returned to authorized administrators."""

    uuid: UUID
    relationship_kind: str
    action: str
    effect: str
    state: str
    outcome_reason: str


def workspace_authorization_scope(workspace_uuid: UUID) -> ResourceScope:
    """Resolve an unarchived workspace's complete account ancestry from SQL."""
    workspace = (
        Workspace.objects.select_related("organization__account")
        .filter(uuid=workspace_uuid, archived_at__isnull=True, organization__account__isnull=False)
        .first()
    )
    if workspace is None or workspace.organization.account is None:
        raise AuthorizationAdminError("authorization scope unavailable")
    return ResourceScope(
        kind="account",
        account_uuid=workspace.organization.account.uuid,
        organization_uuid=workspace.organization.uuid,
        workspace_uuid=workspace.uuid,
    )


def _authorize(
    actor: PrincipalRef,
    credential: CredentialCeiling,
    scope: ResourceScope,
    provider: AuthorizationProvider,
) -> None:
    """Require current management authority at the exact metadata scope."""
    try:
        resolve_principal(actor)
        resolve_resource_scope(scope)
        if scope.workspace_uuid is not None:
            target = TargetRef("workspace", scope.workspace_uuid)
        elif scope.organization_uuid is not None:
            target = TargetRef("organization", scope.organization_uuid)
        elif scope.account_uuid is not None:
            target = TargetRef("account", scope.account_uuid)
        else:
            target = TargetRef("installation")
        request = AuthorizationRequest(
            actor,
            f"{target.type}.manage_authorization",
            target,
            scope,
            credential,
        )
        decision = provider.check(request)
    except Exception as exc:
        raise AuthorizationAdminError("authorization denied") from exc
    if not decision.allowed:
        raise AuthorizationAdminError("authorization denied")


def _lookup(scope: ResourceScope) -> dict[str, object]:
    """Match metadata against all components of the trusted scope."""
    return {
        "scope_kind": scope.kind,
        "account_uuid": scope.account_uuid,
        "organization_uuid": scope.organization_uuid,
        "workspace_uuid": scope.workspace_uuid,
    }


def _metadata_view(item: AuthorizationGroup | AuthorizationPolicy) -> AuthorizationMetadataView:
    """Project a persisted display identity into its public service contract."""
    return AuthorizationMetadataView(
        uuid=item.uuid,
        name=item.name,
        description=item.description,
        predefined_code=getattr(item, "predefined_code", ""),
        is_active=item.is_active,
    )


def _ensure_predefined_metadata(scope: ResourceScope) -> None:
    """Provision immutable display identities for the current concrete scope."""
    if scope.workspace_uuid is not None:
        target_type = "workspace"
    elif scope.organization_uuid is not None:
        target_type = "organization"
    elif scope.account_uuid is not None:
        target_type = "account"
    else:
        target_type = "installation"
    lookup = _lookup(scope)
    definitions = (item for item in PREDEFINED_POLICIES if item.target_type == target_type)
    try:
        with transaction.atomic():
            for definition in definitions:
                AuthorizationPolicy.objects.get_or_create(
                    **lookup,
                    predefined_code=definition.code,
                    defaults={"name": definition.name, "description": "Built-in Shifter authorization policy."},
                )
                AuthorizationGroup.objects.get_or_create(
                    **lookup,
                    predefined_code=definition.code,
                    defaults={
                        "name": definition.assignment_group_name,
                        "description": "Built-in assignment group for the matching policy.",
                    },
                )
    except IntegrityError as exc:
        raise AuthorizationAdminConflict("predefined authorization metadata conflicts with custom metadata") from exc


def _audit_metadata(item: AuthorizationGroup | AuthorizationPolicy, audit: RequestAudit) -> None:
    """Record metadata creation with trusted request attribution in the same transaction."""
    entity_type = (
        AuditEntityType.AUTHORIZATION_GROUP
        if isinstance(item, AuthorizationGroup)
        else AuditEntityType.AUTHORIZATION_POLICY
    )
    audit_log(
        AuditEvent(
            entity_type=entity_type,
            entity_id=item.pk,
            entity_ref=str(item.uuid),
            action=AuditAction.CREATE,
            actor_type=audit.actor_type or "system",
            actor_id=audit.actor_id,
            actor_principal_uuid=audit.actor_principal_uuid,
            new_state={"name": item.name, "scope_kind": item.scope_kind},
            context="authorization_admin",
            source_ip=audit.source_ip,
            user_agent=audit.user_agent,
            request_id=audit.request_id,
        ),
        strict=True,
    )


def _validated_metadata(name: str, description: str) -> tuple[str, str]:
    """Normalize bounded display fields and reject empty or oversized names."""
    normalized_name = name.strip() if isinstance(name, str) else ""
    normalized_description = description.strip() if isinstance(description, str) else ""
    if not normalized_name or len(normalized_name) > 120 or len(normalized_description) > 500:
        raise AuthorizationAdminValidationError("authorization metadata is invalid")
    return normalized_name, normalized_description


def list_authorization_groups(
    actor: PrincipalRef,
    credential: CredentialCeiling,
    scope: ResourceScope,
    provider: AuthorizationProvider,
) -> tuple[AuthorizationMetadataView, ...]:
    """List scoped group metadata only after current administration checks."""
    _authorize(actor, credential, scope, provider)
    _ensure_predefined_metadata(scope)
    return tuple(
        _metadata_view(item) for item in AuthorizationGroup.objects.filter(**_lookup(scope)).order_by("name", "uuid")
    )


def create_authorization_group(
    actor: PrincipalRef,
    credential: CredentialCeiling,
    scope: ResourceScope,
    provider: AuthorizationProvider,
    *,
    name: str,
    description: str = "",
    audit: RequestAudit,
) -> AuthorizationMetadataView:
    """Create and audit scoped group metadata without granting membership."""
    name, description = _validated_metadata(name, description)
    _authorize(actor, credential, scope, provider)
    _ensure_predefined_metadata(scope)
    try:
        with transaction.atomic():
            item = AuthorizationGroup.objects.create(
                **_lookup(scope),
                name=name,
                description=description,
            )
            _audit_metadata(item, audit)
    except IntegrityError as exc:
        raise AuthorizationAdminConflict("authorization metadata already exists") from exc
    return _metadata_view(item)


def list_authorization_policies(
    actor: PrincipalRef,
    credential: CredentialCeiling,
    scope: ResourceScope,
    provider: AuthorizationProvider,
) -> tuple[AuthorizationMetadataView, ...]:
    """List scoped policy metadata only after current administration checks."""
    _authorize(actor, credential, scope, provider)
    _ensure_predefined_metadata(scope)
    return tuple(
        _metadata_view(item) for item in AuthorizationPolicy.objects.filter(**_lookup(scope)).order_by("name", "uuid")
    )


def create_authorization_policy(
    actor: PrincipalRef,
    credential: CredentialCeiling,
    scope: ResourceScope,
    provider: AuthorizationProvider,
    *,
    name: str,
    description: str = "",
    audit: RequestAudit,
) -> AuthorizationMetadataView:
    """Create and audit a custom policy identity without granting permissions."""
    name, description = _validated_metadata(name, description)
    _authorize(actor, credential, scope, provider)
    _ensure_predefined_metadata(scope)
    try:
        with transaction.atomic():
            item = AuthorizationPolicy.objects.create(
                **_lookup(scope),
                name=name,
                description=description,
            )
            _audit_metadata(item, audit)
    except IntegrityError as exc:
        raise AuthorizationAdminConflict("authorization metadata already exists") from exc
    return _metadata_view(item)


def get_authorization_operation(
    actor: PrincipalRef,
    credential: CredentialCeiling,
    scope: ResourceScope,
    provider: AuthorizationProvider,
    operation_uuid: UUID,
) -> AuthorizationOperationView:
    """Read operation status only within the caller's authorized exact scope."""
    _authorize(actor, credential, scope, provider)
    operation = AuthorizationOperation.objects.filter(
        id=operation_uuid,
        scope_kind=scope.kind,
        account_uuid=scope.account_uuid,
        organization_uuid=scope.organization_uuid,
        workspace_uuid=scope.workspace_uuid,
    ).first()
    if operation is None:
        raise AuthorizationAdminError("authorization operation unavailable")
    return AuthorizationOperationView(
        uuid=operation.id,
        relationship_kind=operation.relationship_kind,
        action=operation.action,
        effect=operation.effect,
        state=operation.state,
        outcome_reason=operation.outcome_reason,
    )


def reconcile_authorization_operation(
    actor: PrincipalRef,
    credential: CredentialCeiling,
    scope: ResourceScope,
    provider: AuthorizationProvider,
    operation_uuid: UUID,
) -> AuthorizationOperationView:
    """Explicitly reconcile a scoped pending operation after reauthorization."""
    operation = get_authorization_operation(actor, credential, scope, provider, operation_uuid)
    if operation.state in {AuthorizationOperation.State.REQUESTED, AuthorizationOperation.State.UNRESOLVED}:
        from ._authorization_policy import authorize_operation_reconciliation, reconcile_policy_mutation

        try:
            authorize_operation_reconciliation(operation.uuid, actor, credential, provider)
        except Exception as exc:
            raise AuthorizationAdminError("authorization recovery denied") from exc
        reconcile_policy_mutation(operation.uuid, provider)
    return get_authorization_operation(actor, credential, scope, provider, operation_uuid)
