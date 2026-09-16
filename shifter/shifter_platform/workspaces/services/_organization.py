"""Organization profile read/update seam (ADR-048, PLAT-232).

One service resolves an actor and a public organization UUID into a frozen
profile projection or an opaque denial. Authorization is read from a persisted
``admin`` :class:`~workspaces.models.OrganizationMembership` only, never
re-derived from a workspace role, Django staff/groups, model permissions,
identity-provider claims, API-token scopes, or cloud roles (ADR-046-R8). A
Django superuser is an orthogonal platform-operator override recorded distinctly
in audit.

Public surfaces address organizations by their immutable ``uuid`` only; the
integer primary key stays inside this domain and the integer-shaped audit store.
Updates are atomic, lock the organization row, re-check authority under the
lock, write only changed fields, and emit one strict audit event that records
changed field *names* -- never their values.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator, validate_email
from django.db import transaction

from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from workspaces.models import Organization, OrganizationMembership
from workspaces.roles import OrganizationRole

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

# One message for every denial: a missing organization, an organization outside
# the actor's authority, and insufficient authority must be indistinguishable so
# the surface is not a tenant-enumeration oracle.
_ORG_DENIED_MESSAGE = "Organization access denied"

# The organization profile fields a caller may read or update. ``name`` is the
# canonical display name; the rest are optional and default to empty string
# ("unset"). Identity fields (``uuid``, timestamps) are never writable here.
_PROFILE_FIELDS: tuple[str, ...] = ("name", "description", "support_email", "support_url")

# Maximum lengths, matched to the model column bounds. The service owns these so
# the invariant holds for every caller of the facade, not only the HTTP boundary
# (ADR-046-R12, ADR-048-R6).
_MAX_LENGTHS: dict[str, int] = {"name": 200, "description": 2000, "support_email": 254, "support_url": 500}


class OrganizationAuthorizationError(Exception):
    """Raised when an actor may not read or update an organization profile."""


class OrganizationValidationError(Exception):
    """Raised when an organization profile update carries invalid field values."""


@dataclass(frozen=True, slots=True)
class OrganizationProfile:
    """Immutable public organization profile projection (scalars only)."""

    uuid: uuid.UUID
    name: str
    description: str
    support_email: str
    support_url: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OrganizationAuditContext:
    """Trusted request attribution supplied by the HTTP boundary."""

    actor_type: str
    actor_id: int | None
    source_ip: str | None = None
    user_agent: str = ""
    request_id: str = ""


def _parsed_uuid(value: str | uuid.UUID) -> uuid.UUID:
    """Parse a public organization UUID, treating a malformed value as a denial.

    A bad input must be indistinguishable from an organization the actor may not
    see, so it raises the opaque denial rather than a ``ValueError``.
    """
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise OrganizationAuthorizationError(_ORG_DENIED_MESSAGE) from exc


def _profile_from(organization: Organization) -> OrganizationProfile:
    """Project an organization row onto the immutable public profile."""
    return OrganizationProfile(
        uuid=organization.uuid,
        name=organization.name,
        description=organization.description,
        support_email=organization.support_email,
        support_url=organization.support_url,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
    )


def _validate_format(changes: Mapping[str, str]) -> None:
    """Validate optional email/URL formats, converting Django errors to the domain error."""
    try:
        if changes.get("support_email"):
            validate_email(changes["support_email"])
        if changes.get("support_url"):
            URLValidator()(changes["support_url"])
    except DjangoValidationError as exc:
        raise OrganizationValidationError("invalid organization profile field format") from exc


def _validate_changes(changes: Mapping[str, str]) -> None:
    """Enforce the organization profile invariants for every caller of the facade.

    Rejects unknown fields, non-string or over-length values, a blank ``name``,
    and malformed email/URL values. This is the single domain validation path
    that holds outside HTTP (ADR-046-R12); the DRF serializer is an additional
    HTTP-boundary shape check, not the only guard.
    """
    unknown = set(changes) - set(_PROFILE_FIELDS)
    if unknown:
        raise OrganizationValidationError(f"unknown organization profile fields: {sorted(unknown)}")
    for field, value in changes.items():
        if not isinstance(value, str):
            raise OrganizationValidationError(f"{field} must be a string")
        if len(value) > _MAX_LENGTHS[field]:
            raise OrganizationValidationError(f"{field} exceeds {_MAX_LENGTHS[field]} characters")
    if "name" in changes and not changes["name"].strip():
        raise OrganizationValidationError("name must not be blank")
    _validate_format(changes)


def _authorize(actor: User, organization: Organization) -> bool:
    """Authorize ``actor`` for ``organization``; fail closed with the opaque denial.

    Returns:
        bool: True when a Django superuser override admitted the actor, False
        when a persisted ``admin`` organization membership did. Any other actor
        raises :class:`OrganizationAuthorizationError`.
    """
    if getattr(actor, "is_superuser", False):
        return True
    is_admin = OrganizationMembership.objects.filter(
        organization=organization,
        user=actor,
        role=OrganizationRole.ADMIN.value,
    ).exists()
    if not is_admin:
        raise OrganizationAuthorizationError(_ORG_DENIED_MESSAGE)
    return False


def resolve_administrable_organization(
    actor: User,
    organization_uuid: str | uuid.UUID,
) -> tuple[Organization, bool]:
    """Resolve a public organization UUID the ``actor`` may administer.

    Shared entry point for sibling services (e.g. workspace lifecycle, #1940)
    that need the persisted ADR-048 organization-admin authority without
    re-deriving it. A malformed UUID, a missing organization, and insufficient
    authority all raise the same opaque :class:`OrganizationAuthorizationError`
    so the caller cannot become a tenant-enumeration oracle.

    Returns:
        tuple[Organization, bool]: the organization and whether a Django
        superuser override (rather than a persisted ``admin`` membership)
        admitted the actor.
    """
    parsed = _parsed_uuid(organization_uuid)
    organization = Organization.objects.filter(uuid=parsed).first()
    if organization is None:
        raise OrganizationAuthorizationError(_ORG_DENIED_MESSAGE)
    superuser_override = _authorize(actor, organization)
    return organization, superuser_override


def _write_audit(
    organization: Organization,
    changed_fields: list[str],
    *,
    superuser_override: bool,
    audit: OrganizationAuditContext,
) -> None:
    """Write a strict organization-update audit event within the caller's transaction.

    Records the changed field *names* and the internal organization id only; the
    field values (descriptions, emails, URLs, names) are never copied into the
    durable audit store.
    """
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.ORGANIZATION,
            entity_id=organization.pk,
            action=AuditAction.UPDATE,
            actor_type=audit.actor_type,
            actor_id=audit.actor_id,
            new_state={
                "changed_fields": sorted(changed_fields),
                "organization_id": organization.pk,
                "superuser_override": superuser_override,
            },
            context="organization_profile",
            source_ip=audit.source_ip,
            user_agent=audit.user_agent[:500],
            request_id=audit.request_id[:64],
        ),
        strict=True,
    )


def get_organization_profile(actor: User, organization_uuid: str | uuid.UUID) -> OrganizationProfile:
    """Return the organization profile addressed by its public ``organization_uuid``.

    Side-effect free. Authorizes the read before returning any target-specific
    data (an ``admin`` organization membership or a superuser override); a
    missing organization, an organization outside the actor's authority, and
    insufficient authority raise the same opaque denial.

    Raises:
        OrganizationAuthorizationError: The UUID is malformed, the organization
            does not exist, or the actor may not read it.
    """
    parsed = _parsed_uuid(organization_uuid)
    organization = Organization.objects.filter(uuid=parsed).first()
    if organization is None:
        raise OrganizationAuthorizationError(_ORG_DENIED_MESSAGE)
    _authorize(actor, organization)
    return _profile_from(organization)


def update_organization_profile(
    actor: User,
    organization_uuid: str | uuid.UUID,
    changes: Mapping[str, str],
    *,
    audit: OrganizationAuditContext,
) -> OrganizationProfile:
    """Apply a partial update to an organization profile and return the projection.

    PATCH semantics: only supplied profile fields are considered, and only those
    whose value actually differs from the stored value are written. An empty or
    no-op change set performs no write and records no audit event (a no-op does
    not claim a mutation occurred). A real update is atomic: it locks the
    organization row, re-checks live authority under the lock, saves only the
    changed fields, and emits one strict audit event in the same transaction, so
    an audit-write failure rolls the profile update back.

    Raises:
        OrganizationAuthorizationError: The UUID is malformed, the organization
            does not exist, or the actor may not update it.
    """
    parsed = _parsed_uuid(organization_uuid)
    _validate_changes(changes)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().filter(uuid=parsed).first()
        if organization is None:
            raise OrganizationAuthorizationError(_ORG_DENIED_MESSAGE)
        superuser_override = _authorize(actor, organization)
        changed = [
            field for field in _PROFILE_FIELDS if field in changes and getattr(organization, field) != changes[field]
        ]
        if changed:
            for field in changed:
                setattr(organization, field, changes[field])
            organization.save(update_fields=[*changed, "updated_at"])
            _write_audit(organization, changed, superuser_override=superuser_override, audit=audit)
    return _profile_from(organization)


def list_administrable_organizations(actor: User) -> list[OrganizationProfile]:
    """Return the organizations ``actor`` may administer, as profile projections.

    Authority-owned discovery (ADR-048): a Django superuser sees every
    organization; every other actor sees only the organizations for which they
    hold an ``admin`` OrganizationMembership. This never uses workspace
    reachability (ADR-046-R11 context is advisory, not authority), so an actor is
    offered exactly the organizations they can actually edit and no others.
    Ordered by name for a deterministic list; an actor with none receives an
    empty list.
    """
    if getattr(actor, "id", None) is None:
        return []
    if getattr(actor, "is_superuser", False):
        organizations = Organization.objects.all()
    else:
        admin_org_ids = OrganizationMembership.objects.filter(
            user=actor,
            role=OrganizationRole.ADMIN.value,
        ).values_list("organization_id", flat=True)
        organizations = Organization.objects.filter(id__in=admin_org_ids)
    return [_profile_from(organization) for organization in organizations.order_by("name", "id")]
