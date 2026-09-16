"""Bind the workspace invitation domain service to the shared auth handoff port."""

import uuid

from shared.workspace_invitation_handoff import (
    WorkspaceInvitationAcceptance,
    WorkspaceInvitationAcceptanceError,
    bind_workspace_invitation_acceptor,
)
from workspaces import services


def _accept(command: WorkspaceInvitationAcceptance) -> uuid.UUID:
    """Translate the shared acceptance command into the workspace service."""
    try:
        membership = services.accept_workspace_invitation(
            command.user,
            command.identity,
            services.WorkspaceInvitationClaim(
                invitation_uuid=command.invitation_uuid,
                generation=command.generation,
            ),
            audit=services.MembershipAuditContext(
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                source_ip=command.source_ip,
                user_agent=command.user_agent,
                request_id=command.request_id,
            ),
        )
    except services.WorkspaceInvitationError as exc:
        raise WorkspaceInvitationAcceptanceError(exc.code) from exc
    return membership.workspace_uuid


def register_workspace_invitation_acceptor() -> None:
    """Bind the workspace acceptance adapter during app initialization."""
    bind_workspace_invitation_acceptor(_accept)
