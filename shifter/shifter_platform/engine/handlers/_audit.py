"""Audit-action mapping shared by the range and NGFW handlers.

Leaf helper split out of ``engine/handlers.py`` (#685) so both the range and
NGFW handler submodules can use it without a package import cycle.
"""

from __future__ import annotations

from shared.audit import AuditAction
from shared.enums import ResourceStatus


def _status_to_action(status: str) -> str:
    """Map range status to audit action."""
    status_action_map = {
        ResourceStatus.READY.value: AuditAction.READY,
        ResourceStatus.FAILED.value: AuditAction.FAILED,
        ResourceStatus.DESTROYED.value: AuditAction.DEPROVISION,
        ResourceStatus.PROVISIONING.value: AuditAction.PROVISION,
        ResourceStatus.DESTROYING.value: AuditAction.DEPROVISION,
    }
    return status_action_map.get(status, AuditAction.UPDATE)
