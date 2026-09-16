"""CMS service interface.

Content and asset management for Shifter platform. The implementation is
split across private submodules (``_common``, ``_agents``, ``_credentials``,
``_range_queries``, ``_raes_range_create``, ``_range_destroy``, ``_range_pause``,
``_range_resume``, ``_uploads``, ``_scenarios``, ``_ngfws``, ``_queries``)
and re-exported here so callers continue to use
``from cms.services import X``.

The re-exports also rebind names that tests historically patch at
``cms.services.<name>`` (``assets_create_agent``, ``assets_delete_agent``,
``audit_log``, the ``engine_*`` aliases, ``RangeInstance``) so existing
``unittest.mock.patch`` targets still work.

The cross-layer re-export (``cms.signals.*``) is
preserved on the facade so the layer-imports gate
(``scripts/check_layer_imports/layer_imports.yaml``) continues to allow
only ``cms.services`` from mission_control / ctf rather than reaching into
``cms.signals`` directly.
"""

from __future__ import annotations

# --- Names tests patch via ``patch("cms.services.X")`` -----------------------
# Rebound here so the patch target resolves at the package level, which means
# submodules that look these up at call time through ``cms.services`` honour
# the mock for free.
from cms.assets.services import AgentUploadSpec
from cms.assets.services import create_agent as assets_create_agent
from cms.assets.services import delete_agent as assets_delete_agent
from cms.exceptions import CMSError, RangeScopeAdminError, WorkspaceLaunchDenied, WorkspaceLaunchQuotaExceeded
from cms.models import AgentConfig, RangeInstance
from cms.scenarios.images import project_scenario_images
from cms.signals import range_status_changed as range_status_changed
from engine.services import CleanupObligation as CleanupObligation
from engine.services import EventCapacitySignal as EngineEventCapacitySignal
from engine.services import RangeCleanupOutcome as RangeCleanupOutcome
from engine.services import RetryKeyConflict as RetryKeyConflict
from engine.services import admit_range_capacity as engine_admit_range_capacity
from engine.services import assess_declared_event_capacity as engine_assess_declared_event_capacity
from engine.services import cancel_range_by_request as engine_cancel_range_by_request
from engine.services import confirm_receipt_verifier_binding as engine_confirm_receipt_verifier_binding
from engine.services import destroy_range_by_request as engine_destroy_range_by_request
from engine.services import get_instance_ips_by_uuid as engine_get_instance_ips_by_uuid
from engine.services import get_openvpn_profile as engine_get_openvpn_profile
from engine.services import get_range_pause_resume_capability as engine_get_range_pause_resume_capability
from engine.services import has_openvpn_profile as engine_has_openvpn_profile
from engine.services import invalidate_sharing_authority as engine_invalidate_sharing_authority
from engine.services import pause_range as engine_pause_range
from engine.services import project_range_cleanup_outcome as project_range_cleanup_outcome
from engine.services import project_receipt_verifier_binding as engine_project_receipt_verifier_binding
from engine.services import project_selector_resolution as engine_project_selector_resolution
from engine.services import publish_sharing_binding as engine_publish_sharing_binding
from engine.services import (
    range_owner_reassignment_available_by_request as engine_range_owner_reassignment_available,
)
from engine.services import reassign_range_owner_by_request as engine_reassign_range_owner
from engine.services import rebind_range_workspace_by_request as engine_rebind_range_workspace
from engine.services import (
    record_capacity_declaration as engine_record_capacity_declaration,
)
from engine.services import release_capacity_reservations as engine_release_capacity_reservations
from engine.services import release_range_capacity as engine_release_range_capacity
from engine.services import resolve_model_access_range_page as engine_resolve_model_access_range_page
from engine.services import resolve_model_access_range_views as engine_resolve_model_access_range_views
from engine.services import resume_range as engine_resume_range
from shared.audit import (
    AuditEvent,
    audit_log,
)

from ._agents import (
    create_agent,
    delete_agent,
    get_agent,
    get_allowed_extensions,
    list_agents,
    max_agent_file_size_bytes,
)
from ._content_ingestion import PackRegistrationRequest, RegisteredPack, register_pack
from ._credentials import (
    create_credential,
    delete_credential,
    get_credential,
    list_credentials,
)
from ._model_access_sharing import (
    ModelAccessSelectorError,
    find_model_access_selected_ranges,
    resolve_model_access_range_instances,
    resolve_model_access_range_views,
    resolve_model_access_selected_ranges,
    resolve_model_access_selector,
)
from ._ngfws import (
    create_ngfw,
    destroy_ngfw,
    get_ngfw,
    list_ngfws,
)
from ._non_user_range_launch import NonUserWorkflow, create_non_user_range

