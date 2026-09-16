"""Signed workspace member invitation lifecycle (#1942, PLAT-235)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from shared.auth import is_temporary_ctf_account
from shared.credential_delivery import credential_delivery_allowed
from shared.email import render_template, send_email_async
from shared.site_url import SiteUrlUnavailable, validated_site_url
from shared.verified_identity import VerifiedIdentity
from workspaces.models import Workspace, WorkspaceInvitation, WorkspaceMembership
from workspaces.roles import WorkspaceOperation, WorkspaceRole

from ._memberships import (
    MembershipAuditContext,
    WorkspaceMembershipError,
    WorkspaceMembershipProjection,
    _insert_workspace_membership,
    _lock_workspace_and_actor,
    _require_owner_authority,
    _role_value,
    raise_member_seats_exhausted,
)
from ._quota import WorkspaceQuotaRejected

if TYPE_CHECKING:
    from django.contrib.auth.models import User

UserModel = get_user_model()

WORKSPACE_INVITATION_SIGNING_SALT = "shifter.workspaces.invitation.v1"
WORKSPACE_INVITATION_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
WORKSPACE_INVITATION_TOKEN_MAX_LENGTH = 4096
_TOKEN_VERSION = 1
_INVALID_INVITATION_MESSAGE = "Invitation is invalid"


class WorkspaceInvitationError(Exception):
    """A safe, classified invitation command outcome."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class WorkspaceInvitationClaim:
    """Non-secret staged reference retained after raw-token verification."""

    invitation_uuid: uuid.UUID
    generation: uuid.UUID


@dataclass(frozen=True, slots=True)
class WorkspaceInvitationProjection:
    """Immutable invitation data returned across the domain boundary."""

    invitation_uuid: uuid.UUID
    workspace_uuid: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


def _error(code: str, message: str) -> WorkspaceInvitationError:
    """Build a bounded invitation-domain error."""
    return WorkspaceInvitationError(code, message)


def _normalized_email(value: object) -> str:
    """Normalize and validate one invitation email address."""
    email = str(value).strip().casefold()
    if not email or len(email) > 254:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE)
    try:
        validate_email(email)
    except ValidationError as exc:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE) from exc
    return email


def _status(invitation: WorkspaceInvitation, *, now: datetime | None = None) -> str:
    """Derive the public status without mutating the invitation."""
    status = "pending"
    if invitation.accepted_at is not None:
        status = "accepted"
    elif invitation.revoked_at is not None:
        status = "revoked"
    elif invitation.expires_at <= (now or timezone.now()):
        status = "expired"
    return status


def _projection(invitation: WorkspaceInvitation, *, now: datetime | None = None) -> WorkspaceInvitationProjection:
    """Project a persistent invitation into its public domain contract."""
    return WorkspaceInvitationProjection(
        invitation_uuid=invitation.public_id,
        workspace_uuid=invitation.workspace.uuid,
        email=invitation.email,
        role=invitation.role,
        status=_status(invitation, now=now),
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        updated_at=invitation.updated_at,
    )


def _audit_state(invitation: WorkspaceInvitation) -> dict[str, int | str]:
    """Return the PII-free state stored in invitation audit events."""
    return {
        "workspace_id": invitation.workspace_id,
        "role": invitation.role,
        "generation": str(invitation.generation),
        "status": _status(invitation),
    }


