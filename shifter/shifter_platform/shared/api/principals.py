"""Neutral active-user resolution for session and platform-token requests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.contrib.auth.models import AnonymousUser, User

from shared.api_tokens.models import ApiToken

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
