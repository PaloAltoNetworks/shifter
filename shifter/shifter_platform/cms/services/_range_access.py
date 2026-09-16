"""Workspace-authorized facades for interactive range instance access."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError

from cms.exceptions import CMSError
from cms.models import Instance, Request
from shared.remote_access import TerminalConnection
from workspaces.services import WorkspaceOperation

from ._range_workspace import authorize_range_workspace

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from shared.remote_access import TerminalConnectionFactory

_INSTANCE_NOT_FOUND = "Instance not found"


def _owned_request_id(user: User, instance_uuid: str) -> int | None:
    """Return the request id owning ``instance_uuid``, across both registries.

    Interactive access spans two instance registries and must consult both:

    * realized **range** instances are rows of ``engine.models.Instance``,
      written by the engine interpreter during provisioning, and are reachable
      only through ``engine.services`` (ADR-001);
    * **NGFW** instances are rows of this layer's own ``Instance`` model,
      written by ``cms.services._ngfw_provisioning``.

    Consulting only the CMS table (the original behavior) matched nothing for a
    range instance, so every range terminal/RDP/SSH open failed closed with
    "Instance not found". Consulting only the engine table would break NGFW
    access the same way. Ownership is enforced in both branches.
    """
    from engine.services import get_owned_instance_request_ref

    request_ref = get_owned_instance_request_ref(user, instance_uuid)
    if request_ref is not None:
        # Join on the shared ``request_id`` UUID: engine and CMS keep separate
        # request tables whose primary keys are not a contract.
        return Request.objects.filter(request_id=request_ref).values_list("id", flat=True).first()
    ngfw_instance = (
        Instance.objects.filter(pk=instance_uuid, request__user_id=getattr(user, "id", None))
        .values_list("request_id", flat=True)
        .first()
    )
    return ngfw_instance


def _authorize_instance_access(user: User, instance_uuid: str) -> None:
    """Enforce ownership and the persisted request workspace binding.

    Ownership resolves through ``engine.services`` rather than ``cms.models``:
    realized range instances are rows of ``engine.models.Instance``, while the
    CMS ``Instance`` table is written only by NGFW provisioning. Resolving the
    owner here against the CMS table matched nothing for a range instance, so
    every terminal/RDP/SSH open failed with "Instance not found" (the workspace
    check below was never reached). The engine seam enforces the ownership half;
    the workspace binding is read from this layer's own ``Request`` row, which is
    where ``workspace_id`` is recorded.
    """
    try:
        request_id = _owned_request_id(user, instance_uuid)
    except (ValidationError, ValueError) as exc:
        raise ValueError(_INSTANCE_NOT_FOUND) from exc
    if request_id is None:
        raise ValueError(_INSTANCE_NOT_FOUND)
    workspace_id = Request.objects.filter(pk=request_id).values_list("workspace_id", flat=True).first()
    try:
        authorize_range_workspace(user, workspace_id, WorkspaceOperation.ACCESS_RANGE)
    except CMSError as exc:
        raise PermissionError(_INSTANCE_NOT_FOUND) from exc


def connect_range_terminal(
    user: User,
    instance_uuid: str,
    *,
    connection_factory: TerminalConnectionFactory | None = None,
) -> TerminalConnection:
    """Open an Engine terminal only after workspace authorization succeeds.

    ``connection_factory`` is carried through to ``engine.services`` so a
    consumer test can substitute a fake terminal transport without bypassing
    this workspace authorization layer or Engine's runtime authorization
    (issue #993). Production leaves it ``None`` (a real SSH connection).
    """
    from engine.services import connect_terminal

    _authorize_instance_access(user, instance_uuid)
    return connect_terminal(user, instance_uuid, connection_factory=connection_factory)


def get_range_rdp_connection_info(user: User, instance_uuid: str) -> dict[str, Any]:
    """Resolve RDP data only after workspace authorization succeeds."""
    from engine.services import get_rdp_connection_info

    _authorize_instance_access(user, instance_uuid)
    return get_rdp_connection_info(user, instance_uuid)


def get_range_ssh_connection_info(user: User, instance_uuid: str) -> dict[str, Any]:
    """Resolve SSH data only after workspace authorization succeeds."""
    from engine.services import get_ssh_connection_info

    _authorize_instance_access(user, instance_uuid)
    return get_ssh_connection_info(user, instance_uuid)
