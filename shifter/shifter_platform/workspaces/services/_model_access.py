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
        raise error("Workspace access denied") from exc


def resolve_model_access_workspace(actor: User, workspace_uuid: str | uuid.UUID) -> ModelAccessWorkspaceScope:
    """Lock and authorize an active workspace by its immutable public UUID."""
    parsed = _parse_uuid(workspace_uuid, WorkspaceAuthorizationError)
    with transaction.atomic():
        workspace = Workspace.objects.select_for_update().filter(uuid=parsed).first()
        if workspace is None or workspace.archived_at is not None:
            raise WorkspaceAuthorizationError("Workspace access denied")
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
