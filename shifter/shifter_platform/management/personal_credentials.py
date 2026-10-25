"""Session-owned personal credential lifecycle with live application policy."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, TypedDict, Unpack
from uuid import UUID

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from shared.api_tokens.audit import TokenEvent, record_token_event
from shared.api_tokens.models import ApiToken
from shared.api_tokens.policy import require_personal_token_grant
from shared.api_tokens.scopes import AUTHORIZATION_ACTION_SCOPES, credential_ceiling, validate_scopes
from shared.authorization import (
    AuthorizationProvider,
    AuthorizationRequest,
    TargetRef,
    configured_authorization_provider,
)
from shared.credentials import CredentialContext, resolve_credential_scope
from shared.identity_scope import ResourceScope
from shared.principal_port import resolve_principal

from .principals import principal_for_user

if TYPE_CHECKING:
    from django.http import HttpRequest

_CREDENTIAL_OPERATION_DENIED = "Credential operation denied"


def _authorize_token_administration(actor: CredentialContext, provider: AuthorizationProvider) -> None:
    """Revocation administration never grants the right to issue or use a token."""
    try:
        if actor.kind == "temporary":
            raise ValueError(_CREDENTIAL_OPERATION_DENIED)
        resolve_principal(actor.principal)
        request = AuthorizationRequest(
            actor.principal,
            "installation.revoke_personal_tokens",
            TargetRef("installation"),
            ResourceScope("installation"),
            actor.ceiling,
        )
        if not provider.check(request).allowed:
            raise ValueError(_CREDENTIAL_OPERATION_DENIED)
    except Exception as exc:
        raise ValueError(_CREDENTIAL_OPERATION_DENIED) from exc


def admin_list_personal_tokens(
    actor: CredentialContext, provider: AuthorizationProvider, principal_uuid: UUID, *, offset: int = 0, limit: int = 50
) -> dict[str, object]:
    """List safe metadata for one human, authorized before count and pagination."""
    from .credential_pagination import credential_page

    _authorize_token_administration(actor, provider)
    if not isinstance(principal_uuid, UUID):
        raise ValueError(_CREDENTIAL_OPERATION_DENIED)
    return credential_page(
        ApiToken.objects.filter(principal_uuid=principal_uuid).order_by("-created_at", "-pk"),
        offset=offset,
        limit=limit,
    )


def admin_revoke_personal_token(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    credential_uuid: UUID,
    *,
    request: HttpRequest | None = None,
) -> None:
    """Revoke an exact credential through Knox and strict principal audit."""
    _authorize_token_administration(actor, provider)
    with transaction.atomic():
        owner_id = (
            ApiToken.objects.filter(credential_uuid=credential_uuid).values_list("created_by_id", flat=True).first()
        )
        if owner_id is not None:
            User.objects.select_for_update().get(pk=owner_id)
        token = ApiToken.objects.select_for_update().filter(credential_uuid=credential_uuid).first()
        if token is None or token.created_by_id != owner_id:
            raise ValueError(_CREDENTIAL_OPERATION_DENIED)
        if token.revoked_at is None:
            token.revoke()
            record_token_event(
                TokenEvent.REVOKED,
                token_id=token.token_id,
                token_pk=token.pk,
                actor_principal_uuid=actor.principal.uuid,
                request=request,
                context="administrator credential revocation",
            )


class RotateArguments(TypedDict):
    """Closed arguments shared by personal issue and rotation operations."""

    actor: CredentialContext
    user: User
    name: str
    scopes: list[str]
    expires_at: datetime
    target: TargetRef
    scope: ResourceScope


def _session_owner(actor: CredentialContext, user: User) -> None:
    """The only human credential-management admission, also used for own revoke."""
    if (
        actor.kind != "session"
        or actor.principal.kind != "human"
        or not user.is_active
        or getattr(getattr(user, "profile", None), "is_ctf_account", False)
        or actor.principal != principal_for_user(user)
    ):
        raise ValueError(_CREDENTIAL_OPERATION_DENIED)


def _authorize_issue(
    actor: CredentialContext, user: User, scopes: list[str], target: TargetRef, scope: ResourceScope
) -> list[str]:
    """Validate issuance authority and normalize the requested scope list."""
    _session_owner(actor, user)
    require_personal_token_grant(actor.principal)
    normalized = validate_scopes(scopes)
    ceiling = credential_ceiling(normalized)
    if not ceiling.actions or resolve_credential_scope(target) != scope:
        raise ValueError("Credential authority unavailable")
    # Scope aliases may name the same action, but no unmapped legacy scope can
    # silently become an unbounded new credential.
    if any(item not in AUTHORIZATION_ACTION_SCOPES.values() for item in normalized):
        raise ValueError("Personal credentials require canonical application action scopes")
    forbidden = {"installation.use_personal_tokens", "installation.manage_service_credentials"}
    if ceiling.actions & forbidden:
        raise ValueError("Personal tokens cannot manage credentials")
    provider = configured_authorization_provider()
    for action in ceiling.actions:
        request = AuthorizationRequest(actor.principal, action, target, scope, actor.ceiling)
        if not provider.check(request).allowed:
            raise ValueError("Credential authority denied")
    return normalized


def issue_personal_token(
    *,
    actor: CredentialContext,
    user: User,
    name: str,
    scopes: list[str],
    expires_at: datetime,
    target: TargetRef,
    scope: ResourceScope,
) -> tuple[ApiToken, str]:
    """Issue once through Knox after checking the session and each live action."""
    normalized = _authorize_issue(actor, user, scopes, target, scope)
    return _persist_issue(actor=actor, user=user, name=name, scopes=normalized, expires_at=expires_at, target=target)


def _persist_issue(
    *,
    actor: CredentialContext,
    user: User,
    name: str,
    scopes: list[str],
    expires_at: datetime,
    target: TargetRef,
) -> tuple[ApiToken, str]:
    """Persist an already authorized issue; no network calls occur under locks."""
    if not isinstance(name, str) or not name.strip() or len(name) > 100 or expires_at <= timezone.now():
        raise ValueError("Invalid personal credential")
    with transaction.atomic():
        # Serialize local lifecycle with the credential mutation. External policy
        # reads above intentionally do not run while holding SQL locks.
        from .models import Principal

        owner = User.objects.select_for_update(of=("self",)).select_related("profile").get(pk=user.pk)
        Principal.objects.select_for_update().get(uuid=actor.principal.uuid, is_active=True)
        _session_owner(actor, owner)
        token, raw = ApiToken.create_token(
            name=name.strip(), created_by=user, scopes=scopes, expires_at=expires_at, target=target
        )
        record_token_event(
            TokenEvent.CREATED,
            token_id=token.token_id,
            token_pk=token.pk,
            actor_id=user.pk,
            actor_principal_uuid=actor.principal.uuid,
        )
    return token, raw


def list_own_tokens(actor: CredentialContext, user: User, *, offset: int = 0, limit: int = 50) -> dict[str, object]:
    """Listing safe metadata remains available without an issuance grant."""
    _session_owner(actor, user)
    from .credential_pagination import credential_page

    return credential_page(
        ApiToken.objects.filter(created_by=user, principal_uuid=actor.principal.uuid).order_by("-created_at", "-pk"),
        offset=offset,
        limit=limit,
    )


def revoke_own_token(actor: CredentialContext, user: User, credential_uuid: UUID) -> None:
    """Idempotently revoke an exact owned credential even after grant loss."""
    _session_owner(actor, user)
    with transaction.atomic():
        _session_owner(actor, User.objects.select_for_update(of=("self",)).select_related("profile").get(pk=user.pk))
        token = (
            ApiToken.objects.select_for_update()
            .filter(credential_uuid=credential_uuid, created_by=user, principal_uuid=actor.principal.uuid)
            .first()
        )
        if token is None:
            raise ValueError(_CREDENTIAL_OPERATION_DENIED)
        if token.revoked_at is None:
            token.revoke()
            record_token_event(
                TokenEvent.REVOKED,
                token_id=token.token_id,
                token_pk=token.pk,
                actor_id=user.pk,
                actor_principal_uuid=actor.principal.uuid,
            )


def rotate_personal_token(credential_uuid: UUID, **kwargs: Unpack[RotateArguments]) -> tuple[ApiToken, str]:
    """Authorize before locks, then atomically replace and retire the old proof."""
    normalized = _authorize_issue(kwargs["actor"], kwargs["user"], kwargs["scopes"], kwargs["target"], kwargs["scope"])
    with transaction.atomic():
        owner = User.objects.select_for_update(of=("self",)).select_related("profile").get(pk=kwargs["user"].pk)
        _session_owner(kwargs["actor"], owner)
        previous = (
            ApiToken.objects.select_for_update()
            .filter(credential_uuid=credential_uuid, created_by=kwargs["user"], revoked_at__isnull=True)
            .first()
        )
        if previous is None:
            raise ValueError(_CREDENTIAL_OPERATION_DENIED)
        token, raw = _persist_issue(
            actor=kwargs["actor"],
            user=kwargs["user"],
            name=kwargs["name"],
            scopes=normalized,
            expires_at=kwargs["expires_at"],
            target=kwargs["target"],
        )
        revoke_own_token(kwargs["actor"], kwargs["user"], credential_uuid)
    return token, raw
