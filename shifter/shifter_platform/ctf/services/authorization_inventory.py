"""SQL-authoritative event inventory for authorization delegation proofs."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from shared.authorization import (
    TargetRef,
    bind_authorization_descendant_resolver,
    bind_authorization_event_inventory,
)
from shared.identity_scope import ResourceScope
from workspaces.services import resolve_resource_scope

from .credential_scope import event_credential_scope


def list_authorization_event_uuids(workspace_ids: Sequence[int], limit: int) -> tuple[UUID, ...]:
    """Return at most ``limit`` event UUIDs for the exact workspace ids."""
    from ctf.models import CTFEvent

    if limit <= 0 or not workspace_ids:
        return ()
    return tuple(
        CTFEvent.objects.filter(workspace_id__in=workspace_ids).order_by("id").values_list("id", flat=True)[:limit]
    )


def _authorization_event_targets(workspace_ids: Sequence[int], limit: int) -> tuple[TargetRef, ...]:
    """Project SQL-owned event identities into neutral authorization targets."""
    return tuple(TargetRef("event", item) for item in list_authorization_event_uuids(workspace_ids, limit))


def list_authorization_nonworkspace_events(
    parent: ResourceScope, limit: int
) -> tuple[tuple[TargetRef, ResourceScope], ...]:
    """Enumerate account- and organization-placed events below a SQL parent."""
    from ctf.models import CTFEvent

    if limit <= 0:
        return ()
    rows = CTFEvent.objects.filter(scope_kind="account", workspace_id__isnull=True, deleted_at__isnull=True)
    if parent.kind == "account":
        resolved = resolve_resource_scope(parent)
        rows = rows.filter(account_id=resolved.account_id)
        if resolved.organization_id is not None:
            rows = rows.filter(organization_id=resolved.organization_id)
    return tuple(
        (
            TargetRef("event", event.id),
            event_credential_scope(event.id),
        )
        for event in rows.order_by("id")[:limit]
    )


def register_authorization_event_inventory() -> None:
    """Bind the CTF-owned SQL event inventory to the neutral port."""
    bind_authorization_descendant_resolver("ctf.events", _authorization_event_targets)
    bind_authorization_event_inventory(event_credential_scope, list_authorization_nonworkspace_events)
