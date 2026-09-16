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
from ._lifecycle import pause_range, resume_range
from ._model_admission import admit_range_model_access
from ._ngfw import create_ngfw, destroy_ngfw, start_ngfw, stop_ngfw
from ._operation_apply import apply_pending_operation_results, evaluate_operation_result
from ._preparation_adapters import (
    PreparationAdapterView,
    install_preparation_adapter,
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
from ._raes_range import RaesRangeRef, RangeBindings, create_raes_range
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
    range_owner_reassignment_available_by_request,
    reassign_range_owner_by_request,
    rebind_range_workspace_by_request,
)
from ._range_escape import GuestProbeError, GuestProbeRequest, RangeMembership, get_range_membership, run_guest_probe
from ._receipt import (
    ReceiptBindingUnavailable,
    ReceiptRegistrationConflict,
    confirm_receipt_verifier_binding,
    project_receipt_verifier_binding,
    register_receipt_verifier,
    revoke_receipt_verifier,
)
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

__all__ = (
    "CLEANUP_NOT_APPLICABLE",
    "CLEANUP_PENDING",
    "CLEANUP_UNKNOWN",
    "CLEANUP_VERIFIED_TERMINAL",
    "DEFAULT_RETRY_TTL_SECONDS",
    "CleanupObligation",
    "CleanupVerificationView",
    "EngineError",
    "EventCapacityRequest",
    "EventCapacitySignal",
    "GuestProbeError",
    "GuestProbeRequest",
    "MembershipEvidence",
    "MintedOperation",
    "ModelAccessRangeView",
    "PreparationAdapterView",
    "PreparationView",
    "RaesImageMappingError",
    "RaesImageMappingOptions",
    "RaesImageMappingView",
    "RaesRangeRef",
    "RangeBindings",
    "RangeCleanupOutcome",
    "RangeMembership",
    "RangeOwnershipTransferBlocked",
    "RangeProjectionIntegrityError",
    "RangeWorkspaceRebindOutcome",
    "ReceiptBindingUnavailable",
    "ReceiptRegistrationConflict",
    "RetryBindingResult",
    "RetryKeyConflict",
    "SSHConnection",
    "SecretsError",
    "SharingError",
    "VpnProfileConflict",
    "VpnProfileNotFound",
    "VpnProfileUnavailable",
    "WarmGenerationDraft",
    "activate_preparation_grant",
    "active_generation_count",
    "admit_range_capacity",
    "admit_range_model_access",
    "admit_warm_generation_capacity",
    "apply_pending_operation_results",
    "assess_declared_event_capacity",
    "assess_event_capacity",
    "bind_public_operation",
    "bucket_state_counts",
    "cancel_artifact_preparation",
    "cancel_range",
    "cancel_range_by_request",
    "claim_ready_generation",
    "confirm_receipt_verifier_binding",
    "connect_ngfw_terminal",
    "connect_terminal",
    "create_ngfw",
    "create_raes_range",
    "create_warm_generation",
    "destroy_ngfw",
    "destroy_range",
    "destroy_range_by_request",
    "disable_raes_image_mapping",
    "drain_sharing_binding",
    "enqueue_range_activation",
    "evaluate_operation_result",
    "finalize_retiring_generations",
    "get_active_range_provisioned_instances",
    "get_artifact_preparation",
    "get_authoritative_range_status",
    "get_instance_ips_by_uuid",
    "get_openvpn_profile",
    "get_or_create_allocation_group",
    "get_owned_instance_request_ref",
    "get_range_membership",
    "get_range_pause_resume_capability",
    "get_range_status",
    "get_ranges_for_ngfw",
    "get_rdp_connection_info",
    "get_rdp_password",
    "get_ssh_connection_info",
    "get_ssh_key",
    "get_user_ready_range_instances",
    "has_openvpn_profile",
    "install_preparation_adapter",
    "invalidate_sharing_authority",
    "is_cleanup_verified_absent",
    "latest_capacity_declaration",
    "latest_cleanup_verification",
    "list_backend_artifacts",
    "list_preparation_adapters",
    "list_raes_image_mappings",
    "lookup_public_operation",
    "operation_id_for_request",
    "pause_range",
    "preview_effective_policy",
    "project_raes_operation_status",
    "project_range_cleanup_outcome",
    "project_receipt_verifier_binding",
    "project_selector_resolution",
    "prune_expired_retry_bindings",
    "publish_authority_fence",
    "publish_membership_projection",
    "publish_sharing_binding",
    "range_owner_reassignment_available_by_request",
    "read_preparation_worker_input",
    "read_subnet_reservation",
    "ready_generations",
    "reassign_range_owner_by_request",
    "rebind_range_workspace_by_request",
    "reconcile_capacity_budgets",
    "reconcile_preparations",
    "record_capacity_declaration",
    "record_cleanup_verification",
    "record_preparation_worker_result",
    "record_raes_operation_status",
    "record_raes_runtime_snapshot",
    "recover_stalled_generations",
    "register_receipt_verifier",
    "release_capacity_reservations",
    "release_range_capacity",
    "release_subnet_reservation",
    "release_warm_generation_capacity",
    "request_artifact_preparation",
    "reserve_subnet_cidrs",
    "resolve_model_access_range_page",
    "resolve_model_access_range_views",
    "resume_range",
    "retire_generation",
    "retire_generations_for_request",
    "retire_removed_bucket_generations",
    "retry_artifact_preparation",
    "revoke_preparation_grant",
    "revoke_receipt_verifier",
    "run_guest_probe",
    "set_preparation_adapter_state",
    "start_ngfw",
    "stop_ngfw",
    "total_active_generation_count",
    "transaction",
    "upsert_raes_image_mapping",
    "validate_sharing_binding",
    "warm_capacity_scope_ref",
)
