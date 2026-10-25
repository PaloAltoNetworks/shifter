"""Range-to-workspace scope administration authorization (PLAT-237, #1944).

The tenancy domain owns the authority decision for moving a range's workspace
scope. CMS derives the persisted source scope from the range projection and
supplies the requested target as a public UUID; this seam decides whether the
actor may make the move and returns trusted scalars, never an ORM object
(ADR-046-R1/R8).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from shared.authorization import AuthorizationProvider, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef, ResourceScope
from workspaces.models import Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceOperation

from ._account import AccountScopeError, hierarchy_target_scope
from ._account_policy_admin import _require_action
from ._account_policy_lifecycle import _scope_for_lifecycle
from ._authorization import _deny, authorize_bound_workspace

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RangeRebindAuthorization:
    """Immutable proof that an actor may move a range between two workspace scopes.

    Scalars only: the CMS caller receives trusted internal ids and the parsed
    target UUID, never a workspace ORM instance.
    """

    source_workspace_id: int
    target_workspace_id: int
    target_workspace_uuid: uuid.UUID
    is_same_scope: bool


@dataclass(frozen=True, slots=True)
class PolicyRangeRebindAuthorization:
    """Immutable exact source/destination proof; SQL state is rechecked under lock."""

    source_workspace_id: int
    target_workspace_id: int
    source_scope: ResourceScope
    target_scope: ResourceScope
    owner: PrincipalRef
    source_account_id: int
    source_organization_id: int


def authorize_policy_range_rebind(
    actor: CredentialContext,
    provider: AuthorizationProvider,
    source_workspace_id: int,
    target_workspace_uuid: UUID,
    owner: PrincipalRef,
) -> PolicyRangeRebindAuthorization:
    """Check the registered action in both scopes before opening SQL locks."""
    source = Workspace.objects.filter(pk=source_workspace_id).first()
    destination = Workspace.objects.filter(uuid=target_workspace_uuid, archived_at__isnull=True).first()
    if source is None or destination is None:
        raise _deny("unknown_workspace")
    try:
        source_scope = _scope_for_lifecycle(source.uuid, restore=True)
        target_scope = hierarchy_target_scope("workspace", destination.uuid)
        for row, scope in ((source, source_scope), (destination, target_scope)):
            _require_action(actor, provider, "workspace.manage_range_scope", TargetRef("workspace", row.uuid), scope)
    except AccountScopeError as exc:
        raise _deny("scope_denied") from exc
    if source.organization.account_id is None:
        raise _deny("scope_denied")
    return PolicyRangeRebindAuthorization(
        source.pk,
        destination.pk,
        source_scope,
        target_scope,
        owner,
        source.organization.account_id,
        source.organization_id,
    )


def lock_policy_range_rebind(proof: PolicyRangeRebindAuthorization) -> tuple[int, int]:
    """Recheck both ancestry projections and destination membership under ordered locks."""
    ids = sorted({proof.source_workspace_id, proof.target_workspace_id})
    rows = {
        row.pk: row
        for row in Workspace.objects.select_related("organization__account")
        .select_for_update(of=("self",))
        .filter(pk__in=ids)
        .order_by("pk")
    }
    for workspace_id, scope in (
        (proof.source_workspace_id, proof.source_scope),
        (proof.target_workspace_id, proof.target_scope),
    ):
        row = rows.get(workspace_id)
        if row is None or row.organization.account is None:
            raise _deny("unknown_workspace")
        actual = ResourceScope("account", row.organization.account.uuid, row.organization.uuid, row.uuid)
        if actual != scope:
            raise _deny("scope_changed")
    destination = rows[proof.target_workspace_id]
    if (
        destination.archived_at is not None
        or not WorkspaceMembership.objects.filter(workspace=destination, principal_uuid=proof.owner.uuid).exists()
    ):
        raise _deny("owner_not_in_target")
    return proof.source_workspace_id, proof.target_workspace_id


def authorize_range_rebind(
    actor: User,
    *,
    source_workspace_id: int,
    target_workspace_uuid: str | uuid.UUID,
    range_owner_id: int,
) -> RangeRebindAuthorization:
    """Authorize a range workspace move under both workspace mutexes (ADR-046-R14).

    The move requires ``REBIND_RANGE_WORKSPACE`` authority in BOTH the persisted
    source scope and the requested target scope, rechecked under each workspace's
    row mutex, plus a live membership for the unchanged range owner in the target
    so the range stays reachable by its owner after the move. The target must be
    active; the source may be archived so an administrator can evacuate its
    bindings. Every failure -- malformed or unknown target, missing authority in
    either scope, an archived target, or an absent owner membership -- raises the
    same opaque :class:`WorkspaceAuthorizationError` so the surface never becomes
    a tenant-enumeration oracle.

    ``source_workspace_id`` and ``range_owner_id`` MUST come from a trusted
    persisted range projection, never from untrusted input; the target arrives as
    a public UUID. Must run inside a ``transaction.atomic()`` block: the workspace
    row locks are held until the caller's transaction commits so authority cannot
    be revoked underneath the move.

    Raises:
        WorkspaceAuthorizationError: For every denial class above.
    """
    try:
        parsed_target = (
            target_workspace_uuid
            if isinstance(target_workspace_uuid, uuid.UUID)
            else uuid.UUID(str(target_workspace_uuid))
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise _deny("malformed_workspace_uuid") from exc

    target_id = Workspace.objects.filter(uuid=parsed_target).values_list("id", flat=True).first()
    if target_id is None:
        raise _deny("unknown_workspace")

    # Lock both workspace rows in deterministic id order so a concurrent move in
    # the opposite direction cannot deadlock, and so membership mutation (which
    # locks the same rows) serializes behind this move.
    lock_ids = sorted({source_workspace_id, target_id})
    locked = {
        workspace.id: workspace
        for workspace in Workspace.objects.select_for_update().filter(pk__in=lock_ids).order_by("pk")
    }
    if source_workspace_id not in locked or target_id not in locked:
        raise _deny("unknown_workspace")

    # Actor authority in both scopes, rechecked under the locks.
    authorize_bound_workspace(actor, source_workspace_id, WorkspaceOperation.REBIND_RANGE_WORKSPACE)
    authorize_bound_workspace(actor, target_id, WorkspaceOperation.REBIND_RANGE_WORKSPACE)

    same_scope = source_workspace_id == target_id
    if not same_scope:
        if locked[target_id].archived_at is not None:
            raise _deny("archived_target")
        if not WorkspaceMembership.objects.filter(workspace_id=target_id, user_id=range_owner_id).exists():
            raise _deny("owner_not_in_target")

    return RangeRebindAuthorization(
        source_workspace_id=source_workspace_id,
        target_workspace_id=target_id,
        target_workspace_uuid=parsed_target,
        is_same_scope=same_scope,
    )


def authorize_policy_range_scope_listing(
    actor: CredentialContext, provider: AuthorizationProvider, workspace_uuid: UUID
) -> int:
    """Administrative scope inspection includes archived sources for safe evacuation."""
    scope = _scope_for_lifecycle(workspace_uuid, restore=True)
    _require_action(actor, provider, "workspace.manage_range_scope", TargetRef("workspace", workspace_uuid), scope)
    return Workspace.objects.get(uuid=workspace_uuid).pk