# --- Public service functions ------------------------------------------------
from ._pack_conformance import validate_registered_pack_conformance
from ._queries import (
    find_range_instance_id_by_request,
    get_range_spec_by_id,
    get_range_status_by_id,
    get_range_target_instances,
)
from ._raes_range_create import create_raes_native_range, create_range_dispatch
from ._range_access import (
    connect_range_terminal,
    get_range_rdp_connection_info,
    get_range_ssh_connection_info,
)
from ._range_destroy import (
    cancel_range,
    cancel_range_by_request_id,
    destroy_range,
    destroy_range_by_request_id,
)
from ._range_lease import (
    RangeLeaseConflict,
    RangeLeaseNotFound,
    expire_due_ranges,
    extend_mission_control_range,
    get_mission_control_range_lease,
    reconcile_ctf_range_leases,
)
from ._range_lease_policy import (
    LeasePolicyAuditContext,
    LeasePolicyOverride,
    MissionControlLeasePolicyAdminError,
    MissionControlLeasePolicySettings,
    get_mission_control_lease_settings,
    replace_group_lease_policy,
    replace_tenant_lease_policy,
    reset_group_lease_policy,
    reset_tenant_lease_policy,
    resolve_mission_control_lease_policy,
)
from ._range_pause import pause_range, pause_range_by_request_id
from ._range_queries import (
    get_active_range,
    get_range,
    get_range_by_request_id,
    has_ready_active_range,
    list_mission_control_range_history,
    list_ranges,
)
from ._range_reassign import range_owner_reassignment_available, reassign_range_owner
from ._range_resume import resume_range, resume_range_by_request_id
from ._range_vpn import (
    CtfOpenVpnProfileConflict,
    CtfOpenVpnProfileNotFound,
    CtfOpenVpnProfileUnavailable,
    OpenVpnProfileConflict,
    OpenVpnProfileNotFound,
    OpenVpnProfileUnavailable,
    get_ctf_openvpn_profile,
    get_mission_control_openvpn_profile,
    has_ctf_openvpn_profile,
    has_mission_control_openvpn_profile,
)
from ._range_workspace_admin import (
    RangeRebindResult,
    RangeScopeAuditContext,
    list_range_scope_bindings,
    rebind_range_workspace,
)
from ._receipt import ReceiptRangeBindingUnavailable, confirm_ctf_receipt_binding, project_ctf_receipt_binding
from ._retry_safe_launch import RetrySafeLaunchOutcome, bind_first_use_launch, resolve_retry_recovery
from ._scenarios import (
    get_scenario,
    list_launchable_scenarios,
    list_scenarios,
    validate_scenario_requirements,
)
from ._uploads import (
    cancel_upload,
    complete_upload,
    get_storage_used,
    initiate_upload,
)
from ._user_offboarding import (
    TRANSFERABLE_RESOURCE_KINDS,
    OffboardingAuditContext,
    OwnershipTransferSummary,
    transfer_user_ownership,
)
from ._warm_pool_claim import attempt_warm_claim
from ._warm_pool_reconcile import reconcile_warm_pool

# The public product launch seam is permanently RAES-owned after #1311.
create_range = create_range_dispatch

