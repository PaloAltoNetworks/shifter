"""Workspace scope resolution for the CMS launch boundary (#1325, ADR-046-R3).

One place decides which workspace a launch belongs to. The RAES launch boundary
calls this so scope is never resolved in a view, serializer, or provisioner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cms.exceptions import CMSError, WorkspaceLaunchDenied
from workspaces.services import WorkspaceOperation

if TYPE_CHECKING:
    import uuid

    from django.contrib.auth.models import User

    from shared.enums import RangeSource
    from shared.range_instantiation_policy import InstantiationPurpose

logger = logging.getLogger(__name__)

# One opaque, non-enumerating message for a launch scope the actor may not use.
# It must not distinguish "no such workspace" from "you are not a member" from
# "your role does not permit launching" -- that difference is a tenant oracle.
_LAUNCH_SCOPE_DENIED = "Selected workspace is not available"


def resolve_launch_workspace(user: User, workspace_uuid: str | uuid.UUID | None = None) -> int:
    """Resolve and authorize the workspace scope a launch by ``user`` belongs to.

    ``workspace_uuid`` is the optional public workspace selection from the launch
    command (ADR-046-R9). Omission resolves the launcher's personal compatibility
    workspace, which preserves current single-user behavior exactly. A supplied
    UUID is authorized for ``LAUNCH_RANGE`` through the public-identity workspace
    seam; a malformed, unknown, unauthorized, or non-member value is denied with
    one opaque message and never silently falls back to the personal workspace.

    Internal workspace integers are never accepted here: the trusted internal
    ``workspace_id`` is only ever produced by the workspaces service, so an HTTP
    caller cannot select a workspace it may not see (ADR-046-R9).

    The RAES launch boundary calls this, so scope is never resolved in a view,
    serializer, provisioner, or CTF bridge. The returned scalar is reauthorized
    under the workspace mutex at reservation time by
    :func:`reauthorize_launch_workspace_locked`.
    """
    from workspaces.services import (
        WorkspaceAuthorizationError,
        authorize_bound_workspace,
        authorize_workspace,
        resolve_personal_workspace,
    )

    if workspace_uuid is None:
        workspace_id = resolve_personal_workspace(user).workspace_id
        authorize_bound_workspace(user, workspace_id, WorkspaceOperation.LAUNCH_RANGE)
        return workspace_id

    try:
        authorization = authorize_workspace(user, workspace_uuid, WorkspaceOperation.LAUNCH_RANGE)
    except WorkspaceAuthorizationError as exc:
        raise WorkspaceLaunchDenied(_LAUNCH_SCOPE_DENIED) from exc
    return authorization.workspace_id


def reauthorize_launch_workspace_locked(user: User, workspace_id: int) -> None:
    """Reauthorize a resolved launch scope under the workspace mutex (ADR-046-R9).

    Called inside the atomic CMS request/range reservation so the workspace row
    lock is held across the insert. This closes the membership-removal TOCTOU: a
    concurrent removal cannot commit between the first authorization in
    :func:`resolve_launch_workspace` and the range insert without this locked
    re-check denying the launch.
    """
    from workspaces.services import WorkspaceAuthorizationError, authorize_launch_workspace_locked

    try:
        authorize_launch_workspace_locked(user, workspace_id, WorkspaceOperation.LAUNCH_RANGE)
    except WorkspaceAuthorizationError as exc:
        raise WorkspaceLaunchDenied(_LAUNCH_SCOPE_DENIED) from exc


def resolve_effective_egress_mode(workspace_id: int) -> str:
    """Resolve the effective range egress mode for a launch scope (PLAT-238, ADR-017-R5).

    Combines the workspace's stored selector with the deployment baseline into one
    closed :class:`~installation.range_egress.RangeEgressMode` value to pin on the
    Engine range:

    * A workspace selecting ``none`` is an explicit zero-egress override -> ``none``.
    * A workspace selecting ``status-quo`` inherits the deployment baseline; the
      provider realizes the baseline exactly as it does today. (The concrete
      baseline mode is bound into CMS by the configuration layer; until then
      ``status-quo`` is carried through verbatim and the provider applies the
      deployment baseline, so a deployment-wide ``none`` still reaches a
      ``status-quo`` workspace's ranges.)

    An empty allowlist, a false feature flag, or a missing provider resource is
    never interpreted as zero egress (preflight gotcha): only an explicit ``none``
    selection resolves to ``none`` here.
    """
    from installation.range_egress import RangeEgressMode

    from workspaces.services import workspace_egress_policy

    selector = workspace_egress_policy(workspace_id)
    if selector == RangeEgressMode.NONE.value:
        return RangeEgressMode.NONE.value
    return RangeEgressMode.STATUS_QUO.value


@dataclass(frozen=True, slots=True)
class WorkspaceLaunchAdmission:
    """The bounded verdict returned by the one workspace launch-admission seam.

    Scalars only. ``correlation_key`` is the stable per-launch request/draw key a
    future durable per-workspace quota would key its idempotent reservation on;
    the initial policy carries it without consuming it. ``effective_egress_mode``
    is the preliminary workspace egress decision (PLAT-238); the authoritative
    value is re-resolved under the workspace mutex in
    :func:`resolve_effective_egress_mode_locked` at reservation time, because the
    pre-reservation admission read is racy (a concurrent policy change could land
    between admission and reservation).
    """

    workspace_id: int
    correlation_key: str
    effective_egress_mode: str
    admitted: bool = True


def resolve_effective_egress_mode_locked(workspace_id: int) -> str:
    """Authoritatively resolve the effective egress mode under the workspace mutex.

    Called inside the atomic CMS reservation while the workspace row lock is held
    (alongside :func:`reauthorize_launch_workspace_locked`), so the pinned decision
    reflects the policy as of the reservation, not a stale pre-reservation read. The
    resolution logic is identical to :func:`resolve_effective_egress_mode`; the
    distinction is purely that this call happens under the lock and its result is
    the value pinned on the Engine range and delivered to the provisioner.
    """
    return resolve_effective_egress_mode(workspace_id)


def admit_workspace_launch(
    *,
    workspace_id: int,
    user: User,
    range_source: RangeSource,
    instantiation_purpose: InstantiationPurpose,
    correlation_key: str | uuid.UUID,
) -> WorkspaceLaunchAdmission:
    """The single CMS pre-reservation workspace launch-admission seam (ADR-046-R10).

    Both creation families and every product caller pass through here after the
    actor, workspace, backend, source, purpose, and scenario inputs are validated
    but before CMS reservation, Engine persistence, or cloud dispatch, so a future
    durable per-workspace quota or an effective workspace egress policy attaches in
    one place without duplicating either create path.

    The initial policy admits with no additional workspace limit, but it returns
    one bounded decision at this point; callers must not reproduce a quota or
    policy check elsewhere. A future enforcing quota keys a durable, idempotent
    reservation on ``(workspace_id, correlation_key)`` -- distinct from Engine's
    physical event/provider-capacity ledger and from ``RangeInstance``'s
    ``(user_id, range_source)`` active-range constraint, neither of which this
    seam changes.
    """
    logger.debug(
        "admit_workspace_launch: workspace_id=%s user_id=%s range_source=%s purpose=%s",
        workspace_id,
        getattr(user, "id", None),
        range_source.value,
        instantiation_purpose.value,
    )
    return WorkspaceLaunchAdmission(
        workspace_id=workspace_id,
        correlation_key=str(correlation_key),
        effective_egress_mode=resolve_effective_egress_mode(workspace_id),
        admitted=True,
    )


def authorize_range_workspace(
    user: User,
    workspace_id: int | None,
    operation: WorkspaceOperation,
) -> None:
    """Authorize an interactive operation against a persisted range binding."""
    from workspaces.services import WorkspaceAuthorizationError, authorize_bound_workspace

    try:
        authorize_bound_workspace(user, workspace_id, operation)
    except WorkspaceAuthorizationError as exc:
        raise CMSError("Range not found") from exc


def authorized_range_workspace_ids(
    user: User,
    operation: WorkspaceOperation,
) -> tuple[int, ...]:
    """Return workspace bindings visible to ``user`` for a collection query."""
    from workspaces.services import authorized_workspace_ids

    return authorized_workspace_ids(user, operation)
