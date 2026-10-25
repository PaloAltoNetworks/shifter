"""Administer user-administration domain services (#1373).

Admin-facing read (list) and command (activate/deactivate) operations for the
Administer workspace, split from :mod:`management.services` to keep each module
focused and under the file-size budget. The composition root consumes only the
core seams in :mod:`management.services` (ADR-001); these admin-only services are
consumed by ``management.api``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from management.policy import require_principal_administration
from shared.audit import AuditAction, AuditEntityType, AuditEvent, RequestAudit, audit_log
from shared.authorization import AuthorizationProvider
from shared.credentials import CredentialContext

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import QuerySet

    from management.models import UserProfile

# Bounded length for the Administer user-search input (defence in depth; the API
# query serializer also enforces it).
ADMIN_USER_SEARCH_MAX_LEN = 100

# Allowlisted account-origin filter values for the Administer user list.
ADMIN_ACCOUNT_ORIGINS = ("provider", "local", "ctf")
_INVALID_METADATA = "Invalid user metadata"


def _apply_metadata_changes(user: User, changes: Mapping[str, str]) -> list[str]:
    """Validate the existing model before persisting any changed metadata fields."""
    fields = []
    for field, value in changes.items():
        if not isinstance(value, str):
            raise ValueError(_INVALID_METADATA)
        if getattr(user, field) != value:
            setattr(user, field, value)
            fields.append(field)
    try:
        user.full_clean(exclude=["password", "last_login", "date_joined"])
    except ValidationError as exc:
        raise ValueError(_INVALID_METADATA) from exc
    return fields


def _require_recovery_email_owner(actor: CredentialContext, user: User, changes: Mapping[str, str]) -> None:
    """Administration of identity metadata never grants another user's recovery."""
    from shared.principal_port import principal_identity_for_user

    if (
        "email" in changes
        and changes["email"] != user.email
        and (actor.kind != "session" or actor.principal != principal_identity_for_user(user))
    ):
        raise ValueError("Recovery email requires its owning human session")


def update_policy_user_metadata(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    user_id: int,
    changes: Mapping[str, str],
    *,
    audit: RequestAudit | None = None,
) -> User:
    """Preserve validated contact/display edits without touching identity or authority."""
    require_principal_administration(actor, provider)
    if not changes or not set(changes) <= {"username", "email", "first_name", "last_name"}:
        raise ValueError(_INVALID_METADATA)
    attribution = audit or RequestAudit()
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=user_id)
        from management.models import UserProfile

        profile = UserProfile.objects.select_for_update().filter(user=user).first()
        if profile is not None and (profile.is_ctf_account or profile.deleted_at or profile.anonymized_at):
            raise ValueError("User metadata unavailable")
        _require_recovery_email_owner(actor, user, changes)
        fields = _apply_metadata_changes(user, changes)
        if fields:
            try:
                user.save(update_fields=fields)
            except IntegrityError as exc:
                raise ValueError(_INVALID_METADATA) from exc
            audit_log(
                AuditEvent(
                    entity_type=AuditEntityType.USER,
                    entity_id=user.pk,
                    action=AuditAction.UPDATE,
                    actor_type="principal",
                    actor_principal_uuid=actor.principal.uuid,
                    new_state={"changed_fields": sorted(fields)},
                    context="user_metadata",
                    source_ip=attribution.source_ip,
                    user_agent=attribution.user_agent[:500],
                    request_id=attribution.request_id[:64],
                ),
                strict=True,
            )
        return user


def classify_account_origin(profile: UserProfile | None) -> str:
    """Classify an account's origin for the Administer read surface.

    Returns ``"ctf"`` (temporary event-scoped participant account), ``"provider"``
    (bound to a verified OIDC/Identity Platform identity), or ``"local"`` (a
    locally managed or profile-less account). Read-only, derived from durable
    profile facts; never exposes the issuer/subject.
    """
    if profile is not None and profile.is_ctf_account:
        return "ctf"
    if profile is not None and profile.cognito_sub:
        return "provider"
    return "local"


def list_admin_users(
    *,
    search: str = "",
    user_type: str = "",
    is_active: bool | None = None,
    account_origin: str = "",
    include_deleted: bool = False,
) -> QuerySet[User]:
    """Return the bounded, admin-facing user queryset for the Administer list.

    Applies allowlisted filters and a bounded username/email search, selecting
    the related profile so the read serializer avoids per-row queries. Ordering
    is deterministic (``-date_joined``, ``id``). Soft-deleted accounts are
    excluded unless ``include_deleted`` is set. Callers paginate the result; this
    never exposes identity-binding internals.
    """
    user_model = get_user_model()
    queryset = user_model.objects.select_related("profile").prefetch_related("groups").order_by("-date_joined", "id")

    if not include_deleted:
        queryset = queryset.filter(Q(profile__deleted_at__isnull=True) | Q(profile__isnull=True))

    search = (search or "").strip()[:ADMIN_USER_SEARCH_MAX_LEN]
    if search:
        queryset = queryset.filter(Q(username__icontains=search) | Q(email__icontains=search))

    if user_type:
        queryset = queryset.filter(profile__user_type=user_type)

    if is_active is not None:
        queryset = queryset.filter(is_active=is_active)

    if account_origin == "ctf":
        queryset = queryset.filter(profile__is_ctf_account=True)
    elif account_origin == "provider":
        queryset = queryset.filter(profile__is_ctf_account=False).exclude(
            Q(profile__cognito_sub__isnull=True) | Q(profile__cognito_sub="")
        )
    elif account_origin == "local":
        # A profile-less account is classified "local" by classify_account_origin,
        # so the Local filter must include profile__isnull rows too; otherwise the
        # list hides accounts it otherwise labels Local.
        queryset = queryset.filter(
            Q(profile__isnull=True)
            | (Q(profile__is_ctf_account=False) & (Q(profile__cognito_sub__isnull=True) | Q(profile__cognito_sub="")))
        )

    return queryset


def list_policy_admin_users(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    *,
    search: str = "",
    user_type: str = "",
    is_active: bool | None = None,
    account_origin: str = "",
    include_deleted: bool = False,
) -> QuerySet[User]:
    """Authorize the global identity list before count, filtering, or paging."""
    require_principal_administration(actor, provider)
    return list_admin_users(
        search=search,
        user_type=user_type,
        is_active=is_active,
        account_origin=account_origin,
        include_deleted=include_deleted,
    )