# Cross-layer re-export preserved on cms.services so the layer-imports gate
# (scripts/check_layer_imports/layer_imports.yaml) can continue to allow only
# `cms.services` from mission_control / ctf rather than reaching into
# cms.signals directly.
__all__ = (
    "TRANSFERABLE_RESOURCE_KINDS",
    "AgentConfig",
    "AgentUploadSpec",
    "AuditEvent",
    "CMSError",
    "CleanupObligation",
    "CtfOpenVpnProfileConflict",
    "CtfOpenVpnProfileNotFound",
    "CtfOpenVpnProfileUnavailable",
    "EngineEventCapacitySignal",
    "LeasePolicyAuditContext",
    "LeasePolicyOverride",
    "MissionControlLeasePolicyAdminError",
    "MissionControlLeasePolicySettings",
    "ModelAccessSelectorError",
    "NonUserWorkflow",
    "OffboardingAuditContext",
    "OpenVpnProfileConflict",
    "OpenVpnProfileNotFound",
    "OpenVpnProfileUnavailable",
    "OwnershipTransferSummary",
    "PackRegistrationRequest",
    "RangeCleanupOutcome",
    "RangeInstance",
    "RangeLeaseConflict",
    "RangeLeaseNotFound",
    "RangeRebindResult",
    "RangeScopeAdminError",
    "RangeScopeAuditContext",
    "ReceiptRangeBindingUnavailable",
    "RegisteredPack",
    "RetryKeyConflict",
    "RetrySafeLaunchOutcome",
    "WorkspaceLaunchDenied",
    "WorkspaceLaunchQuotaExceeded",
    "assets_create_agent",
    "assets_delete_agent",
    "attempt_warm_claim",
    "audit_log",
    "bind_first_use_launch",
    "cancel_range",
    "cancel_range_by_request_id",
    "cancel_upload",
    "complete_upload",
    "confirm_ctf_receipt_binding",
    "connect_range_terminal",
    "create_agent",
    "create_credential",
    "create_ngfw",
    "create_non_user_range",
    "create_raes_native_range",
    "create_range",
    "create_range_dispatch",
    "delete_agent",
    "delete_credential",
    "destroy_ngfw",
    "destroy_range",
    "destroy_range_by_request_id",
    "engine_admit_range_capacity",
    "engine_assess_declared_event_capacity",
    "engine_cancel_range_by_request",
    "engine_confirm_receipt_verifier_binding",
    "engine_destroy_range_by_request",
    "engine_get_instance_ips_by_uuid",
    "engine_get_openvpn_profile",
    "engine_get_range_pause_resume_capability",
    "engine_has_openvpn_profile",
    "engine_invalidate_sharing_authority",
    "engine_pause_range",
    "engine_project_receipt_verifier_binding",
    "engine_project_selector_resolution",
    "engine_publish_sharing_binding",
    "engine_range_owner_reassignment_available",
    "engine_reassign_range_owner",
    "engine_rebind_range_workspace",
    "engine_record_capacity_declaration",
    "engine_release_capacity_reservations",
    "engine_release_range_capacity",
    "engine_resolve_model_access_range_page",
    "engine_resolve_model_access_range_views",
    "engine_resume_range",
    "expire_due_ranges",
    "extend_mission_control_range",
    "find_model_access_selected_ranges",
    "find_range_instance_id_by_request",
    "get_active_range",
    "get_agent",
    "get_allowed_extensions",
    "get_credential",
    "get_ctf_openvpn_profile",
    "get_mission_control_lease_settings",
    "get_mission_control_openvpn_profile",
    "get_mission_control_range_lease",
    "get_ngfw",
    "get_range",
    "get_range_by_request_id",
    "get_range_rdp_connection_info",
    "get_range_spec_by_id",
    "get_range_ssh_connection_info",
    "get_range_status_by_id",
    "get_range_target_instances",
    "get_scenario",
    "get_storage_used",
    "has_ctf_openvpn_profile",
    "has_mission_control_openvpn_profile",
    "has_ready_active_range",
    "initiate_upload",
    "list_agents",
    "list_credentials",
    "list_launchable_scenarios",
    "list_mission_control_range_history",
    "list_ngfws",
    "list_range_scope_bindings",
    "list_ranges",
    "list_scenarios",
    "max_agent_file_size_bytes",
    "pause_range",
    "pause_range_by_request_id",
    "project_ctf_receipt_binding",
    "project_range_cleanup_outcome",
    "project_scenario_images",
    "range_owner_reassignment_available",
    "range_status_changed",
    "reassign_range_owner",
    "rebind_range_workspace",
    "reconcile_ctf_range_leases",
    "reconcile_warm_pool",
    "register_pack",
    "replace_group_lease_policy",
    "replace_tenant_lease_policy",
    "reset_group_lease_policy",
    "reset_tenant_lease_policy",
    "resolve_mission_control_lease_policy",
    "resolve_model_access_range_instances",
    "resolve_model_access_range_views",
    "resolve_model_access_selected_ranges",
    "resolve_model_access_selector",
    "resolve_retry_recovery",
    "resume_range",
    "resume_range_by_request_id",
    "transfer_user_ownership",
    "validate_registered_pack_conformance",
    "validate_scenario_requirements",
)
