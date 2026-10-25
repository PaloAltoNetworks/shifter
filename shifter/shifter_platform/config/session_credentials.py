"""Bounded provider assurance shared by HTTP and Channels session admission."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import TypedDict, cast

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, get_user, logout
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.sessions.backends.base import SessionBase
from django.http import HttpRequest, HttpResponse

from shared.principal_port import PrincipalResolutionError, principal_for_user

IDENTITY_BACKEND = "config.identity_platform.IdentityPlatformBackend"
ASSURANCE_KEY = "identity_assurance"


class IdentityAssurance(TypedDict):
    """Narrow verified identity and timing evidence retained in a session."""

    issuer: str
    subject: str
    auth_time: float
    created: float
    tenant: str
    seen: float
    checked: float


def establish_identity_session(session: SessionBase, claims: dict[str, object], *, now: float | None = None) -> None:
    """Persist only verified identity and timing evidence, never the ID token."""
    timestamp = time.time() if now is None else now
    session[ASSURANCE_KEY] = {
        "issuer": claims["iss"],
        "subject": claims["sub"],
        "auth_time": claims["auth_time"],
        "created": claims["auth_time"],
        "tenant": claims.get("tenant", ""),
        "seen": timestamp,
        "checked": timestamp,
    }


def _validated_assurance(session: SessionBase, now: float) -> IdentityAssurance:
    """Validate and narrow persisted assurance state without trusting its shape."""
    raw = session.get(ASSURANCE_KEY)
    if not isinstance(raw, dict):
        raise ValueError("Identity assurance is unavailable")
    issuer = raw.get("issuer")
    subject = raw.get("subject")
    tenant = raw.get("tenant")
    expected_issuer = f"https://securetoken.google.com/{settings.IDENTITY_PLATFORM_PROJECT_ID}"
    if issuer != expected_issuer or tenant != settings.IDENTITY_PLATFORM_TENANT_ID or not isinstance(subject, str):
        raise ValueError("Identity assurance does not match provider configuration")
    times = _validated_assurance_times(raw, now)
    return {
        "issuer": issuer,
        "subject": subject,
        "tenant": tenant,
        "created": times["created"],
        "seen": times["seen"],
        "checked": times["checked"],
        "auth_time": times["auth_time"],
    }


def _validated_assurance_times(raw: dict[str, object], now: float) -> dict[str, float]:
    """Reject malformed, future, and non-finite session timestamps."""
    times: dict[str, float] = {}
    for key in ("created", "seen", "checked", "auth_time"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError("Identity assurance timestamp is invalid")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric > now or numeric < 0:
            raise ValueError("Identity assurance timestamp is invalid")
        times[key] = numeric
    return times


def _recheck_provider_state(state: IdentityAssurance) -> None:
    """Require the provider account to remain enabled, verified, and unrevoked."""
    from config.identity_platform import provider_user_state

    record = provider_user_state(state["subject"])
    if record.disabled or record.email_verified is not True:
        raise ValueError("Provider identity is inactive")
    if record.tokens_valid_after_timestamp / 1000 > state["auth_time"]:
        raise ValueError("Provider identity was revoked")


def _identity_session_valid(user: User, session: SessionBase, now: float) -> bool:
    """Validate stored assurance, live binding, time limits, and provider state."""
    from management.services import resolve_user_by_provider_identity

    try:
        state = _validated_assurance(session, now)
        if now - state["created"] >= settings.IDENTITY_SESSION_ABSOLUTE_SECONDS:
            raise ValueError("Identity session exceeded its absolute lifetime")
        if now - state["seen"] >= settings.IDENTITY_SESSION_IDLE_SECONDS:
            raise ValueError("Identity session exceeded its idle lifetime")
        if not resolve_user_by_provider_identity(state["issuer"], state["subject"]).filter(pk=user.pk).exists():
            raise ValueError("Provider identity binding is unavailable")
        if now - state["checked"] >= settings.IDENTITY_SESSION_RECHECK_SECONDS:
            _recheck_provider_state(state)
            state["checked"] = now
        state["seen"] = now
        session[ASSURANCE_KEY] = state
        return True
    except Exception:
        # Provider/database outages and malformed state never extend a proof.
        return False


def validate_session(user: User | AnonymousUser, session: SessionBase, *, now: float | None = None) -> bool:
    """Recheck local lifecycle every use and provider state at a bounded interval."""
    valid = False
    if isinstance(user, User) and bool(getattr(user, "is_authenticated", False)):
        valid = True
        try:
            principal_for_user(user)
        except PrincipalResolutionError:
            valid = False
        if valid and session.get(BACKEND_SESSION_KEY) == IDENTITY_BACKEND:
            valid = _identity_session_valid(user, session, time.time() if now is None else now)
    return valid


def validate_socket_session(scope: dict[str, object]) -> bool:
    """Reload Django state so logout/password invalidation also closes sockets."""
    from importlib import import_module

    try:
        cached = scope.get("session")
        if not isinstance(cached, SessionBase) or not cached.session_key:
            raise ValueError("Socket session is unavailable")
        session = import_module(settings.SESSION_ENGINE).SessionStore(session_key=cached.session_key)
        request = cast(HttpRequest, SimpleNamespace(session=session))
        user = get_user(request)
        if not validate_session(user, session):
            raise ValueError("Socket session is invalid")
        if session.modified:
            session.save(must_create=False)
        scope["user"] = user
        scope["session"] = session
        return True
    except Exception:
        return False


class CredentialSessionMiddleware:
    """Discard invalid sessions before any HTTP authorization boundary runs."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.user.is_authenticated and not validate_session(request.user, request.session):
            logout(request)
        return self.get_response(request)
