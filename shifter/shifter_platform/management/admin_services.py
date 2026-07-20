"""Administer user-administration domain services (#1373).

Admin-facing read (list) and command (activate/deactivate) operations for the
Administer workspace, split from :mod:`management.services` to keep each module
focused and under the file-size budget. The composition root consumes only the
core seams in :mod:`management.services` (ADR-001); these admin-only services are
consumed by ``management.api``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

from management.services import USER_PK_REQUIRED_MSG, AuditContext
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from shared.constants import USER_CANNOT_BE_NONE
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import QuerySet

    from management.models import UserProfile

logger = logging.getLogger(__name__)

# Bounded length for the Administer user-search input (defence in depth; the API
# query serializer also enforces it).
ADMIN_USER_SEARCH_MAX_LEN = 100

# Allowlisted account-origin filter values for the Administer user list.
ADMIN_ACCOUNT_ORIGINS = ("provider", "local", "ctf")


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


def set_user_active(user: User, *, active: bool, audit: AuditContext) -> None:
    """Enable or disable a user's ability to authenticate (``User.is_active``).

    Distinct from soft deletion, anonymization, and privilege revocation. The
    field change and a strict, request-attributed audit row are written in one
    atomic block; an audit-write failure rolls the change back so the account
    state and the audit trail can never diverge.

    Raises:
        TypeError: If user is None
        ValueError: If user has no primary key (unsaved)
    """
    if user is None:
        raise TypeError(USER_CANNOT_BE_NONE)
    if user.pk is None:
        raise ValueError(USER_PK_REQUIRED_MSG)

    previous_active = user.is_active
    with transaction.atomic():
        if previous_active != active:
            user.is_active = active
            user.save(update_fields=["is_active"])
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.USER,
                entity_id=user.id,
                action=AuditAction.UPDATE,
                actor_type=audit.actor_type,
                actor_id=audit.actor_id,
                previous_state={"is_active": previous_active},
                new_state={"is_active": active},
                request_id=audit.request_id,
                source_ip=audit.source_ip,
                user_agent=audit.user_agent,
            ),
            strict=True,
        )
    logger.info("Set is_active=%s for user %s", active, safe_log_value(user.email))
