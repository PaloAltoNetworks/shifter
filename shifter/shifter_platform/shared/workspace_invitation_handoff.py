"""Neutral port for provider-authenticated workspace invitation acceptance."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from shared.verified_identity import VerifiedIdentity

STAGED_INVITATION_SESSION_KEY = "workspace_invitation_staged"
INVITATION_OUTCOME_SESSION_KEY = "workspace_invitation_outcome"
POST_LOGIN_CONTINUATION_SESSION_KEY = "workspace_invitation_continuation"


class WorkspaceInvitationAcceptanceError(Exception):
    """Bounded failure returned by the domain adapter."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class WorkspaceInvitationAcceptance:
    """Provider-neutral command sent from authentication composition to tenancy."""

    user: User
    identity: VerifiedIdentity
    invitation_uuid: uuid.UUID
    generation: uuid.UUID
    actor_type: str
    actor_id: int | None
    source_ip: str | None = None
    user_agent: str = ""
    request_id: str = ""


class WorkspaceInvitationAcceptor(Protocol):
    """Callable domain port bound by the workspace composition adapter."""

    def __call__(self, command: WorkspaceInvitationAcceptance) -> uuid.UUID:
        """Accept one staged invitation and return its workspace UUID."""
        ...


_acceptor: WorkspaceInvitationAcceptor | None = None


def bind_workspace_invitation_acceptor(acceptor: WorkspaceInvitationAcceptor) -> None:
    """Bind the tenancy adapter once at workspace-app startup."""
    global _acceptor
    if _acceptor is not None and _acceptor is not acceptor:
        raise RuntimeError("A workspace invitation acceptor is already bound")
    _acceptor = acceptor


def accept_workspace_invitation(command: WorkspaceInvitationAcceptance) -> uuid.UUID:
    """Dispatch through the bound domain adapter without importing the domain."""
    if _acceptor is None:
        raise RuntimeError("No workspace invitation acceptor is bound")
    return _acceptor(command)
