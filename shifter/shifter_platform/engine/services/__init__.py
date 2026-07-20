"""Engine service interface.

Infrastructure lifecycle for Shifter platform. The implementation is split
across private submodules (``_common``, ``_range``, ``_lifecycle``,
``_terminal``, ``_ngfw``, ``_queries``) and re-exported here so callers
continue to use ``from engine.services import X``.

The re-exports also rebind a few names that tests historically patch at
``engine.services.<name>`` (``transaction``, ``get_rdp_password``,
``get_ssh_key``) so existing ``unittest.mock.patch`` targets still work.
"""

from __future__ import annotations

from django.db import transaction

from engine.secrets import SecretsError, get_rdp_password, get_ssh_key
from engine.ssh import SSHConnection

from ._aces_evidence import record_aces_operation_status, record_aces_runtime_snapshot
from ._aces_image import (
    AcesImageMappingError,
    AcesImageMappingOptions,
    AcesImageMappingView,
    disable_aces_image_mapping,
    list_aces_image_mappings,
    upsert_aces_image_mapping,
)
from ._aces_range import AcesRangeRef, create_aces_range
from ._aces_status import project_aces_operation_status
from ._capacity import (
    EventCapacitySignal,
    latest_capacity_declaration,
    record_capacity_declaration,
)
from ._common import EngineError
from ._lifecycle import pause_range, resume_range
from ._ngfw import create_ngfw, destroy_ngfw, start_ngfw, stop_ngfw
from ._queries import get_authoritative_range_status, get_ranges_for_ngfw, get_user_ready_range_instances
from ._range import (
    cancel_range,
    create_range,
    destroy_range,
    get_instance_ips_by_uuid,
    get_range_status,
)
from ._range_by_request import (
    RangeOwnershipTransferBlocked,
    cancel_range_by_request,
    destroy_range_by_request,
    range_owner_reassignment_available_by_request,
    reassign_range_owner_by_request,
)
from ._range_escape import GuestProbeError, GuestProbeRequest, RangeMembership, get_range_membership, run_guest_probe
from ._terminal import (
    connect_ngfw_terminal,
    connect_terminal,
    get_rdp_connection_info,
    get_ssh_connection_info,
)
from ._vpn import (
    VpnProfileConflict,
    VpnProfileNotFound,
    VpnProfileUnavailable,
    get_openvpn_profile,
    has_openvpn_profile,
)

__all__ = (
    "AcesImageMappingError",
    "AcesImageMappingOptions",
    "AcesImageMappingView",
    "AcesRangeRef",
    "EngineError",
    "EventCapacitySignal",
    "GuestProbeError",
    "GuestProbeRequest",
    "RangeMembership",
    "RangeOwnershipTransferBlocked",
    "SSHConnection",
    "SecretsError",
    "VpnProfileConflict",
    "VpnProfileNotFound",
    "VpnProfileUnavailable",
    "cancel_range",
    "cancel_range_by_request",
    "connect_ngfw_terminal",
    "connect_terminal",
    "create_aces_range",
    "create_ngfw",
    "create_range",
    "destroy_ngfw",
    "destroy_range",
    "destroy_range_by_request",
    "disable_aces_image_mapping",
    "get_authoritative_range_status",
    "get_instance_ips_by_uuid",
    "get_openvpn_profile",
    "get_range_membership",
    "get_range_status",
    "get_ranges_for_ngfw",
    "get_rdp_connection_info",
    "get_rdp_password",
    "get_ssh_connection_info",
    "get_ssh_key",
    "get_user_ready_range_instances",
    "has_openvpn_profile",
    "latest_capacity_declaration",
    "list_aces_image_mappings",
    "pause_range",
    "project_aces_operation_status",
    "range_owner_reassignment_available_by_request",
    "reassign_range_owner_by_request",
    "record_aces_operation_status",
    "record_aces_runtime_snapshot",
    "record_capacity_declaration",
    "resume_range",
    "run_guest_probe",
    "start_ngfw",
    "stop_ngfw",
    "transaction",
    "upsert_aces_image_mapping",
)
