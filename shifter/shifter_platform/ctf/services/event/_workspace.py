"""Resolve the immutable workspace scope for a new CTF event (ADR-051, #2048).

Split from ``_crud`` for the python:S104 file-size budget. CTF reaches tenancy
only through the public ``workspaces.services`` facade -- the one sanctioned CTF
-> workspaces edge -- never a workspace model or cross-layer foreign key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import workspaces.services as workspace_services
from ctf.exceptions import CTFValidationError

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def resolve_event_workspace_id(user: User, event_data: dict[str, Any]) -> int:
    """Resolve the immutable workspace scope for a new event (ADR-051, #2048).

    An explicit public ``workspace`` UUID is authorized through the tenancy seam
    for the ``USE_CTF_COMMUNICATIONS`` membership operation (which proves the
    creator belongs to the workspace and refuses an archived one); this never
    grants CTF event or recipient authority. Omitting it uses the creator's
    personal compatibility workspace.
    """
    workspace_uuid = event_data.get("workspace")
    if workspace_uuid:
        try:
            authorization = workspace_services.authorize_workspace(
                user, workspace_uuid, workspace_services.WorkspaceOperation.USE_CTF_COMMUNICATIONS
            )
        except workspace_services.WorkspaceAuthorizationError:
            raise CTFValidationError(
                "Workspace is not available for CTF event creation.",
                code="CTF_WORKSPACE_NOT_AVAILABLE",
            ) from None
        return authorization.workspace_id
    return workspace_services.resolve_personal_workspace(user).workspace_id
