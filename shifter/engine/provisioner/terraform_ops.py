"""Terraform provision / destroy + Terraform variable builders for Shifter ranges.

Extracted from ``main.py`` (Sonar S104). Owns the run_range_terraform
dispatch path, the per-operation provision and destroy pipelines, the
NGFW recovery path that runs before provisioning, the NGFW-on-range
attachment helpers that run after the Terraform apply, and the
``_build_range_terraform_variables`` family that maps the range spec
into the inputs the Terraform module expects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from shared.range_cells import RangeCellContractError, validate_scenario_artifact
from shared.range_instantiation_policy import InstantiationPurpose
from shared.remote_access import parse_openvpn_capability, validate_openvpn_capability_window

import range_terraform_runner
from config import is_gce_range_cell_backend
from events import (
    STATUS_DESTROYED,
    STATUS_FAILED,
    STATUS_PROVISIONING,
    STATUS_READY,
)
from gcp_range_cell_scenario import validate_legacy_gce_composition
from instance_orchestrator import run_instance_setup
from provisioner_db import (
    get_range_data_by_request_id,
    update_range_status,
    write_provisioned_state,
)
from provisioner_db_appends import OperationRef
from range_backend_resolution import (
    assert_provision_route,
    prerequisite_error,
    resolve_operation_backend,
    resolve_provision_purpose,
)
from range_subnet_allocation import (
    _post_destroy_cleanup,
    _realized_range_spec_for_destroy,
    _reserve_range_subnet_cidrs,
)
from state_helpers import _validate_provisioned_outputs
from terraform_ngfw_range import (
    _configure_ngfw_for_range,
    _ensure_ngfw_ready_for_provisioning,
    _maybe_pause_user_ngfw,
    _remove_ngfw_attachments_for_destroy,
    _validate_ngfw_range_attachment,
)
from terraform_vars import RangeVariableContext, build_range_variables
from vpn_access import (
    cleanup_openvpn_access,
    finalize_openvpn_access,
    prepare_openvpn_access,
    verify_openvpn_gateway,
)
from vpn_secrets import get_vpn_secret_ops, openvpn_access_enabled

logger = logging.getLogger(__name__)


def _cleanup_openvpn_if_enabled(range_id: int, request_id: str, *, delete_identity: bool = True) -> None:
    """Delete a generation only when this installation could have created it."""
    if openvpn_access_enabled():
        cleanup_openvpn_access(
            range_id,
            request_id,
            get_vpn_secret_ops(),
            delete_identity=delete_identity,
        )


@dataclass(frozen=True)
class RangeOperation:
    """Inputs of one range Terraform operation, bound once at dispatch.

    ``backend`` is the #1666 per-operation ownership binding captured at
    operation start; on a provision failure the compensation destroy routes
    from it, never a re-read of the env selector.

    ``purpose`` is the #1354 trusted instantiation purpose read from the same
    persisted binding. It reaches the provisioner's defense-in-depth policy
    evaluation before any GDC apply call.

    ``operation_id`` is the ADR-043 canonical operation generation (#1834);
    ``None`` on local-dev runs / commands not yet carrying it.
    """

    request_id: str
    range_id: int
    user_id: int
    range_spec: dict[str, Any]
    scenario_artifact: dict[str, Any] | None = None
    backend: str | None = None
    purpose: InstantiationPurpose = InstantiationPurpose.LIVE_FIRE
    remote_access_capability: dict[str, object] | None = None
    operation_id: str | None = None
    # Effective egress posture pinned at create (PLAT-238, ADR-017-R5). Threaded
    # into the range Terraform variables so ``none`` suppresses the participant
    # default route/NAT per-range; ``status-quo`` inherits the deployment baseline.
    egress_mode: str = "status-quo"


def _operation_variable_context(operation: RangeOperation) -> RangeVariableContext:
    """Bundle the per-operation range-variable binding (PLAT-238 egress included)."""
    return RangeVariableContext(
        scenario_artifact=operation.scenario_artifact,
        backend=operation.backend,
        remote_access_capability=operation.remote_access_capability,
        egress_mode=operation.egress_mode,
    )


def _build_operation_variables(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict[str, Any],
    context: RangeVariableContext,
) -> dict[str, Any]:
    """Build backend variables from the range spec and the per-operation binding.

    ``context.backend`` (the #1666 per-operation binding) selects the variable
    shape from persisted ownership for destroy/compensation; ``None`` keeps the
    env-selector behavior. ``context.egress_mode`` is the pinned per-range posture
    (PLAT-238); it flows into the range Terraform variables so a ``none`` range
    suppresses NAT/default-route regardless of the deployment env.
    """
    return build_range_variables(request_id, range_id, user_id, range_spec, context)


def _teardown_owned_range_resources(
    operation: RangeOperation,
    *,
    delete_vpn_identity: bool,
    revoke_vpn_even_if_destroy_fails: bool = False,
) -> None:
    """Tear down the request-owned cloud resources via the canonical algorithm.

    Shared by explicit destroy and provision-failure compensation so the two do
    not drift into divergent lifecycle algorithms (ADR-039-R1/R3): NGFW detach,
    realized-CIDR reconstruction (never authored intent), provider-routed destroy,
    VPN + Terraform-state cleanup, and ownership release via ``_post_destroy_cleanup``
    ONLY after destroy confirms absence. A partial/failed destroy propagates with
    ownership retained, so the operation stays retryable (ADR-043-R7).
    ``delete_vpn_identity`` deletes the deterministic GCE principal on terminal
    destroy but is ``False`` for compensation (preserve identity for retry).
    ``revoke_vpn_even_if_destroy_fails`` makes compensation revoke the issued
    remote-access generation even on a failed destroy, so credentials cannot
    outlive a failed provision that left orphans reachable.
    """
    request_id = operation.request_id
    range_id = operation.range_id
    user_id = operation.user_id
    _remove_ngfw_attachments_for_destroy(user_id, range_id, operation.range_spec)
    # Authored intent never carried CIDRs; tear down the ones this range holds.
    realized_spec = _realized_range_spec_for_destroy(
        request_id, operation.range_spec, operation_id=operation.operation_id
    )
    vpn_revoked = False
    terraform_succeeded = False
    try:
        destroy_variables = _build_operation_variables(
            request_id,
            range_id,
            user_id,
            realized_spec,
            _operation_variable_context(operation),
        )
        range_terraform_runner.destroy_range(request_id, variables=destroy_variables, backend=operation.backend)
        _cleanup_openvpn_if_enabled(range_id, request_id, delete_identity=delete_vpn_identity)
        vpn_revoked = True
        terraform_succeeded = True
        logger.info("Cleaning up Terraform state...")
        range_terraform_runner.cleanup_range_state(request_id, operation.backend)
    finally:
        # Revoke issued remote-access credentials even on a failed destroy, so they
        # cannot outlive a failed provision that left orphan resources reachable.
        # Capture the failure class and log it below (in finally, not the handler):
        # logger.exception would attach a raw stack trace barred here (ADR-043-R5).
        revoke_failure: str | None = None
        if revoke_vpn_even_if_destroy_fails and not vpn_revoked:
            try:
                _cleanup_openvpn_if_enabled(range_id, request_id, delete_identity=delete_vpn_identity)
            except Exception as exc:
                revoke_failure = type(exc).__name__
        if revoke_failure is not None:
            logger.error(
                "Failed to revoke remote-access generation during compensation for range_id=%s (%s)",
                range_id,
                revoke_failure,
            )
        # Ownership (reservations, child projections) is released only behind the
        # confirmed-destroy postcondition; a failed destroy keeps it so a CIDR is
        # not reused while orphan resources still occupy it.
        if terraform_succeeded:
            _post_destroy_cleanup(request_id, range_id, operation_id=operation.operation_id)
        _maybe_pause_user_ngfw(user_id, range_id)


def _attempt_terraform_auto_cleanup(operation: RangeOperation) -> None:
    """Best-effort compensation destroy after a failed provision.

    Runs the shared teardown so orphaned resources are reclaimed through one
    lifecycle, but stays best-effort: failures are bounded-logged (no raw
    Terraform diagnostics, ADR-043-R5) with ownership retained and identity
    preserved for retry. The caller still records the range ``FAILED``.
    """
    logger.error(
        "Provision failed for range_id=%s request_id=%s - attempting compensation destroy...",
        operation.range_id,
        operation.request_id,
    )
    # Capture the failure class and log outside the handler: a raw exception body
    # carries Terraform stderr barred at this boundary (ADR-043-R5).
    failure: str | None = None
    try:
        _teardown_owned_range_resources(operation, delete_vpn_identity=False, revoke_vpn_even_if_destroy_fails=True)
    except Exception as exc:
        failure = type(exc).__name__
    if failure is None:
        logger.info("Compensation destroy succeeded for range_id=%s", operation.range_id)
    else:
        logger.error(
            "Compensation destroy FAILED for range_id=%s request_id=%s (%s); "
            "cloud resources and ownership retained for retry.",
            operation.range_id,
            operation.request_id,
            failure,
        )


def _dispatch_terraform_operation(kind: str, operation: RangeOperation) -> None:
    """Run the requested Terraform operation; raise ValueError for unknown ops.

    ``operation.backend`` (the #1666 per-operation ownership binding) routes
    destroy from persisted ownership; provision keeps its #1348 env-gated
    routing unchanged.
    """
    if kind == "up":
        _run_terraform_provision(operation)
    elif kind == "destroy":
        _run_terraform_destroy(operation)
    else:
        raise ValueError(f"Unknown operation: {kind}")


def _safe_failure_message(exc: Exception) -> str:
    """Return a bounded authored event message for a lifecycle failure."""
    if isinstance(exc, RangeCellContractError):
        return "Range-cell contract validation failed"
    return str(exc)[:1000]


def _resolve_remote_access_capability(
    range_data: dict[str, Any],
    operation: str,
) -> dict[str, object] | None:
    """Validate persisted remote-access authority before any operation mutation."""
    raw_capability = range_data.get("remote_access_capability")
    if raw_capability is None:
        return None
    capability = parse_openvpn_capability(raw_capability)
    if operation == "up":
        validate_openvpn_capability_window(capability)
        if not openvpn_access_enabled():
            raise prerequisite_error(
                "This range requests OpenVPN access, but the selected provider adapter is not configured to realize it"
            )
    return capability.as_dict()


def run_range_terraform(operation: str, request_id: str, *, operation_id: str | None = None) -> None:
    """Run Range Terraform operation (provision or destroy).

    ``operation_id`` is the ADR-043 canonical operation generation (#1834),
    threaded onto the argv only on the remote/drainer dispatch path; ``None``
    on local-dev runs.
    """
    logger.info("run_range_terraform: starting operation=%s request_id=%s", operation, request_id)

    range_data = get_range_data_by_request_id(request_id)
    range_id = range_data["range_id"]
    user_id = range_data["user_id"]
    range_spec = range_data.get("spec", {})
    # Resolve the per-operation backend binding once, at operation start, from the
    # persisted Range ownership (#1666). Reused for dispatch and, on a provision
    # failure, for the compensation destroy -- never re-resolved from the env
    # selector after a failure.
    operation_backend = resolve_operation_backend(range_data, operation, operation_id)
    # The trusted purpose travels with the binding (#1354). It is provision-only
    # authority: destroy never parses it, so a damaged or forward-version value
    # cannot strand owned resources. A provision must also still take the route
    # CMS admitted.
    operation_purpose = resolve_provision_purpose(range_data, operation)
    assert_provision_route(operation_backend, operation)

    range_operation: RangeOperation | None = None
    try:
        remote_access_capability = _resolve_remote_access_capability(range_data, operation)
        # Verify the producer-minted artifact before any NGFW or provider
        # operation. Other backends retain their existing legacy payload path.
        uses_gce = operation_backend == "gce" if operation_backend is not None else is_gce_range_cell_backend()
        scenario_artifact = validate_scenario_artifact(range_data.get("spec_envelope")) if uses_gce else None
        if operation == "up" and scenario_artifact is not None:
            validate_legacy_gce_composition(scenario_artifact, backend=operation_backend)

        if range_spec.get("ngfw", False):
            _ensure_ngfw_ready_for_provisioning(range_id, user_id)

        range_operation = RangeOperation(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
            range_spec=range_spec,
            scenario_artifact=scenario_artifact,
            backend=operation_backend,
            purpose=operation_purpose,
            remote_access_capability=remote_access_capability,
            operation_id=operation_id,
            egress_mode=range_data.get("egress_mode", "status-quo"),
        )
        _dispatch_terraform_operation(operation, range_operation)
    except Exception as e:
        error_msg = _safe_failure_message(e)
        logger.exception("Range Terraform operation failed: %s", error_msg)
        if operation == "up" and range_operation is not None:
            _attempt_terraform_auto_cleanup(range_operation)
        update_range_status(
            range_id=range_id,
            status=STATUS_FAILED,
            error_message=error_msg,
        )
        raise


def _run_terraform_provision(operation: RangeOperation) -> None:
    """Run Terraform apply for range, then run instance setup."""
    request_id = operation.request_id
    range_id = operation.range_id
    user_id = operation.user_id
    range_spec = operation.range_spec
    remote_access_capability = operation.remote_access_capability
    update_range_status(
        range_id=range_id,
        status=STATUS_PROVISIONING,
    )

    logger.info("Running terraform apply for range...")

    vpn_secret_ops = get_vpn_secret_ops() if remote_access_capability is not None else None
    vpn_preparation = (
        prepare_openvpn_access(
            request_id,
            range_id,
            user_id,
            range_spec,
            remote_access_capability,
            vpn_secret_ops,
        )
        if remote_access_capability is not None and vpn_secret_ops is not None
        else None
    )

    # Reservation produces an operation-local realization of the authored spec.
    # ``range_spec`` itself stays authored intent and is never written back
    # (ADR-043-R6), so the backend no longer decides whether to persist it --
    # nothing persists it.
    realized_spec = _reserve_range_subnet_cidrs(
        request_id,
        range_spec,
        operation_id=operation.operation_id,
    )
    spec_subnets = realized_spec.get("subnets", [])

    # Build backend-appropriate range variables from the realized spec. GCE range
    # cells receive a closed request around the persisted scenario artifact; AWS
    # receives Terraform variables.
    provision_variables = _build_operation_variables(
        request_id,
        range_id,
        user_id,
        realized_spec,
        _operation_variable_context(operation),
    )

    # Run the provider-routed apply, carrying the trusted purpose so the
    # provisioner's defense-in-depth policy denial sees real persisted state
    # rather than an unconditional live-fire default (#1354), and the persisted
    # backend so selector changes cannot reroute the operation (#1666).
    output_data = range_terraform_runner.apply_range(
        request_id,
        provision_variables,
        purpose=operation.purpose,
        backend=operation.backend,
    )
    vpn_access_binding = (
        finalize_openvpn_access(
            vpn_preparation,
            verify_openvpn_gateway(output_data.get("vpn_gateway")),
            vpn_secret_ops,
        )
        if vpn_preparation is not None and vpn_secret_ops is not None
        else None
    )

    subnets_output = output_data.get("subnets", {})
    instances_output = output_data.get("instances", [])
    # Non-secret per-range Polaris Bedrock agent role ARN (#1377); empty
    # string when polaris_agent_enabled was false or the backend has no
    # such output (e.g. GCP/GDC ranges).
    polaris_agent_role_arn = output_data.get("polaris_agent_role_arn") or ""
    # Log structure only. Terraform outputs can carry sensitive values
    # (generated passwords, SSH keys, tokens) and must never be dumped raw.
    logger.info(
        "Terraform apply produced %d subnet(s) and %d instance(s)",
        len(subnets_output),
        len(instances_output),
    )

    expected_subnet_names = {str(subnet_name) for subnet in spec_subnets if (subnet_name := subnet.get("name"))}
    _validate_provisioned_outputs(
        subnets=subnets_output,
        instances=instances_output,
        expected_subnet_names=expected_subnet_names,
    )

    _validate_ngfw_range_attachment(range_spec, user_id)
    _configure_ngfw_for_range(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        range_spec=realized_spec,
        spec_subnets=spec_subnets,
        subnets_output=subnets_output,
    )

    # Run instance setup (DC first, then others in parallel)
    logger.info("Running instance setup...")
    run_instance_setup(
        instances_output=instances_output,
        range_spec=range_spec,
        range_id=range_id,
        polaris_agent_role_arn=polaris_agent_role_arn,
    )

    # Write provisioned state to DB
    range_data = get_range_data_by_request_id(request_id)
    write_provisioned_state(
        range_id=range_id,
        subnets=subnets_output,
        instances=instances_output,
        ngfw_instance_id=range_data.get("ngfw_instance_id"),
        vpn_access_binding=vpn_access_binding,
        operation=OperationRef(request_id=request_id, operation_id=operation.operation_id),
    )

    update_range_status(range_id=range_id, status=STATUS_READY)


def _ensure_range_is_active(request_id: str, range_id: int) -> bool:
    """Return True if the range exists and is not already destroyed."""
    try:
        range_data = get_range_data_by_request_id(request_id)
    except ValueError as e:
        logger.warning("Range not found for request %s, skipping destroy: %s", request_id, e)
        return False
    if range_data.get("status") == STATUS_DESTROYED:
        logger.info("Range %d already destroyed, skipping", range_id)
        return False
    return True


def _run_terraform_destroy(operation: RangeOperation) -> None:
    """Run Terraform destroy for range.

    ``operation.backend`` is the #1666 per-operation ownership binding: teardown
    routes from the backend the range was provisioned on, not the current env
    selector, so a ``gdc -> gce`` deploy-selector flip cannot strand an existing
    GDC range.
    """
    request_id = operation.request_id
    range_id = operation.range_id
    if not _ensure_range_is_active(request_id, range_id):
        return

    logger.info("Running terraform destroy for range...")
    # An explicit destroy deletes the deterministic access identity; on failure
    # the shared helper propagates with ownership retained, so DESTROYED is not
    # recorded below.
    _teardown_owned_range_resources(operation, delete_vpn_identity=True)

    update_range_status(range_id=range_id, status=STATUS_DESTROYED)
