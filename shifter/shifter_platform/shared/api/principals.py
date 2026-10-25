"""Neutral active-user resolution for session and platform-token requests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.contrib.auth.models import AnonymousUser, User

from shared.api_tokens.models import ApiToken
from shared.authorization import ACTION_CATALOG, CredentialCeiling
from shared.credentials import CredentialContext, temporary_credential
from shared.principal_port import principal_for_user, resolve_principal

if TYPE_CHECKING:
    from rest_framework.request import Request


def active_actor_user(request: Request) -> User | None:
    """Return the active user represented by a session or token request."""
    auth = getattr(request, "auth", None)
    user = auth.created_by if isinstance(auth, ApiToken) else getattr(request, "user", None)
    if user is None or isinstance(user, AnonymousUser):
        return None
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return None
    return cast(User, user)


def authenticated_credential(request: Request) -> CredentialContext:
    """Resolve the one credential context without treating a service as a user."""
    credential = getattr(request, "credential_context", None)
    if isinstance(credential, CredentialContext):
        resolve_principal(credential.principal)
        return credential
    if getattr(request, "auth", None) is not None:
        raise ValueError("Credential context unavailable")
    user = active_actor_user(request)
    if user is None:
        raise ValueError("Unrestricted human session unavailable")
    if getattr(getattr(user, "profile", None), "is_ctf_account", False):
        return temporary_credential(user)
    principal = principal_for_user(user)
    return CredentialContext(
        principal=principal,
        kind="session",
        credential_uuid=principal.uuid,
        ceiling=CredentialCeiling(frozenset(action.code for action in ACTION_CATALOG)),
        scopes=frozenset(),
    )
