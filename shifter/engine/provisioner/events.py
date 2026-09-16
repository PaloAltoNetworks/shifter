"""Provisioner status vocabulary for cyberscript range operations.

Range lifecycle notifications are no longer written by the provisioner
(ADR-043 phase 7, #1839). Cut-over families report through the operation
result inbox; the Engine applier enqueues ADR-025 outbox rows. The surviving
cyberscript provision/destroy path updates ``mission_control_range`` directly
via :func:`provisioner_db.update_range_status`.
"""

from __future__ import annotations

from shared.enums import ResourceStatus

# Status string aliases for provisioner call sites (sourced from shared.enums).
STATUS_PENDING = ResourceStatus.PENDING.value
STATUS_PROVISIONING = ResourceStatus.PROVISIONING.value
STATUS_READY = ResourceStatus.READY.value
STATUS_PAUSING = ResourceStatus.PAUSING.value
STATUS_PAUSED = ResourceStatus.PAUSED.value
STATUS_RESUMING = ResourceStatus.RESUMING.value
STATUS_FAILED = ResourceStatus.FAILED.value
STATUS_DESTROYING = ResourceStatus.DESTROYING.value
STATUS_DESTROYED = ResourceStatus.DESTROYED.value
