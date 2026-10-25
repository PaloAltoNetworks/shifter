"""Neutral fail-closed principal directory binding (ADR-066, #2315)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import UUID

from shared.identity_scope import PrincipalRef
from shared.verified_identity import VerifiedIdentity

if TYPE_CHECKING:
    from django.contrib.auth.models import User

_DIRECTORY_UNBOUND = "No principal directory is bound"
_PRINCIPAL_UNAVAILABLE = "Principal unavailable"

PrincipalForUser = Callable[["User"], PrincipalRef]
PrincipalResolver = Callable[[PrincipalRef], PrincipalRef]
PrincipalUuidResolver = Callable[[UUID], PrincipalRef]
VerifiedPrincipalResolver = Callable[[VerifiedIdentity], PrincipalRef]


class PrincipalResolutionError(RuntimeError):
    """The principal directory is unavailable or rejected an identity."""


_for_user: PrincipalForUser | None = None
_resolver: PrincipalResolver | None = None
_uuid_resolver: PrincipalUuidResolver | None = None
_verified_resolver: VerifiedPrincipalResolver | None = None
_identity_for_user: PrincipalForUser | None = None


def bind_principal_directory(
    for_user: PrincipalForUser,
    resolver: PrincipalResolver,
    uuid_resolver: PrincipalUuidResolver,
    verified_resolver: VerifiedPrincipalResolver | None = None,
    identity_for_user: PrincipalForUser | None = None,
) -> None:
    """Bind the management-owned directory once at composition startup."""
    global _for_user, _resolver, _uuid_resolver, _verified_resolver, _identity_for_user
    bindings: tuple[tuple[object | None, object], ...] = (
        (_for_user, for_user),
        (_resolver, resolver),
        (_uuid_resolver, uuid_resolver),
    )
    if verified_resolver is not None:
        bindings += ((_verified_resolver, verified_resolver),)
    if identity_for_user is not None:
        bindings += ((_identity_for_user, identity_for_user),)
    if any(current is not None and current is not incoming for current, incoming in bindings):
        raise PrincipalResolutionError("A different principal directory is already bound")
    _for_user = for_user
    _resolver = resolver
    _uuid_resolver = uuid_resolver
    if verified_resolver is not None:
        _verified_resolver = verified_resolver
    if identity_for_user is not None:
        _identity_for_user = identity_for_user


def principal_identity_for_user(user: User) -> PrincipalRef:
    """Read ownership identity of an inactive human; this is not credential admission."""
    if _identity_for_user is None:
        raise PrincipalResolutionError(_DIRECTORY_UNBOUND)
    try:
        return _identity_for_user(user)
    except Exception as exc:
        raise PrincipalResolutionError(_PRINCIPAL_UNAVAILABLE) from exc


def resolve_verified_principal(identity: VerifiedIdentity) -> PrincipalRef:
    """Resolve exact provider issuer/subject, independently of email matching."""
    if _verified_resolver is None:
        raise PrincipalResolutionError(_DIRECTORY_UNBOUND)
    try:
        return _verified_resolver(identity)
    except Exception as exc:
        raise PrincipalResolutionError(_PRINCIPAL_UNAVAILABLE) from exc


def principal_for_user(user: User) -> PrincipalRef:
    """Resolve an existing human principal through the bound management directory."""
    if _for_user is None:
        raise PrincipalResolutionError(_DIRECTORY_UNBOUND)
    try:
        return _for_user(user)
    except PrincipalResolutionError:
        raise
    except Exception as exc:
        raise PrincipalResolutionError(_PRINCIPAL_UNAVAILABLE) from exc


def resolve_principal(principal: PrincipalRef) -> PrincipalRef:
    """Revalidate an active principal through the bound management directory."""
    if _resolver is None:
        raise PrincipalResolutionError(_DIRECTORY_UNBOUND)
    try:
        return _resolver(principal)
    except PrincipalResolutionError:
        raise
    except Exception as exc:
        raise PrincipalResolutionError(_PRINCIPAL_UNAVAILABLE) from exc


def resolve_principal_uuid(principal_uuid: UUID) -> PrincipalRef:
    """Resolve an active principal UUID without exposing management persistence."""
    if _uuid_resolver is None:
        raise PrincipalResolutionError(_DIRECTORY_UNBOUND)
    try:
        return _uuid_resolver(principal_uuid)
    except PrincipalResolutionError:
        raise
    except Exception as exc:
        raise PrincipalResolutionError(_PRINCIPAL_UNAVAILABLE) from exc
