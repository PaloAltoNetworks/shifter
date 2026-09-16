"""Read-only current-principal workspace context projection (ADR-046-R11, #1938).

The organization/workspace admin console shell needs the caller's *existing*
workspace memberships -- their organization, workspace, role, and the operations
that role permits -- as a side-effect-free read. This is a projection over rows
the caller already holds; it creates no organization, workspace, membership,
primary organization, organization-wide role, or persisted current-workspace,
and it never repairs tenancy state (it never calls
:func:`resolve_personal_workspace`). A caller with no membership gets an empty
list. Capabilities are derived centrally from the role-to-operation policy in
:mod:`workspaces.roles`, so no consumer re-derives authority from a role code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from workspaces.models import WorkspaceMembership
from workspaces.roles import WorkspaceOperation, role_permits

if TYPE_CHECKING:
    from django.contrib.auth.models import User


@dataclass(frozen=True, slots=True)
class OrganizationRef:
    """Immutable public organization projection (scalars only)."""

    uuid: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class ActorWorkspaceContext:
    """One workspace the actor belongs to, with role and permitted operations.

    Carries scalars and public UUIDs only. ``role`` is display data, not
    authorization; ``capabilities`` are advisory presentation hints derived from
    the central policy, and every resource endpoint still reauthorizes the
    operation it performs.
    """

    organization: OrganizationRef
    workspace_uuid: uuid.UUID
    workspace_name: str
    is_personal: bool
    role: str
    capabilities: tuple[str, ...]


def _capabilities_for_role(role: str) -> tuple[str, ...]:
    """Return the workspace-operation codes ``role`` permits, in declaration order.

    Derived from the single role-to-operation policy so no caller re-derives
    authority from a role string. Fail-closed: an unknown role yields no
    capabilities.
    """
    return tuple(operation for operation in WorkspaceOperation.values if role_permits(role, operation))


def list_actor_workspace_contexts(actor: User) -> list[ActorWorkspaceContext]:
    """Return ``actor``'s workspace memberships as read-only context projections.

    One bounded query with ``select_related`` over the workspace and its
    organization (no N+1 authorization). Side-effect free: it reads existing
    rows only and never creates or repairs tenancy state, so a staff caller with
    no membership receives an empty list rather than a manufactured personal
    workspace. Ordered by organization name, then workspace name, for a
    deterministic switcher order.
    """
    if getattr(actor, "id", None) is None:
        return []
    memberships = (
        WorkspaceMembership.objects.filter(user=actor)
        .select_related("workspace", "workspace__organization")
        .order_by("workspace__organization__name", "workspace__name", "workspace_id")
    )
    return [
        ActorWorkspaceContext(
            organization=OrganizationRef(
                uuid=membership.workspace.organization.uuid,
                name=membership.workspace.organization.name,
            ),
            workspace_uuid=membership.workspace.uuid,
            workspace_name=membership.workspace.name,
            is_personal=membership.workspace.personal_for_user_id is not None,
            role=membership.role,
            capabilities=_capabilities_for_role(membership.role),
        )
        for membership in memberships
    ]
