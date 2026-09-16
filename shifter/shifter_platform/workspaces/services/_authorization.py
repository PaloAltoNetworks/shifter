"""Workspace authorization seam (ADR-046).

One service resolves an actor, a workspace identity, and a requested operation
into an immutable authorization result or a classified denial. #1326 extends
the role-to-operation policy behind this seam and #1327 makes queries and
admission workspace-aware, neither of which requires a caller to import a
workspaces model or to re-derive permissions from a role code.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from workspaces.models import Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole, operation_requires_active_workspace, role_permits

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

# One message for every denial. Callers, log lines, and API responses must not
# be able to tell "this workspace does not exist" from "you are not a member of
# it" -- that difference is a tenant-enumeration oracle.
_DENIED_MESSAGE = "Workspace access denied"


class WorkspaceAuthorizationError(Exception):
    """Raised when an actor may not perform an operation in a workspace."""


@dataclass(frozen=True, slots=True)
class WorkspaceAuthorization:
    """Immutable proof that an actor may act in a workspace.

    Carries scalars only. Handing another layer an ORM instance would let it
    mutate tenancy state outside this domain and would defeat the boundary the
    scalar ``workspace_id`` bindings exist to preserve.
    """

    workspace_id: int
    workspace_uuid: uuid.UUID
    organization_id: int
    role: str


def _deny(reason: str, **context: object) -> WorkspaceAuthorizationError:
    """Log a denial with low-cardinality context and build the opaque error."""
    logger.info("workspace authorization denied: reason=%s context=%s", reason, context)
    return WorkspaceAuthorizationError(_DENIED_MESSAGE)


def _authorization_from(membership: WorkspaceMembership) -> WorkspaceAuthorization:
    """Project a membership row onto the immutable result."""
    return WorkspaceAuthorization(
        workspace_id=membership.workspace_id,
        workspace_uuid=membership.workspace.uuid,
        organization_id=membership.workspace.organization_id,
        role=membership.role,
    )


def _operation_value(operation: object) -> str:
    """Normalize an operation enum member or raw code to its string value."""
    return str(getattr(operation, "value", operation))


def _check_operation(role: str, operation: object) -> None:
    """Raise unless ``role`` permits ``operation``."""
    operation_code = _operation_value(operation)
    if not role_permits(role, operation_code):
        raise _deny("operation_not_permitted", operation=operation_code, role=role)


def _check_active_workspace(membership: WorkspaceMembership, operation: object) -> None:
    """Raise when ``operation`` requires an active workspace but it is archived.

    Scoped to the active-workspace operation set (ADR-051): existing operations
    keep their prior behavior, so this cannot silently change unrelated callers.
    The denial is the same opaque message as every other, so an archived
    workspace is not distinguishable from a missing one or a role gap.
    """
    operation_code = _operation_value(operation)
    if operation_requires_active_workspace(operation_code) and membership.workspace.archived_at is not None:
        raise _deny("workspace_archived", operation=operation_code)


def authorize_workspace(
    actor: User,
    workspace_uuid: str | uuid.UUID,
    operation: object,
) -> WorkspaceAuthorization:
    """Authorize ``actor`` for ``operation`` in the workspace with ``workspace_uuid``.

    This is the entry point for anything that accepts a workspace identity from
    outside the platform: public surfaces address workspaces by UUID only, so a
    caller cannot probe internal primary keys. A malformed UUID is a denial, not
    a ``ValueError``, so a bad input cannot be distinguished from a workspace
    the actor may not see.

    Raises:
        WorkspaceAuthorizationError: The workspace does not exist, the actor
            holds no membership in it, or the actor's role does not permit the
            operation. All three raise the same message by design.
    """
    try:
        parsed = workspace_uuid if isinstance(workspace_uuid, uuid.UUID) else uuid.UUID(str(workspace_uuid))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _deny("malformed_workspace_uuid") from exc

    membership = (
        WorkspaceMembership.objects.select_related("workspace").filter(workspace__uuid=parsed, user=actor).first()
    )
    if membership is None:
        raise _deny("no_membership")
    _check_operation(membership.role, operation)
    _check_active_workspace(membership, operation)
    return _authorization_from(membership)


def authorize_bound_workspace(
    actor: User,
    workspace_id: int | None,
    operation: object,
) -> WorkspaceAuthorization:
    """Authorize ``actor`` against an already-persisted internal ``workspace_id``.

    ``workspace_id`` must come from a trusted persisted binding -- the
    ``workspace_id`` column on a CMS request/range projection or an Engine range
    -- never from a request body, path, or query parameter. Untrusted input goes
    through :func:`authorize_workspace` and its public UUID.

    A ``None`` binding (a legacy row predating #1325) is denied rather than
    treated as "any workspace": an unbound range is out of workspace scope, not
    implicitly in every scope.

    Raises:
        WorkspaceAuthorizationError: The binding is absent or unknown, the actor
            holds no membership, or the role does not permit the operation.
    """
    if workspace_id is None:
        raise _deny("unbound_workspace")

    membership = (
        WorkspaceMembership.objects.select_related("workspace").filter(workspace_id=workspace_id, user=actor).first()
    )
    if membership is None:
        raise _deny("no_membership")
    _check_operation(membership.role, operation)
    _check_active_workspace(membership, operation)
    return _authorization_from(membership)


def authorize_launch_workspace_locked(
    actor: User,
    workspace_id: int | None,
    operation: object,
) -> WorkspaceAuthorization:
    """Authorize a launch against a bound ``workspace_id`` under the workspace mutex.

    Identical in outcome to :func:`authorize_bound_workspace`, but it first takes
    ``SELECT ... FOR UPDATE`` on the workspace row -- the same row mutation
    commands lock in :func:`workspaces.services._memberships._lock_workspace_and_actor`
    -- before reading the membership. A concurrent removal therefore either has
    already committed (and this read denies) or blocks behind this lock until the
    launch's enclosing transaction commits.

    It MUST run inside a ``transaction.atomic()`` block: the row lock is held
    until that transaction commits, so a caller that reserves the range in the
    same transaction (ADR-046-R9) cannot have the membership revoked underneath
    it after this check. A ``None`` binding is denied, never treated as "any
    workspace".

    Raises:
        WorkspaceAuthorizationError: The binding is absent or unknown, the actor
            holds no membership, or the role does not permit the operation.
    """
    if workspace_id is None:
        raise _deny("unbound_workspace")

    if Workspace.objects.select_for_update().filter(pk=workspace_id).first() is None:
        raise _deny("unknown_workspace")
    membership = (
        WorkspaceMembership.objects.select_related("workspace").filter(workspace_id=workspace_id, user=actor).first()
    )
    if membership is None:
        raise _deny("no_membership")
    _check_operation(membership.role, operation)
    _check_active_workspace(membership, operation)
    return _authorization_from(membership)


def authorized_workspace_ids(actor: User, operation: object) -> tuple[int, ...]:
    """Return persisted workspace IDs where ``actor`` may perform ``operation``.

    This is the query-side companion to :func:`authorize_bound_workspace`.
    Callers use it to omit inaccessible tenant-bound rows from collection
    surfaces without importing workspace models or role policy.
    """
    operation_code = _operation_value(operation)
    permitted_roles = tuple(role for role in WorkspaceRole.values if role_permits(role, operation_code))
    if not permitted_roles or getattr(actor, "id", None) is None:
        return ()
    return tuple(
        WorkspaceMembership.objects.filter(user=actor, role__in=permitted_roles)
        .order_by("workspace_id")
        .values_list("workspace_id", flat=True)
    )
