"""Provider-neutral authenticated handoff for staged workspace invitations."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from django.contrib.auth.signals import user_logged_in
from django.urls import reverse

from shared.audit import AuditActorType, get_client_ip, get_request_id
from shared.verified_identity import VerifiedIdentity
from shared.workspace_invitation_handoff import (
    INVITATION_OUTCOME_SESSION_KEY,
    POST_LOGIN_CONTINUATION_SESSION_KEY,
    STAGED_INVITATION_SESSION_KEY,
    WorkspaceInvitationAcceptance,
    WorkspaceInvitationAcceptanceError,
    accept_workspace_invitation,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.http import HttpRequest

_VERIFIED_IDENTITY_REQUEST_ATTRIBUTE = "_workspace_invitation_verified_identity"
logger = logging.getLogger(__name__)


def attach_fresh_verified_identity(request: HttpRequest | None, identity: VerifiedIdentity) -> None:
    """Attach provider-verified evidence to the in-flight auth transaction only."""
    if request is not None:
        setattr(request, _VERIFIED_IDENTITY_REQUEST_ATTRIBUTE, identity)


def preserve_staged_invitation_across_logout(request: HttpRequest) -> dict[str, str] | None:
    """Copy only the nonsecret staged claim across forced reauthentication."""
    value = request.session.get(STAGED_INVITATION_SESSION_KEY)
    if not isinstance(value, dict):
        return None
    invitation_uuid = value.get("invitation_uuid")
    generation = value.get("generation")
    if not isinstance(invitation_uuid, str) or not isinstance(generation, str):
        return None
    return {"invitation_uuid": invitation_uuid, "generation": generation}


def pop_post_login_continuation(request: HttpRequest) -> str | None:
    """Return the single allowlisted invitation continuation, if present."""
    session = getattr(request, "session", None)
    if session is None:
        return None
    value = session.pop(POST_LOGIN_CONTINUATION_SESSION_KEY, None)
    expected = reverse("workspace_invitation_accept")
    return expected if value == expected else None


def _claim_from_session(value: object) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Parse the exact nonsecret staged-claim session shape."""
    if not isinstance(value, dict) or set(value) != {"invitation_uuid", "generation"}:
        return None
    try:
        return uuid.UUID(value["invitation_uuid"]), uuid.UUID(value["generation"])
    except (TypeError, ValueError):
        return None


def consume_staged_workspace_invitation(sender: object, request: HttpRequest, user: User, **kwargs: object) -> None:
    """Consume a grant only during login carrying fresh provider evidence."""
    del sender, kwargs
    staged = request.session.pop(STAGED_INVITATION_SESSION_KEY, None)
    if staged is None:
        return
    outcome: dict[str, str] = {"status": "failed", "code": "invitation_invalid"}
    claim = _claim_from_session(staged)
    identity = getattr(request, _VERIFIED_IDENTITY_REQUEST_ATTRIBUTE, None)
    if claim is not None and isinstance(identity, VerifiedIdentity):
        try:
            workspace_uuid = accept_workspace_invitation(
                WorkspaceInvitationAcceptance(
                    user=user,
                    identity=identity,
                    invitation_uuid=claim[0],
                    generation=claim[1],
                    actor_type=AuditActorType.USER,
                    actor_id=user.pk,
                    source_ip=get_client_ip(request),
                    user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
                    request_id=get_request_id(request),
                )
            )
        except WorkspaceInvitationAcceptanceError as exc:
            outcome["code"] = exc.code if exc.code == "membership_exists" else "invitation_invalid"
        except Exception:
            logger.exception("Workspace invitation acceptance failed")
        else:
            outcome = {"status": "accepted", "workspace_uuid": str(workspace_uuid)}
    request.session[INVITATION_OUTCOME_SESSION_KEY] = outcome
    request.session[POST_LOGIN_CONTINUATION_SESSION_KEY] = reverse("workspace_invitation_accept")


def register_workspace_invitation_login_signal() -> None:
    """Register the provider-neutral post-login invitation consumer once."""
    user_logged_in.connect(
        consume_staged_workspace_invitation,
        dispatch_uid="config_workspace_invitation_login",
        weak=False,
    )
