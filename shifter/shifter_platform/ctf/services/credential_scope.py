"""CTF-owned event ancestry projection for credential authority checks."""

from uuid import UUID

from ctf.models import CTFEvent
from shared.identity_scope import ResourceScope
from workspaces.services import event_placement_scope, resource_scope_from_ids

_SCOPE_UNAVAILABLE = "Credential scope unavailable"


def event_credential_scope(event_uuid: UUID) -> ResourceScope:
    """Return validated SQL ancestry, never an absent-scope installation default."""
    event = CTFEvent.objects.filter(pk=event_uuid, deleted_at__isnull=True).first()
    if event is None:
        raise ValueError(_SCOPE_UNAVAILABLE)
    scope = resource_scope_from_ids(
        kind=event.scope_kind,
        account_id=event.account_id,
        organization_id=event.organization_id,
        workspace_id=event.workspace_id,
    )
    if scope.kind == "account":
        if scope.workspace_uuid is not None:
            parent_type, parent_uuid = "workspace", scope.workspace_uuid
        elif scope.organization_uuid is not None:
            parent_type, parent_uuid = "organization", scope.organization_uuid
        else:
            if scope.account_uuid is None:
                raise ValueError(_SCOPE_UNAVAILABLE)
            parent_type, parent_uuid = "account", scope.account_uuid
        if event_placement_scope(parent_type, parent_uuid) != scope:
            raise ValueError(_SCOPE_UNAVAILABLE)
    return scope
