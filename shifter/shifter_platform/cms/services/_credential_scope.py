"""CMS-owned range ancestry projection for credential authority checks."""

from uuid import UUID

from cms.models import RangeInstance
from shared.identity_scope import ResourceScope
from workspaces.services import resource_scope_from_ids


def range_credential_scope(range_uuid: UUID) -> ResourceScope:
    """Resolve a live range and its validated account hierarchy."""
    instance = RangeInstance.objects.filter(uuid=range_uuid, deleted_at__isnull=True).first()
    if instance is None:
        raise ValueError("Credential scope unavailable")
    return resource_scope_from_ids(
        kind=instance.scope_kind,
        account_id=instance.account_id,
        organization_id=instance.organization_id,
        workspace_id=instance.workspace_id,
    )
