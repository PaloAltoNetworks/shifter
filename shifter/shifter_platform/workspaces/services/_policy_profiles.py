"""Prepared profile and quota reads reuse the owning validation/projection seams."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from django.db import transaction

from shared.audit import AuditAction, AuditEntityType, AuditEvent, RequestAudit, audit_log
from shared.authorization import AuthorizationProvider, TargetRef
from shared.credentials import CredentialContext
from workspaces.models import Account

from ._account import AccountScopeError, hierarchy_target_scope
from ._account_policy_admin import AccountAdminView, _require_action
from ._organization import OrganizationAuditContext, OrganizationProfile, _profile_from, _validate_changes, _write_audit
from ._policy_memberships import _locked_scope
from ._quota_admin import WorkspaceQuotaProjection, _workspace_quota_projection

_SCOPE_UNAVAILABLE = "Scope unavailable"


def admin_update_account(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    changes: Mapping[str, str],
    *,
    audit: RequestAudit | None = None,
) -> AccountAdminView:
    """Rename the account; changing kind/identity is a separate data-mapping decision."""
    if (
        set(changes) != {"name"}
        or not isinstance(changes["name"], str)
        or not changes["name"].strip()
        or len(changes["name"]) > 200
    ):
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    scope = hierarchy_target_scope("account", account_uuid)
    _require_action(actor, provider, "account.update", TargetRef("account", account_uuid), scope)
    request = audit or RequestAudit()
    with transaction.atomic():
        account = Account.objects.select_for_update().get(uuid=account_uuid)
        name = changes["name"].strip()
        if account.name != name:
            account.name = name
            account.save(update_fields=["name", "updated_at"])
            audit_log(
                AuditEvent(
                    entity_type=AuditEntityType.ACCOUNT,
                    entity_id=account.pk,
                    action=AuditAction.UPDATE,
                    actor_type="principal",
                    actor_principal_uuid=actor.principal.uuid,
                    new_state={"changed_fields": ["name"]},
                    context="account_profile",
                    source_ip=request.source_ip,
                    user_agent=request.user_agent[:500],
                    request_id=request.request_id[:64],
                ),
                strict=True,
            )
        return AccountAdminView(account.uuid, account.name, account.kind)


def admin_get_organization_profile(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    organization_uuid: UUID,
) -> OrganizationProfile:
    """Return the canonical profile only beneath its exact SQL parent."""
    scope = hierarchy_target_scope("organization", organization_uuid)
    if scope.account_uuid != account_uuid:
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    _require_action(actor, provider, "organization.read", TargetRef("organization", organization_uuid), scope)
    from workspaces.models import Organization

    return _profile_from(Organization.objects.get(uuid=organization_uuid, account__uuid=account_uuid))


def admin_update_organization_profile(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    account_uuid: UUID,
    organization_uuid: UUID,
    changes: Mapping[str, str],
    *,
    audit: RequestAudit | None = None,
) -> OrganizationProfile:
    """Keep the existing PATCH mask, validation, locked writer and strict evidence."""
    scope = hierarchy_target_scope("organization", organization_uuid)
    if scope.account_uuid != account_uuid:
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    _require_action(actor, provider, "organization.update", TargetRef("organization", organization_uuid), scope)
    _validate_changes(changes)
    request = audit or RequestAudit()
    with transaction.atomic():
        organization = _locked_scope("organization", scope)
        fields = [key for key, value in changes.items() if getattr(organization, key) != value]
        if fields:
            for key in fields:
                setattr(organization, key, changes[key])
            organization.save(update_fields=[*fields, "updated_at"])
            _write_audit(
                organization,
                fields,
                superuser_override=False,
                audit=OrganizationAuditContext(
                    actor_type="principal",
                    actor_id=None,
                    actor_principal_uuid=actor.principal.uuid,
                    source_ip=request.source_ip,
                    user_agent=request.user_agent,
                    request_id=request.request_id,
                ),
            )
        return _profile_from(organization)


def admin_workspace_quota_usage(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: UUID,
) -> WorkspaceQuotaProjection:
    """Read exactly one workspace's quota under its registered read action."""
    scope = hierarchy_target_scope("workspace", workspace_uuid)
    _require_action(actor, provider, "workspace.read", TargetRef("workspace", workspace_uuid), scope)
    from workspaces.models import Workspace

    workspace = Workspace.objects.get(uuid=workspace_uuid)
    return _workspace_quota_projection(workspace.pk, workspace.uuid)
