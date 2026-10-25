"""Tenancy-owned model-access selector and publisher scopes (PLAT-202 M20)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from shared.model_access import AuthorityInvalidation, AuthorityState, OwnedReference
from shared.model_access.authority_port import invalidate_authority
from workspaces.models import Organization, Workspace
from workspaces.roles import WorkspaceOperation
from workspaces.services._authorization import WorkspaceAuthorizationError, authorize_bound_workspace
from workspaces.services._organization import (
    OrganizationAuthorizationError,
    resolve_administrable_organization,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from workspaces.services._authorization import WorkspaceAuthorization


WORKSPACE_ACCESS_DENIED = "Workspace access denied"


@dataclass(frozen=True, slots=True)
class ModelAccessWorkspaceScope:
    """Scalar-only workspace selector and publisher-authority source."""

    workspace_id: int
    workspace_uuid: uuid.UUID
    authority_reference: str
    containment_reference: str


@dataclass(frozen=True, slots=True)
class ModelAccessOrganizationScope:
    """Scalar-only organization selector and its active workspace containment."""

    organization_id: int
    organization_uuid: uuid.UUID
    workspace_ids: tuple[int, ...]
    authority_reference: str


def invalidate_workspace_model_access(
    workspace: Workspace,
    *,
    reason: str,
    include_organization: bool = False,
) -> int:
    """Advance workspace publisher authority and optional organization containment."""
    references = [
        OwnedReference(owner="workspaces", reference=f"workspace:{workspace.uuid}"),
        OwnedReference(owner="workspaces", reference=f"workspace-id:{workspace.pk}"),
    ]
    if include_organization:
        references.append(
            OwnedReference(
                owner="workspaces",
                reference=f"organization:{workspace.organization.uuid}",
            )
        )
    return invalidate_authority(
        AuthorityInvalidation(
            deployment_id=None,
            authority_refs=tuple(references),
            state=AuthorityState.UNKNOWN,
            reason=reason,
        )
    )


def _parse_uuid(value: str | uuid.UUID, error: type[Exception]) -> uuid.UUID:
    """Parse a public UUID while preserving the owner service's opaque error."""
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise error(WORKSPACE_ACCESS_DENIED) from exc


def resolve_model_access_workspace(actor: User, workspace_uuid: str | uuid.UUID) -> ModelAccessWorkspaceScope:
    """Lock and authorize an active workspace by its immutable public UUID."""
    parsed = _parse_uuid(workspace_uuid, WorkspaceAuthorizationError)
    with transaction.atomic():
        workspace = Workspace.objects.select_for_update().filter(uuid=parsed).first()
        if workspace is None or workspace.archived_at is not None:
            raise WorkspaceAuthorizationError(WORKSPACE_ACCESS_DENIED)
        authorize_bound_workspace(actor, workspace.pk, WorkspaceOperation.PUBLISH_MODEL_ACCESS)
        return ModelAccessWorkspaceScope(
            workspace_id=workspace.pk,
            workspace_uuid=workspace.uuid,
            authority_reference=f"workspace:{workspace.uuid}",
            containment_reference=f"workspace-id:{workspace.pk}",
        )


def resolve_model_access_organization(actor: User, organization_uuid: str | uuid.UUID) -> ModelAccessOrganizationScope:
    """Lock an administrable organization and return active workspace containment."""
    parsed = _parse_uuid(organization_uuid, OrganizationAuthorizationError)
    with transaction.atomic():
        authorized, _override = resolve_administrable_organization(actor, parsed)
        organization = Organization.objects.select_for_update().get(pk=authorized.pk)
        workspace_ids = tuple(
            Workspace.objects.select_for_update()
            .filter(organization=organization, archived_at__isnull=True)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        return ModelAccessOrganizationScope(
            organization_id=organization.pk,
            organization_uuid=organization.uuid,
            workspace_ids=workspace_ids,
            authority_reference=f"organization:{organization.uuid}",
        )


def authorize_model_source_workspace(
    actor: User, *, workspace_id: int | None = None, workspace_uuid: str | uuid.UUID | None = None
) -> WorkspaceAuthorization:
    """Authorize model-source administration through tenant or workspace authority.

    This narrow operation grants no range access or other workspace capability.
    Organization administrators need no synthetic workspace membership.
    """
    from django.contrib.auth.models import User

    from workspaces.services._authorization import WorkspaceAuthorization

    current_actor = User.objects.filter(pk=actor.pk, is_active=True).first()
    if current_actor is None:
        raise WorkspaceAuthorizationError(WORKSPACE_ACCESS_DENIED)
    actor = current_actor
    query = Workspace.objects.select_related("organization").filter(archived_at__isnull=True)
    if workspace_uuid is not None:
        query = query.filter(uuid=_parse_uuid(workspace_uuid, WorkspaceAuthorizationError))
    elif workspace_id is not None:
        query = query.filter(pk=workspace_id)
    else:
        raise WorkspaceAuthorizationError(WORKSPACE_ACCESS_DENIED)
    workspace = query.first()
    if workspace is None:
        raise WorkspaceAuthorizationError(WORKSPACE_ACCESS_DENIED)
    try:
        resolve_administrable_organization(actor, workspace.organization.uuid)
    except OrganizationAuthorizationError:
        return authorize_bound_workspace(actor, workspace.pk, WorkspaceOperation.PUBLISH_MODEL_ACCESS)
    return WorkspaceAuthorization(
        workspace_id=workspace.pk,
        workspace_uuid=workspace.uuid,
        organization_id=workspace.organization_id,
        organization_uuid=workspace.organization.uuid,
        role="admin",
    )


def list_model_source_users(
    actor: User, organization_uuid: uuid.UUID, *, search: str = "", page: int = 1
) -> dict[str, object]:
    """Tenant-admin directory for explicit source-use grants, with bounded paging."""
    from django.contrib.auth.models import User
    from django.db.models import Q

    from workspaces.models import OrganizationMembership, WorkspaceMembership

    current_actor = User.objects.filter(pk=actor.pk, is_active=True).first()
    if current_actor is None:
        raise OrganizationAuthorizationError("Organization access denied")
    actor = current_actor
    organization, _override = resolve_administrable_organization(actor, organization_uuid)
    members = WorkspaceMembership.objects.filter(
        workspace__organization=organization, workspace__archived_at__isnull=True
    ).values_list("user_id", flat=True)
    admins = OrganizationMembership.objects.filter(organization=organization).values_list("user_id", flat=True)
    users = User.objects.filter(Q(pk__in=members) | Q(pk__in=admins), is_active=True)
    if search:
        users = users.filter(
            Q(username__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search)
        )
    users = users.order_by("username", "pk")
    count = users.count()
    return {
        "has_next": page * 25 < count,
        "results": [
            {"id": user.pk, "name": user.get_full_name() or user.username, "username": user.username}
            for user in users[(page - 1) * 25 : page * 25]
        ],
    }
