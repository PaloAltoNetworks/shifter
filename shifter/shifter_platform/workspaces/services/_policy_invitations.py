"""Dormant policy invitation commands using the incumbent signing/delivery contract."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from shared.audit import AuditAction, RequestAudit
from shared.authorization import AuthorizationProvider, AuthorizationRequest, CredentialCeiling, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from shared.principal_port import principal_for_user, resolve_principal_uuid, resolve_verified_principal
from shared.verified_identity import VerifiedIdentity
from workspaces.models import WorkspaceInvitation, WorkspaceMembership

from ._account import AccountScopeError, hierarchy_target_scope
from ._account_policy_admin import _require_action, _valid_account_page
from ._invitations import (
    WORKSPACE_INVITATION_TOKEN_MAX_AGE_SECONDS,
    WorkspaceInvitationClaim,
    WorkspaceInvitationError,
    WorkspaceInvitationProjection,
    _audit_state,
    _consume_delivery_budget,
    _eligible_verified_principal,
    _normalized_email,
    _projection,
    _require_workspace_eligible,
    _schedule_delivery,
    _write_audit,
)
from ._memberships import MembershipAuditContext, raise_member_seats_exhausted
from ._policy_memberships import _add_scope_member_locked, _locked_scope
from ._quota import WorkspaceQuotaRejected

if TYPE_CHECKING:
    from django.contrib.auth.models import User

_ACTION = "workspace.manage_invitations"


def _unavailable() -> WorkspaceInvitationError:
    """Do not disclose the state or ancestry of an inaccessible invitation."""
    return WorkspaceInvitationError("invitation_invalid", "Invitation is invalid")


def _authorize(actor: CredentialContext, provider: AuthorizationProvider, workspace_uuid: uuid.UUID) -> ResourceScope:
    """Check exact SQL ancestry and live policy before opening the write transaction."""
    try:
        scope = hierarchy_target_scope("workspace", workspace_uuid)
        _require_action(actor, provider, _ACTION, TargetRef("workspace", workspace_uuid), scope)
        return scope
    except AccountScopeError as exc:
        raise _unavailable() from exc


def _attribution(actor: CredentialContext, audit: RequestAudit | None) -> MembershipAuditContext:
    """Bind invitation evidence to the authenticated principal and request."""
    request = audit or RequestAudit()
    return MembershipAuditContext(
        actor_type="principal",
        actor_id=None,
        actor_principal_uuid=actor.principal.uuid,
        source_ip=request.source_ip,
        user_agent=request.user_agent,
        request_id=request.request_id,
    )


def admin_list_workspace_invitations(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: uuid.UUID,
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[int, tuple[WorkspaceInvitationProjection, ...]]:
    """Count/page only invitations of the policy-authorized exact workspace."""
    _valid_account_page(offset, limit)
    _authorize(actor, provider, workspace_uuid)
    rows = (
        WorkspaceInvitation.objects.select_related("workspace")
        .filter(
            workspace__uuid=workspace_uuid,
            created_by_principal_uuid__isnull=False,
        )
        .order_by("-created_at", "-pk")
    )
    return rows.count(), tuple(_projection(row) for row in rows[offset : offset + limit])


def admin_issue_workspace_invitation(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: uuid.UUID,
    email: str,
    *,
    audit: RequestAudit | None = None,
) -> WorkspaceInvitationProjection:
    """A service can invite a verified human without impersonating its contact."""
    scope = _authorize(actor, provider, workspace_uuid)
    email = _normalized_email(email)
    _consume_delivery_budget(actor.principal.uuid)
    with transaction.atomic():
        workspace = _locked_scope("workspace", scope)
        _require_workspace_eligible(workspace)
        if WorkspaceInvitation.objects.filter(
            workspace=workspace,
            email__iexact=email,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
        ).exists():
            raise WorkspaceInvitationError("invitation_exists", "A current invitation already exists")
        invitation = WorkspaceInvitation.objects.create(
            workspace=workspace,
            email=email,
            role="",
            created_by_principal_uuid=actor.principal.uuid,
            expires_at=timezone.now() + timedelta(seconds=WORKSPACE_INVITATION_TOKEN_MAX_AGE_SECONDS),
        )
        _write_audit(invitation, AuditAction.CREATE, _attribution(actor, audit), new_state=_audit_state(invitation))
        _schedule_delivery(invitation)
        return _projection(invitation)


def _manage(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: uuid.UUID,
    invitation_uuid: uuid.UUID,
    *,
    revoke: bool,
    audit: RequestAudit | None,
) -> WorkspaceInvitationProjection:
    """Use the same generation/status/signing invariants for resend and revoke."""
    scope = _authorize(actor, provider, workspace_uuid)
    if not revoke:
        _consume_delivery_budget(actor.principal.uuid)
    with transaction.atomic():
        workspace = _locked_scope("workspace", scope)
        _require_workspace_eligible(workspace)
        invitation = (
            WorkspaceInvitation.objects.select_for_update()
            .filter(
                workspace=workspace,
                public_id=invitation_uuid,
                role="",
                created_by_principal_uuid__isnull=False,
                accepted_at__isnull=True,
                revoked_at__isnull=True,
            )
            .first()
        )
        if invitation is None:
            raise _unavailable()
        previous = _audit_state(invitation)
        invitation.generation = uuid.uuid4()
        if revoke:
            invitation.revoked_at = timezone.now()
            changed = "revoked_at"
        else:
            invitation.expires_at = timezone.now() + timedelta(seconds=WORKSPACE_INVITATION_TOKEN_MAX_AGE_SECONDS)
            changed = "expires_at"
        invitation.save(update_fields=["generation", changed, "updated_at"])
        _write_audit(
            invitation,
            AuditAction.CANCEL if revoke else AuditAction.UPDATE,
            _attribution(actor, audit),
            previous_state=previous,
            new_state=_audit_state(invitation),
        )
        if not revoke:
            _schedule_delivery(invitation)
        return _projection(invitation)


def admin_resend_workspace_invitation(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: uuid.UUID,
    invitation_uuid: uuid.UUID,
    *,
    audit: RequestAudit | None = None,
) -> WorkspaceInvitationProjection:
    """Rotate the generation; a token from any earlier delivery stops working."""
    return _manage(actor, provider, workspace_uuid, invitation_uuid, revoke=False, audit=audit)


def admin_revoke_workspace_invitation(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    workspace_uuid: uuid.UUID,
    invitation_uuid: uuid.UUID,
    *,
    audit: RequestAudit | None = None,
) -> WorkspaceInvitationProjection:
    """Revoke only the invitation in the exact authorized workspace."""
    return _manage(actor, provider, workspace_uuid, invitation_uuid, revoke=True, audit=audit)


def policy_accept_workspace_invitation(
    user: User,
    identity: VerifiedIdentity,
    claim: WorkspaceInvitationClaim,
    provider: AuthorizationProvider,
    *,
    audit: RequestAudit | None = None,
) -> uuid.UUID:
    """Consume a fact-only invitation in the fresh provider-login handoff at S8."""
    hint = (
        WorkspaceInvitation.objects.select_related("workspace")
        .filter(
            public_id=claim.invitation_uuid,
            role="",
            created_by_principal_uuid__isnull=False,
        )
        .first()
    )
    if hint is None:
        raise _unavailable()
    if hint.created_by_principal_uuid is None:
        raise _unavailable()
    try:
        recipient = resolve_verified_principal(identity)
        if recipient != principal_for_user(user):
            raise _unavailable()
        _eligible_verified_principal(user, identity, hint.email)
        issuer = resolve_principal_uuid(hint.created_by_principal_uuid)
        scope = hierarchy_target_scope("workspace", hint.workspace.uuid)
        target = TargetRef("workspace", hint.workspace.uuid)
        # The stored invitation records an already-authorized, exact membership
        # effect. Recheck the issuer's current policy; this grants no policy.
        if not provider.check(
            AuthorizationRequest(
                issuer,
                _ACTION,
                target,
                scope,
                CredentialCeiling(frozenset({_ACTION}), target),
            )
        ).allowed:
            raise _unavailable()
    except Exception as exc:
        raise _unavailable() from exc
    actor = CredentialContext(recipient, "session", recipient.uuid, CredentialCeiling(frozenset()), frozenset())
    try:
        with transaction.atomic():
            workspace = _locked_scope("workspace", scope)
            _require_workspace_eligible(workspace)
            invitation = (
                WorkspaceInvitation.objects.select_for_update()
                .filter(
                    public_id=claim.invitation_uuid,
                    workspace=workspace,
                    generation=claim.generation,
                    accepted_at__isnull=True,
                    revoked_at__isnull=True,
                    expires_at__gt=timezone.now(),
                    created_by_principal_uuid=issuer.uuid,
                    email=hint.email,
                    role="",
                )
                .first()
            )
            if invitation is None:
                raise _unavailable()
            if WorkspaceMembership.objects.filter(workspace=workspace, principal_uuid=recipient.uuid).exists():
                raise WorkspaceInvitationError("membership_exists", "Workspace membership already exists")
            _add_scope_member_locked(workspace, recipient, actor, audit)
            previous = _audit_state(invitation)
            invitation.accepted_at = timezone.now()
            invitation.accepted_by_principal_uuid = recipient.uuid
            invitation.save(update_fields=["accepted_at", "accepted_by_principal_uuid", "updated_at"])
            _write_audit(
                invitation,
                AuditAction.CLOSE,
                _attribution(actor, audit),
                previous_state=previous,
                new_state=_audit_state(invitation),
            )
            return workspace.uuid
    except WorkspaceQuotaRejected as rejected:
        raise_member_seats_exhausted(rejected, _attribution(actor, audit))
