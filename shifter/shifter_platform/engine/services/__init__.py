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

from datetime import datetime

from django.db import transaction

from engine.secrets import SecretsError, get_rdp_password, get_ssh_key
from engine.ssh import SSHConnection

from ._authorization_inventory import list_authorization_range_uuids
from ._capacity import (
    EventCapacitySignal,
    latest_capacity_declaration,
    record_capacity_declaration,
)
from ._capacity_admit import (
    admit_range_capacity,
    reconcile_capacity_budgets,
    release_range_capacity,
)
from ._capacity_plan import (
    EventCapacityRequest,
    assess_declared_event_capacity,
    assess_event_capacity,
    release_capacity_reservations,
)
from ._cleanup_outcome import (
    CLEANUP_NOT_APPLICABLE,
    CLEANUP_PENDING,
    CLEANUP_UNKNOWN,
    CLEANUP_VERIFIED_TERMINAL,
    CleanupObligation,
    RangeCleanupOutcome,
    project_range_cleanup_outcome,
)
from ._cleanup_verification import (
    CleanupVerificationView,
    is_cleanup_verified_absent,
    latest_cleanup_verification,
    record_cleanup_verification,
)
from ._common import EngineError
from ._feature_artifact_launcher import default_storage_target, reconcile_feature_artifact_acquisitions
from ._feature_artifacts import (
    ArtifactRequest,
    FeatureArtifactUnavailableError,
    StorageTarget,
    await_ready,
    request_acquisition,
)
from ._lifecycle import dispatch_prepared_range_resume, pause_range, resume_range
from ._model_admission import admit_range_model_access
from ._model_broker_control import advance_model_call, commit_model_call, finish_model_call, reserve_model_call
from ._model_credentials import (
    authenticate_model_access,
    exchange_model_enrollment,
    issue_model_enrollment,
    refresh_model_access,
)
from ._model_launch_api import (
    disable_optional_model_preparation,
    fence_model_policy_publication,
    get_model_launch_preparation,
    get_model_warm_scope,
    list_model_launch_refreshes,
    prepare_model_launch,
    project_model_launch_authority,
    record_model_observations,
)
from ._model_policy_transition import (
    admit_range_model_policy_change,
    begin_range_model_policy_change,
    get_range_model_policy_status,
    revoke_range_model_access,
)
from ._model_request_accounting import RequestIdempotency, ReservationOutcome, reserve_request
from ._model_request_commit import commit_request_spend
from ._model_request_lifecycle import (
    DispatchGrant,
    charge_unknown,
    check_dispatch_lease,
    fence_revoked_requests,
    open_dispatch,
    release_before_dispatch,
    renew_continuation_lease,
    settle_request,
)
from ._model_request_reconcile import (
    apply_late_evidence,
    close_expired_revocations,
    reconcile_expired_dispatches,
    reconcile_model_requests,
)
from ._model_source_control import model_source_execution
from ._model_sources import (
    ModelSourceView,
    compile_authorized_model_sources,
    create_model_source,
    list_model_sources,
    project_authorized_model_sources,
    retire_unused_model_source_credentials,
    update_model_source,
)
from ._ngfw import create_ngfw, destroy_ngfw, start_ngfw, stop_ngfw
from ._operation_apply import apply_pending_operation_results, evaluate_operation_result
from ._preparation_adapters import (
    PreparationAdapterView,
    install_preparation_adapter,
    list_preparation_adapter_grants,
    list_preparation_adapters,
    set_preparation_adapter_state,
)
from ._preparation_controller import reconcile_preparations
from ._preparation_grants import activate_preparation_grant, revoke_preparation_grant
from ._preparation_operations import (
    PreparationView,
    cancel_artifact_preparation,
    get_artifact_preparation,
    request_artifact_preparation,
    retry_artifact_preparation,
)
from ._preparation_worker import read_preparation_worker_input, record_preparation_worker_result
from ._public_operations import (
    DEFAULT_RETRY_TTL_SECONDS,
    MintedOperation,
    RetryBindingResult,
    RetryKeyConflict,
    bind_public_operation,
    lookup_public_operation,
    operation_id_for_request,
    prune_expired_retry_bindings,
)
from ._queries import get_authoritative_range_status, get_ranges_for_ngfw, get_user_ready_range_instances
from ._raes_evidence import record_raes_operation_status, record_raes_runtime_snapshot
from ._raes_image import (
    RaesImageMappingError,
    RaesImageMappingOptions,
    RaesImageMappingView,
    disable_raes_image_mapping,
    list_backend_artifacts,
    list_raes_image_mappings,
    upsert_raes_image_mapping,
)
from ._raes_range import (
    RaesRangeRef,
    RangeBindings,
    create_raes_range,
    dispatch_created_raes_range,
    grant_raes_remote_access,
)
from ._raes_status import project_raes_operation_status
from ._range import (
    cancel_range,
    destroy_range,
    get_instance_ips_by_uuid,
    get_range_pause_resume_capability,
    get_range_status,
)
from ._range_by_request import (
    RangeOwnershipTransferBlocked,
    RangeProjectionIntegrityError,
    RangeWorkspaceRebindOutcome,
    cancel_range_by_request,
    destroy_range_by_request,
    get_pinned_range_egress_mode_by_request,
    get_range_failure_reason_by_request,
    range_owner_reassignment_available_by_request,
    reassign_range_owner_by_request,
    rebind_range_workspace_by_request,
)
from ._range_escape import GuestProbeError, GuestProbeRequest, RangeMembership, get_range_membership, run_guest_probe
from ._range_ownership import RangeOwnershipProjection, range_ownership_projection
from ._receipt import (
    ReceiptBindingUnavailable,
    ReceiptRegistrationConflict,
    confirm_receipt_verifier_binding,
    project_receipt_verifier_binding,
    register_receipt_verifier,
    revoke_receipt_verifier,
)
from ._runtime_plugin_bindings import (
    RuntimePluginPackView,
    bind_runtime_plugin,
    has_runtime_plugin_binding,
    list_runtime_plugin_bindings,
)
from ._runtime_plugin_controller import reconcile_runtime_plugins
from ._runtime_plugin_operations import reconcile_runtime_plugin_operations
from ._runtime_plugins import change_runtime_plugin, install_runtime_plugin, list_runtime_plugins
from ._sharing import (
    MembershipEvidence,
    ModelAccessRangeView,
    SharingError,
    drain_sharing_binding,
    get_or_create_allocation_group,
    invalidate_sharing_authority,
    preview_effective_policy,
    project_selector_resolution,
    publish_authority_fence,
    publish_membership_projection,
    publish_sharing_binding,
    resolve_model_access_range_page,
    resolve_model_access_range_reference,
    resolve_model_access_range_views,
    validate_sharing_binding,
)
from ._subnet_coordination import (
    read_subnet_reservation,
    release_subnet_reservation,
    reserve_subnet_cidrs,
)
from ._terminal import (
    connect_ngfw_terminal,
    connect_terminal,
    get_active_range_provisioned_instances,
    get_owned_instance_request_ref,
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
from ._vpn_sessions import (
    VPN_SESSION_HEARTBEAT_SECONDS,
    VPN_SESSION_LEASE_SECONDS,
    VpnSessionDenied,
    VpnSessionGrant,
    authorize_vpn_session,
    end_vpn_session,
    renew_vpn_sessions,
)
from ._warm_pool import (
    WarmGenerationDraft,
    active_generation_count,
    admit_warm_generation_capacity,
    bucket_state_counts,
    claim_ready_generation,
    create_warm_generation,
    enqueue_range_activation,
    finalize_retiring_generations,
    ready_generations,
    recover_stalled_generations,
    release_warm_generation_capacity,
    retire_generation,
    retire_generations_for_request,
    retire_removed_bucket_generations,
    total_active_generation_count,
    warm_capacity_scope_ref,
)


def reconcile_model_allocations(*, now: datetime | None = None, limit: int = 100) -> int:
    """Lazily expose allocation cleanup without importing models during app setup."""
    from ._model_allocation_lifecycle import reconcile_model_allocations as reconcile

    return reconcile(now=now, limit=limit)


__all__ = (
    "CLEANUP_NOT_APPLICABLE",
    "CLEANUP_PENDING",
    "CLEANUP_UNKNOWN",
    "CLEANUP_VERIFIED_TERMINAL",
    "DEFAULT_RETRY_TTL_SECONDS",
    "VPN_SESSION_HEARTBEAT_SECONDS",
    "VPN_SESSION_LEASE_SECONDS",
    "ArtifactRequest",
    "CleanupObligation",
    "CleanupVerificationView",
    "DispatchGrant",
    "EngineError",
    "EventCapacityRequest",
    "EventCapacitySignal",
    "FeatureArtifactUnavailableError",
    "GuestProbeError",
    "GuestProbeRequest",
    "MembershipEvidence",
    "MintedOperation",
    "ModelAccessRangeView",
    "ModelSourceView",
    "PreparationAdapterView",
    "PreparationView",
    "RaesImageMappingError",
    "RaesImageMappingOptions",
    "RaesImageMappingView",
    "RaesRangeRef",
    "RangeBindings",
    "RangeCleanupOutcome",
    "RangeMembership",
    "RangeOwnershipProjection",
    "RangeOwnershipTransferBlocked",
    "RangeProjectionIntegrityError",
    "RangeWorkspaceRebindOutcome",
    "ReceiptBindingUnavailable",
    "ReceiptRegistrationConflict",
    "RequestIdempotency",
    "ReservationOutcome",
    "RetryBindingResult",
    "RetryKeyConflict",
    "RuntimePluginPackView",
    "SSHConnection",
    "SecretsError",
    "SharingError",
    "StorageTarget",
    "VpnProfileConflict",
    "VpnProfileNotFound",
    "VpnProfileUnavailable",
    "VpnSessionDenied",
    "VpnSessionGrant",
    "WarmGenerationDraft",
    "activate_preparation_grant",
    "active_generation_count",
    "admit_range_capacity",
    "admit_range_model_access",
    "admit_range_model_policy_change",
    "admit_warm_generation_capacity",
    "advance_model_call",
    "apply_late_evidence",
    "apply_pending_operation_results",
    "assess_declared_event_capacity",
    "assess_event_capacity",
    "authenticate_model_access",
    "authorize_vpn_session",
    "await_ready",
    "begin_range_model_policy_change",
    "bind_public_operation",
    "bind_runtime_plugin",
    "bucket_state_counts",
    "cancel_artifact_preparation",
    "cancel_range",
    "cancel_range_by_request",
    "change_runtime_plugin",
    "charge_unknown",
    "check_dispatch_lease",
    "claim_ready_generation",
    "close_expired_revocations",
    "commit_model_call",
    "commit_request_spend",
    "compile_authorized_model_sources",
    "confirm_receipt_verifier_binding",
    "connect_ngfw_terminal",
    "connect_terminal",
    "create_model_source",
    "create_ngfw",
    "create_raes_range",
    "create_warm_generation",
    "default_storage_target",
    "destroy_ngfw",
    "destroy_range",
    "destroy_range_by_request",
    "disable_optional_model_preparation",
    "disable_raes_image_mapping",
    "dispatch_created_raes_range",
    "dispatch_prepared_range_resume",
    "drain_sharing_binding",
    "end_vpn_session",
    "enqueue_range_activation",
    "evaluate_operation_result",
    "exchange_model_enrollment",
    "fence_model_policy_publication",
    "fence_revoked_requests",
    "finalize_retiring_generations",
    "finish_model_call",
    "get_active_range_provisioned_instances",
    "get_artifact_preparation",
    "get_authoritative_range_status",
    "get_instance_ips_by_uuid",
    "get_model_launch_preparation",
    "get_model_warm_scope",
    "get_openvpn_profile",
    "get_or_create_allocation_group",
    "get_owned_instance_request_ref",
    "get_pinned_range_egress_mode_by_request",
    "get_range_failure_reason_by_request",
    "get_range_membership",
    "get_range_model_policy_status",
    "get_range_pause_resume_capability",
    "get_range_status",
    "get_ranges_for_ngfw",
    "get_rdp_connection_info",
    "get_rdp_password",
    "get_ssh_connection_info",
    "get_ssh_key",
    "get_user_ready_range_instances",
    "grant_raes_remote_access",
    "has_openvpn_profile",
    "has_runtime_plugin_binding",
    "install_preparation_adapter",
    "install_runtime_plugin",
    "invalidate_sharing_authority",
    "is_cleanup_verified_absent",
    "issue_model_enrollment",
    "latest_capacity_declaration",
    "latest_cleanup_verification",
    "list_authorization_range_uuids",
    "list_backend_artifacts",
    "list_model_launch_refreshes",
    "list_model_sources",
    "list_preparation_adapter_grants",
    "list_preparation_adapters",
    "list_raes_image_mappings",
    "list_runtime_plugin_bindings",
    "list_runtime_plugins",
    "lookup_public_operation",
    "model_source_execution",
    "open_dispatch",
    "operation_id_for_request",
    "pause_range",
    "prepare_model_launch",
    "preview_effective_policy",
    "project_authorized_model_sources",
    "project_model_launch_authority",
    "project_raes_operation_status",
    "project_range_cleanup_outcome",
    "project_receipt_verifier_binding",
    "project_selector_resolution",
    "prune_expired_retry_bindings",
    "publish_authority_fence",
    "publish_membership_projection",
    "publish_sharing_binding",
    "range_owner_reassignment_available_by_request",
    "range_ownership_projection",
    "read_preparation_worker_input",
    "read_subnet_reservation",
    "ready_generations",
    "reassign_range_owner_by_request",
    "rebind_range_workspace_by_request",
    "reconcile_capacity_budgets",
    "reconcile_expired_dispatches",
    "reconcile_feature_artifact_acquisitions",
    "reconcile_model_allocations",
    "reconcile_model_requests",
    "reconcile_preparations",
    "reconcile_runtime_plugin_operations",
    "reconcile_runtime_plugins",
    "record_capacity_declaration",
    "record_cleanup_verification",
    "record_model_observations",
    "record_preparation_worker_result",
    "record_raes_operation_status",
    "record_raes_runtime_snapshot",
    "recover_stalled_generations",
    "refresh_model_access",
    "register_receipt_verifier",
    "release_before_dispatch",
    "release_capacity_reservations",
    "release_range_capacity",
    "release_subnet_reservation",
    "release_warm_generation_capacity",
    "renew_continuation_lease",
    "renew_vpn_sessions",
    "request_acquisition",
    "request_artifact_preparation",
    "reserve_model_call",
    "reserve_request",
    "reserve_subnet_cidrs",
    "resolve_model_access_range_page",
    "resolve_model_access_range_reference",
    "resolve_model_access_range_views",
    "resume_range",
    "retire_generation",
    "retire_generations_for_request",
    "retire_removed_bucket_generations",
    "retire_unused_model_source_credentials",
    "retry_artifact_preparation",
    "revoke_preparation_grant",
    "revoke_range_model_access",
    "revoke_receipt_verifier",
    "run_guest_probe",
    "set_preparation_adapter_state",
    "settle_request",
    "start_ngfw",
    "stop_ngfw",
    "total_active_generation_count",
    "transaction",
    "update_model_source",
    "upsert_raes_image_mapping",
    "validate_sharing_binding",
    "warm_capacity_scope_ref",
)
