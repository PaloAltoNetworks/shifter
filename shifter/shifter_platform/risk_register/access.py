"""Risk register Cognito group access policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from shared.api_tokens.models import ApiToken

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.http import HttpRequest


def allowed_risk_register_cognito_groups() -> frozenset[str]:
    """Return configured Cognito groups that grant risk register access."""
    return frozenset(getattr(settings, "RISK_REGISTER_ALLOWED_COGNITO_GROUPS", ()))


def cognito_groups_for_user(user: User) -> list[str]:
    """Return Cognito groups last captured for ``user``."""
    from management.services import get_user_profile

    profile = get_user_profile(user)
    return list(profile.cognito_groups or [])


def _groups_intersect_allowed(groups: list[str]) -> bool:
    """Return True when ``groups`` intersects the configured allow-list."""
    allowed = allowed_risk_register_cognito_groups()
    if not allowed:
        return False
    return bool(set(groups) & allowed)


def _token_owner_has_access(auth: ApiToken) -> bool:
    """Return True when the token owner belongs to an allowed group."""
    owner = getattr(auth, "created_by", None)
    if owner is None:
        return False
    return _groups_intersect_allowed(cognito_groups_for_user(owner))


def _session_user_has_access(request: HttpRequest, user: User) -> bool:
    """Return True when the session or profile groups satisfy the allow-list."""
    session_groups = request.session.get("cognito_groups")
    groups = list(session_groups) if session_groups is not None else cognito_groups_for_user(user)
    return _groups_intersect_allowed(groups)


def principal_has_risk_register_access(request: HttpRequest) -> bool:
    """Return True when the request principal is in an allowed Cognito group."""
    allowed = allowed_risk_register_cognito_groups()
    auth = getattr(request, "auth", None)
    user = getattr(request, "user", None)

    result = False
    if allowed and isinstance(auth, ApiToken):
        result = _token_owner_has_access(auth)
    elif allowed and user and user.is_authenticated:
        result = _session_user_has_access(request, user)
    return result