def _write_audit(
    invitation: WorkspaceInvitation,
    action: AuditAction,
    audit: MembershipAuditContext,
    *,
    previous_state: dict[str, int | str] | None = None,
    new_state: dict[str, int | str] | None = None,
) -> None:
    """Write a strict invitation audit event."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.WORKSPACE_INVITATION,
            entity_id=invitation.pk,
            action=action,
            actor_type=audit.actor_type,
            actor_id=audit.actor_id,
            previous_state=previous_state,
            new_state=new_state,
            context="workspace_invitation",
            source_ip=audit.source_ip,
            user_agent=audit.user_agent[:500],
            request_id=audit.request_id[:64],
        ),
        strict=True,
    )


def _token(invitation: WorkspaceInvitation) -> str:
    """Create a timestamped signed token for the current generation."""
    return signing.dumps(
        {
            "v": _TOKEN_VERSION,
            "invitation": str(invitation.public_id),
            "generation": str(invitation.generation),
        },
        salt=WORKSPACE_INVITATION_SIGNING_SALT,
        compress=False,
    )


def _site_url() -> str:
    """Return the validated public origin used in invitation delivery."""
    try:
        return validated_site_url()
    except SiteUrlUnavailable as exc:
        raise _error("invitation_delivery_unavailable", "Invitation delivery is unavailable") from exc


def _render_delivery(invitation: WorkspaceInvitation) -> tuple[str, str, str]:
    """Render the subject and multipart bodies for one invitation."""
    token = quote(_token(invitation), safe="")
    accept_url = f"{_site_url()}{reverse('workspace_invitation_accept')}#token={token}"
    context = {
        "accept_url": accept_url,
        "workspace_name": invitation.workspace.name,
        "organization_name": invitation.workspace.organization.name,
        "role_label": WorkspaceRole(invitation.role).label,
        "expires_at": invitation.expires_at,
    }
    html, text = render_template("workspaces/email/member_invitation", context)
    return _("Invitation to %(workspace)s") % {"workspace": invitation.workspace.name}, html, text


def _schedule_delivery(invitation: WorkspaceInvitation) -> None:
    """Schedule delivery only after the surrounding transaction commits."""
    subject, html, text = _render_delivery(invitation)
    transaction.on_commit(partial(send_email_async, invitation.email, subject, html, text))


def _consume_delivery_budget(actor_id: int) -> None:
    """Consume the shared credential-delivery rate-limit budget."""
    try:
        allowed = credential_delivery_allowed(actor_id, limit=20, window=3600)
    except Exception as exc:
        raise _error("invitation_delivery_unavailable", "Invitation delivery is unavailable") from exc
    if not allowed:
        raise _error("invitation_throttled", "Too many invitation requests. Try again later")


def _require_workspace_eligible(workspace: Workspace) -> None:
    """Reject invitation mutations for protected workspace states."""
    if workspace.personal_for_user_id is not None:
        raise WorkspaceMembershipError("personal_workspace_protected", "Personal workspaces cannot have collaborators")
    if workspace.archived_at is not None:
        raise _error("workspace_archived", "Archived workspaces cannot manage invitations")


def _require_owner_for_owner_invitation(actor_membership: WorkspaceMembership, role: str) -> None:
    """Require owner authority whenever the invitation grants ownership."""
    if role == WorkspaceRole.OWNER.value:
        _require_owner_authority(actor_membership)


def list_workspace_invitations(actor: User, workspace_uuid: str | uuid.UUID) -> list[WorkspaceInvitationProjection]:
    """Return an authorized invitation list with one derived status policy."""
    from ._authorization import authorize_workspace

    authorization = authorize_workspace(actor, workspace_uuid, WorkspaceOperation.READ_INVITATIONS)
    now = timezone.now()
    invitations = WorkspaceInvitation.objects.select_related("workspace").filter(
        workspace_id=authorization.workspace_id
    )
    return [_projection(invitation, now=now) for invitation in invitations]


def issue_workspace_invitation(
    actor: User,
    workspace_uuid: str | uuid.UUID,
    target_email: object,
    role: object,
    *,
    audit: MembershipAuditContext,
) -> WorkspaceInvitationProjection:
    """Issue one current signed invitation after staff/API admission and live role authorization."""
    role_value = _role_value(role)
    email = _normalized_email(target_email)
    with transaction.atomic():
        workspace, actor_membership = _lock_workspace_and_actor(
            actor,
            workspace_uuid,
            WorkspaceOperation.ISSUE_INVITATION,
        )
        _require_workspace_eligible(workspace)
        _require_owner_for_owner_invitation(actor_membership, role_value)
        _consume_delivery_budget(actor.pk)
        if WorkspaceMembership.objects.filter(workspace=workspace, user__email__iexact=email).exists():
            raise WorkspaceMembershipError("membership_exists", "The account already has a workspace membership")
        if (
            WorkspaceInvitation.objects.select_for_update()
            .filter(
                workspace=workspace,
                email__iexact=email,
                accepted_at__isnull=True,
                revoked_at__isnull=True,
            )
            .exists()
        ):
            raise _error("invitation_exists", "A current invitation already exists for this address")
        invitation = WorkspaceInvitation.objects.create(
            workspace=workspace,
            email=email,
            role=role_value,
            expires_at=timezone.now() + timedelta(seconds=WORKSPACE_INVITATION_TOKEN_MAX_AGE_SECONDS),
            created_by=actor,
        )
        invitation = WorkspaceInvitation.objects.select_related("workspace__organization").get(pk=invitation.pk)
        _write_audit(invitation, AuditAction.CREATE, audit, new_state=_audit_state(invitation))
        _schedule_delivery(invitation)
        return _projection(invitation)


def _locked_managed_invitation(
    actor: User,
    workspace_uuid: str | uuid.UUID,
    invitation_uuid: str | uuid.UUID,
    operation: WorkspaceOperation,
) -> tuple[Workspace, WorkspaceMembership, WorkspaceInvitation]:
    """Lock and authorize one invitation-management target."""
    workspace, actor_membership = _lock_workspace_and_actor(actor, workspace_uuid, operation)
    _require_workspace_eligible(workspace)
    invitation = (
        WorkspaceInvitation.objects.select_for_update()
        .select_related("workspace__organization")
        .filter(workspace=workspace, public_id=invitation_uuid)
        .first()
    )
    if invitation is None:
        raise _error("invitation_not_found", "Workspace invitation not found")
    _require_owner_for_owner_invitation(actor_membership, invitation.role)
    return workspace, actor_membership, invitation


def resend_workspace_invitation(
    actor: User,
    workspace_uuid: str | uuid.UUID,
    invitation_uuid: str | uuid.UUID,
    *,
    audit: MembershipAuditContext,
) -> WorkspaceInvitationProjection:
    """Rotate and redeliver a current invitation, invalidating every earlier token."""
    with transaction.atomic():
        _workspace, _membership, invitation = _locked_managed_invitation(
            actor,
            workspace_uuid,
            invitation_uuid,
            WorkspaceOperation.RESEND_INVITATION,
        )
        if invitation.accepted_at is not None or invitation.revoked_at is not None:
            raise _error("invitation_not_current", "Workspace invitation is not current")
        _consume_delivery_budget(actor.pk)
        previous = _audit_state(invitation)
        invitation.generation = uuid.uuid4()
        invitation.expires_at = timezone.now() + timedelta(seconds=WORKSPACE_INVITATION_TOKEN_MAX_AGE_SECONDS)
        invitation.save(update_fields=["generation", "expires_at", "updated_at"])
        _write_audit(invitation, AuditAction.UPDATE, audit, previous_state=previous, new_state=_audit_state(invitation))
        _schedule_delivery(invitation)
        return _projection(invitation)


def revoke_workspace_invitation(
    actor: User,
    workspace_uuid: str | uuid.UUID,
    invitation_uuid: str | uuid.UUID,
    *,
    audit: MembershipAuditContext,
) -> WorkspaceInvitationProjection:
    """Revoke a current invitation and invalidate its signed generation."""
    with transaction.atomic():
        _workspace, _membership, invitation = _locked_managed_invitation(
            actor,
            workspace_uuid,
            invitation_uuid,
            WorkspaceOperation.REVOKE_INVITATION,
        )
        if invitation.accepted_at is not None or invitation.revoked_at is not None:
            raise _error("invitation_not_current", "Workspace invitation is not current")
        previous = _audit_state(invitation)
        invitation.generation = uuid.uuid4()
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["generation", "revoked_at", "updated_at"])
        _write_audit(invitation, AuditAction.CANCEL, audit, previous_state=previous, new_state=_audit_state(invitation))
        return _projection(invitation)


def _payload_claim(payload: object) -> WorkspaceInvitationClaim:
    """Parse the exact signed-token payload into a staged claim."""
    if not isinstance(payload, dict) or set(payload) != {"v", "invitation", "generation"}:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE)
    if payload.get("v") != _TOKEN_VERSION:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE)
    try:
        return WorkspaceInvitationClaim(
            invitation_uuid=uuid.UUID(payload["invitation"]),
            generation=uuid.UUID(payload["generation"]),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE) from exc


def stage_workspace_invitation_token(raw_token: object) -> WorkspaceInvitationClaim:
    """Verify and reduce a raw bearer token to a non-secret invitation reference."""
    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > WORKSPACE_INVITATION_TOKEN_MAX_LENGTH:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE)
    try:
        payload = signing.loads(
            raw_token,
            salt=WORKSPACE_INVITATION_SIGNING_SALT,
            max_age=WORKSPACE_INVITATION_TOKEN_MAX_AGE_SECONDS,
        )
    except signing.BadSignature as exc:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE) from exc
    claim = _payload_claim(payload)
    invitation = WorkspaceInvitation.objects.filter(
        public_id=claim.invitation_uuid,
        generation=claim.generation,
        accepted_at__isnull=True,
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).first()
    if invitation is None:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE)
    return claim


def _eligible_verified_principal(user: User, identity: VerifiedIdentity, invited_email: str) -> None:
    """Require one unambiguous active account matching fresh provider evidence."""
    if not user.is_active or is_temporary_ctf_account(user):
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE)
    verified_email = _normalized_email(identity.email)
    if identity.email_verified is not True or verified_email != invited_email:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE)
    matches = list(UserModel.objects.filter(is_active=True, email__iexact=verified_email).order_by("pk")[:3])
    conflicting = [
        candidate for candidate in matches if candidate.pk != user.pk and not is_temporary_ctf_account(candidate)
    ]
    if conflicting:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE)


def accept_workspace_invitation(
    user: User,
    identity: VerifiedIdentity,
    claim: WorkspaceInvitationClaim,
    *,
    audit: MembershipAuditContext,
) -> WorkspaceMembershipProjection:
    """Consume a staged grant for one freshly verified provider identity."""
    invitation_hint = WorkspaceInvitation.objects.filter(public_id=claim.invitation_uuid).only("workspace_id").first()
    if invitation_hint is None:
        raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE)
    try:
        return _accept_invitation_locked(user, identity, claim, invitation_hint, audit=audit)
    except WorkspaceQuotaRejected as rejected:
        # Seat hard cap: the acceptance transaction has rolled back; record the
        # rejection evidence and map it once, mirroring the direct-add path.
        raise_member_seats_exhausted(rejected, audit)


def _accept_invitation_locked(
    user: User,
    identity: VerifiedIdentity,
    claim: WorkspaceInvitationClaim,
    invitation_hint: WorkspaceInvitation,
    *,
    audit: MembershipAuditContext,
) -> WorkspaceMembershipProjection:
    """Consume the staged grant under the workspace mutex (seat quota enforced within)."""
    with transaction.atomic():
        workspace = Workspace.objects.select_for_update().filter(pk=invitation_hint.workspace_id).first()
        invitation = (
            WorkspaceInvitation.objects.select_for_update()
            .select_related("workspace")
            .filter(pk=invitation_hint.pk, workspace=workspace)
            .first()
        )
        if (
            workspace is None
            or invitation is None
            or invitation.generation != claim.generation
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or invitation.expires_at <= timezone.now()
        ):
            raise _error("invitation_invalid", _INVALID_INVITATION_MESSAGE)
        _require_workspace_eligible(workspace)
        _eligible_verified_principal(user, identity, invitation.email)
        try:
            membership = _insert_workspace_membership(
                workspace,
                user,
                invitation.role,
                audit,
                exact_existing_is_idempotent=False,
            )
        except WorkspaceMembershipError as exc:
            if exc.code == "membership_exists":
                raise _error("membership_exists", "The account already has a workspace membership") from exc
            raise
        previous = _audit_state(invitation)
        invitation.accepted_by = user
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_by", "accepted_at", "updated_at"])
        _write_audit(invitation, AuditAction.CLOSE, audit, previous_state=previous, new_state=_audit_state(invitation))
        return membership
