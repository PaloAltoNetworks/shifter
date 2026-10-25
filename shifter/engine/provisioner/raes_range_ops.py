"""RAES-native range lifecycle entry for the provisioner ``raes-range`` command.

Parallel to ``terraform_ops.run_range_terraform`` but for the RAES-native path
(ADR-031, default off behind the platform feature flag). It realizes the
serialized RAES plan into a real GCE range cell. It performs no cyberscript
scenario setup, NGFW attachment, or Vertex credential management -- those are
cyberscript/participant concerns. It invokes tenant subnet coordination only for
the GCE adapter's backend-owned realization of open portable network intent.

ADR-043 phase 5 (#1837) moved both sides of this path onto the operation
contract:

* **Inputs** come from the immutable operation-input projection, selected by the
  canonical ``operation_id``. The plan, the byte-free content-delivery bindings,
  and the tenant image candidates the plan can ask for all ride that one row --
  no ``mission_control_range`` / ``engine_raes_content_delivery_binding`` /
  ``engine_raes_image_mapping`` reads remain.
* **Outcomes** are appended as closed results on the operation contract. The
  Engine applier is the authoritative writer for range status and the RAES
  sidecar evidence, so this module publishes no lifecycle events: one operation
  generation has exactly one authoritative path.

Image/sizing is still resolved at realization from the authored RAES source
against the tenant-managed registry (ADR-032-R2) via the pure
``resolve_gce_image`` policy -- only the candidate rows now arrive by projection
rather than by direct SQL.
"""

from __future__ import annotations

import logging
from typing import Any

from shared.operation_results import MAX_DIAGNOSTIC_CHARS, ResultStep
from shared.raes.completion_evidence import build_completion_evidence
from shared.raes.operation_input import RaesOperationInput

from config import GCERangeCellConfig, load_gce_range_cell_config
from provisioner_db_appends import OperationRef, append_operation_step_result
from provisioner_db_operation_input import (
    RaesOperationRun,
    get_activation_operation_input,
    get_raes_operation_input,
)
from raes_gce_image import registry_image_resolver
from raes_gcp_apply import RaesGceApplyOptions, RaesGceDestroyOptions, apply_raes_range_cell, destroy_raes_range_cell
from raes_gcp_inventory import VERIFIED_ABSENT, inventory_raes_range_cell
from raes_gcp_network_allocation import (
    GceNetworkAllocation,
    RaesRealizationError,
)
from raes_gcp_network_allocation import (
    allocated_networks_for_destroy as _allocated_networks_for_destroy,
)
from raes_gcp_network_allocation import (
    allocated_networks_for_provision as _allocated_networks_for_provision,
)
from raes_openvpn import (
    cleanup_failed_provision_openvpn,
    cleanup_raes_openvpn,
    prepare_raes_openvpn,
    vpn_access_fragment,
    vpn_access_names,
)
from raes_plan import RaesPlan, parse_plan
from raes_range_contract import _classify_failure, _require_gce_live_fire_binding
from raes_range_members import realized_members as _realized_members
from raes_snapshot import snapshot_resources
from range_placement import resolve_range_cell_placement
from range_subnet_allocation import _release_subnet_allocations_best_effort

logger = logging.getLogger(__name__)
_GceNetworkAllocation = GceNetworkAllocation

#: The single closed failure code an RAES realization/teardown failure reports.
#: The bounded diagnostic rides the result payload; only this code reaches the
#: range's user-visible error text (ADR-043-R5).
_FAILURE_REASON_CODE = "cloud_operation_failed"

#: Reported when this generation's immutable input cannot be read or validated.
_INPUT_REASON_CODE = "dependency_unavailable"

#: Reported when the realization contract itself was violated (bad plan, missing proof).


#: Reported when a cloud operation exceeded its budget.


_RESOURCE = "raes-range"


class RaesGenerationError(RuntimeError):
    """An RAES operation was invoked without its canonical operation generation."""


def _config_for_range_placement(request_id: str, config: GCERangeCellConfig) -> GCERangeCellConfig:
    """Bind ``config`` to this range's realized zone before any plan/cloud work.

    The RAES lifecycle boundary is the symmetric counterpart of the legacy
    ``gcp_range_cells`` binding: it reads the zone chosen at range creation and
    stored on the row, so provision and destroy target the exact same zone and
    teardown never recomputes against a pool that may have changed. An empty stored
    zone returns the config unchanged, preserving single-region behaviour.
    """
    return resolve_range_cell_placement(request_id, config)


def _require_generation(request_id: str, operation_id: str | None, operation: str) -> tuple[OperationRef, str]:
    """Return the operation ref and its proven generation id, or refuse.

    A cut-over family has no non-contract path: with no generation there is no
    immutable input to realize from and no fence to report results against, so
    proceeding would mutate cloud resources the Engine cannot reconcile. The id
    is returned alongside the ref because ``OperationRef.operation_id`` is
    optional by contract, and every caller past this point needs the proven
    non-null value.
    """
    if not operation_id:
        raise RaesGenerationError(
            f"raes-range {operation} requires a canonical operation id; refusing to mutate cloud state without one"
        )
    return OperationRef(request_id=request_id, operation_id=operation_id), operation_id


def _report(ref: OperationRef, operation: str, step: ResultStep, payload: dict[str, Any]) -> None:
    """Append one closed result for this operation generation."""
    append_operation_step_result(ref, resource=_RESOURCE, operation=operation, step=step, result_payload=payload)


def _report_failure(
    ref: OperationRef, operation: str, diagnostic: str, reason_code: str = _FAILURE_REASON_CODE
) -> None:
    """Report terminal failure with a closed reason code and bounded diagnostic."""
    _report(
        ref,
        operation,
        ResultStep.RAES_TERMINAL_FAILED,
        {"reason_code": reason_code, "diagnostic": diagnostic[:MAX_DIAGNOSTIC_CHARS]},
    )


def _load_input(ref: OperationRef, operation_id: str, operation: str, request_id: str) -> RaesOperationRun:
    """Read and validate this generation's input, reporting failure if it cannot.

    An operation generation that never reports a terminal result is only visible
    through the inbox-lag signal (ADR-043-R7), leaving the range stuck until an
    operator notices. The generation comes from argv, so a bad input is still
    reportable -- and reporting it lets the applier fail the range explicitly.
    The provisional ref used for that report is argv-derived, which is safe: no
    cloud mutation has happened, and the applier fences the result on ownership
    before applying anything.

    The diagnostic is authored, not derived: the underlying error can carry a
    table name or driver text, which must not cross the result boundary.
    """
    try:
        return get_raes_operation_input(operation_id, request_id=request_id, operation=operation)
    except Exception:
        _report_failure(ref, operation, "operation input could not be read or validated", _INPUT_REASON_CODE)
        raise


def run_raes_range_provision(request_id: str, *, operation_id: str | None = None) -> None:
    """Realize the serialized RAES plan for a generation into a real GCE range cell.

    Reports ``running`` -> bounded runtime snapshot -> ``ready`` on the operation
    contract; the Engine applier turns those into range status, RAES sidecar
    evidence, audit, and the ADR-025 notification in one transaction.
    """
    operation = "provision"
    provisional_ref, generation = _require_generation(request_id, operation_id, operation)
    run = _load_input(provisional_ref, generation, operation, request_id)
    # Correlate every result from the identity the input row proved, not from
    # the argv pair that was merely asserted.
    ref = OperationRef(request_id=run.request_id, operation_id=run.operation_id)
    operation_input = run.input
    range_id = operation_input.legacy_range_id

    logger.info("Starting RAES range provision for request_id=%s", request_id)
    _report(ref, operation, ResultStep.RAES_PROVISION_RUNNING, {"raes_status": "running"})
    network_allocation: GceNetworkAllocation | None = None
    raes_plan: RaesPlan | None = None
    config: GCERangeCellConfig | None = None
    pre_mutation_release_attempted = False
    try:
        from model_enrollment import load_model_enrollment
        from runtime_plugin_execution import load_guest_plugin_plans

        plugin_plans = load_guest_plugin_plans(run)
        enrollment = load_model_enrollment(run)
        raes_plan = parse_plan(operation_input.plan)
        if operation_input.range_backend == "ec2":
            from raes_ec2_runtime import provision_ec2_run

            if operation_input.remote_access is not None:
                # The EC2 shared pool is #2481; never launch without it silently.
                raise RaesRealizationError("OpenVPN access is not realized by the EC2 range backend")
            apply_result = provision_ec2_run(run, plugin_plans, enrollment)
        else:
            backend = _require_gce_live_fire_binding(operation_input)
            config = load_gce_range_cell_config(backend=backend)
            config = _config_for_range_placement(request_id, config)
            raes_plan = parse_plan(operation_input.plan)
            network_allocation = _allocated_networks_for_provision(
                request_id,
                generation,
                raes_plan,
                config,
            )
            openvpn = prepare_raes_openvpn(run.request_id, range_id, raes_plan, operation_input.remote_access)

            def release_pre_mutation_allocation() -> None:
                """Release this generation's reservation before provider mutation."""
                nonlocal pre_mutation_release_attempted
                pre_mutation_release_attempted = True
                _release_subnet_allocations_best_effort(request_id, operation_id=generation)

            apply_result = apply_raes_range_cell(
                request_id,
                range_id,
                raes_plan,
                registry_image_resolver(operation_input),
                options=RaesGceApplyOptions(
                    config=config,
                    egress_mode=operation_input.egress_mode,
                    allocated_network_cidrs=network_allocation.require_available(),
                    runtime_plugin=plugin_plans.execute if plugin_plans is not None else None,
                    model_enrollment=enrollment.execute if enrollment is not None else None,
                    model_broker=enrollment.gce_egress_capability() if enrollment is not None else None,
                    on_pre_mutation_failure=(
                        release_pre_mutation_allocation if network_allocation.network_cidrs else None
                    ),
                    openvpn=openvpn,
                ),
                delivery_bindings=operation_input.binding_transport(),
                access_bindings=operation_input.access_binding_transport(),
            )
        verified_addresses = apply_result.get("composition_verified_addresses")
        if not isinstance(verified_addresses, list) or not all(
            isinstance(address, str) for address in verified_addresses
        ):
            raise RaesRealizationError("composition verification proof is invalid")
        resources = snapshot_resources(raes_plan, set(verified_addresses))
        members = _realized_members(apply_result)
        completion = build_completion_evidence(
            operation_input.plan,
            resources=resources,
            operating_systems=apply_result.get("operating_systems"),
            compute_substrates=apply_result.get("compute_substrates"),
            generation_id=run.operation_id,
        )
    except Exception as exc:
        _release_failed_provision_allocation(run, raes_plan, config, network_allocation, pre_mutation_release_attempted)
        cleanup_failed_provision_openvpn(run.request_id, run.input.legacy_range_id, run.input.remote_access)
        reason_code, diagnostic = _classify_failure(exc, "raes range provision")
        logger.error("RAES range provision failed for request_id=%s", request_id)
        _report_failure(ref, operation, diagnostic, reason_code)
        raise
    # The realized member/access projection rides the terminal result itself, so
    # the Engine validates it and transitions READY in one transaction against
    # this generation's own state (#1710, ADR-032-R10). So does the owner-free
    # OpenVPN realization, which the Engine binds to the range owner (#2030).
    _report_realized_provision(
        ref,
        request_id,
        resources,
        {
            "raes_status": "succeeded",
            "members": members,
            "completion": completion,
            **vpn_access_fragment(apply_result.get("vpn_access")),
        },
    )


def _report_realized_provision(
    ref: OperationRef, request_id: str, resources: list[dict[str, str]], ready: dict[str, Any]
) -> None:
    """Append the realized snapshot and terminal ready result for a provision generation."""
    operation = "provision"
    try:
        _report(ref, operation, ResultStep.RAES_PROVISION_SNAPSHOT, {"resources": resources})
        _report(ref, operation, ResultStep.RAES_TERMINAL_READY, ready)
    except Exception as exc:
        # The appends validate the result contract. A rejected realized result must
        # still end the generation with a terminal failure; otherwise the range stays
        # PROVISIONING indefinitely and occupies the owner's active-range slot. The
        # cloud resources are realized, so allocations are not released here: the
        # failed range is torn down through the normal destroy operation, which also
        # removes its OpenVPN access.
        reason_code, diagnostic = _classify_failure(exc, "raes range provision result")
        logger.error("RAES range provision result was rejected for request_id=%s", request_id)
        _report_failure(ref, operation, diagnostic, reason_code)
        raise


def _release_failed_provision_allocation(
    run: RaesOperationRun,
    raes_plan: RaesPlan | None,
    config: GCERangeCellConfig | None,
    network_allocation: GceNetworkAllocation | None,
    pre_mutation_release_attempted: bool,
) -> None:
    """Release failed GCE addressing only after proving original resources absent."""
    if (
        network_allocation is not None
        and network_allocation.network_cidrs
        and raes_plan is not None
        and config is not None
        and not pre_mutation_release_attempted
    ):
        cleanup_inventory = _raes_cleanup_inventory(
            run.request_id,
            run.input.legacy_range_id,
            raes_plan,
            _destroy_options(config, network_allocation, run.input),
        )
        if cleanup_inventory.get("outcome") == VERIFIED_ABSENT:
            _release_subnet_allocations_best_effort(run.request_id, operation_id=run.operation_id)


def run_raes_range_activate(request_id: str, *, operation_id: str | None = None) -> None:
    """Hand a claimed warm generation to its claimant (#28).

    Scrubs every pre-claim credential/access identity, realizes the claimant's
    fresh access, and negatively verifies the pre-claim access is revoked, then
    reports ``running`` -> snapshot -> ``ready`` with the claimant's realized
    member/access projection. Any failure reports a terminal failure with a closed
    reason code; the Engine applier fails the generation and it is retired through
    the canonical destroy lifecycle rather than handed over.
    """
    from uuid import UUID

    from raes_gcp_activate import activate_raes_range_cell, default_activation_ops

    operation = "activate"
    provisional_ref, generation = _require_generation(request_id, operation_id, operation)
    try:
        run = get_activation_operation_input(generation, request_id=request_id)
    except Exception:
        _report_failure(
            provisional_ref, operation, "operation input could not be read or validated", _INPUT_REASON_CODE
        )
        raise
    ref = OperationRef(request_id=run.request_id, operation_id=run.operation_id)
    activation = run.input

    logger.info("Starting RAES range activation for request_id=%s", request_id)
    _report(ref, operation, ResultStep.RAES_ACTIVATE_RUNNING, {"raes_status": "running"})
    try:
        operation_input = activation.raes_input
        if operation_input.runtime_plugin is not None:
            raise RaesRealizationError("Runtime plugin warm activation is not supported")
        backend = _require_gce_live_fire_binding(operation_input)
        config = _config_for_range_placement(request_id, load_gce_range_cell_config(backend=backend))
        raes_plan = parse_plan(operation_input.plan)
        network_allocation = _allocated_networks_for_destroy(
            request_id,
            run.operation_id,
            raes_plan,
            config,
        )
        # The claimant's OpenVPN credentials, keyed on the range's request id like
        # a cold provision; the warm-prepare generation never held any (#2030).
        openvpn = prepare_raes_openvpn(
            run.request_id, activation.legacy_range_id, raes_plan, operation_input.remote_access
        )
        result = activate_raes_range_cell(
            activation=activation,
            prepared_generation=UUID(activation.prepared_generation_fence),
            activate_generation=UUID(run.operation_id),
            ops=default_activation_ops(
                config=config,
                allocated_network_cidrs=network_allocation.require_available(),
                openvpn=openvpn,
            ),
        )
        resources = result.completion["resources"]
    except Exception as exc:
        reason_code, diagnostic = _classify_failure(exc, "raes range activate")
        logger.error("RAES range activation failed for request_id=%s", request_id)
        _report_failure(ref, operation, diagnostic, reason_code)
        raise
    _report(ref, operation, ResultStep.RAES_ACTIVATE_SNAPSHOT, {"resources": resources})
    _report(
        ref,
        operation,
        ResultStep.RAES_TERMINAL_READY,
        {
            "raes_status": "succeeded",
            "members": result.members,
            "completion": result.completion,
            **vpn_access_fragment(result.vpn_access),
        },
    )


def _destroy_options(
    config: GCERangeCellConfig, network_allocation: GceNetworkAllocation, operation_input: RaesOperationInput
) -> RaesGceDestroyOptions:
    """Return the reconstructive destroy options shared by teardown and its inventory."""
    return RaesGceDestroyOptions(
        config=config,
        allocated_network_cidrs=network_allocation.network_cidrs or None,
        reconstruct_without_allocation=network_allocation.required and not network_allocation.network_cidrs,
        remote_access=vpn_access_names(operation_input.remote_access),
    )


def _raes_cleanup_inventory(
    request_id: str, range_id: int, raes_plan: RaesPlan, options: RaesGceDestroyOptions
) -> dict[str, Any]:
    """Inventory owned resources after a successful destroy; never fail the terminal report.

    A failed inventory yields ``INCOMPLETE`` (unknown, never an empty success), so
    the destroy still terminalizes but no consumer treats it as verified cleanup.
    """
    try:
        return inventory_raes_range_cell(request_id, range_id, raes_plan, options)
    except Exception:
        logger.exception("RAES cleanup inventory failed for request_id=%s", request_id)
        return {"outcome": "INCOMPLETE", "residual_categories": [], "scope": {}}


def run_raes_range_destroy(request_id: str, *, operation_id: str | None = None) -> None:
    """Tear down every GCE resource owned by an RAES range cell for a generation."""
    operation = "destroy"
    provisional_ref, generation = _require_generation(request_id, operation_id, operation)
    run = _load_input(provisional_ref, generation, operation, request_id)
    ref = OperationRef(request_id=run.request_id, operation_id=run.operation_id)
    operation_input = run.input
    range_id = operation_input.legacy_range_id

    logger.info("Starting RAES range destroy for request_id=%s", request_id)
    _report(ref, operation, ResultStep.RAES_DESTROY_RUNNING, {"raes_status": "running"})
    try:
        if operation_input.range_backend == "ec2":
            from raes_ec2_runtime import destroy_ec2_run

            cleanup_inventory = destroy_ec2_run(run)
            _report(
                ref,
                operation,
                ResultStep.RAES_TERMINAL_DESTROYED,
                {"raes_status": "succeeded", "cleanup_inventory": cleanup_inventory},
            )
            return
        backend = _require_gce_live_fire_binding(operation_input)
        config = load_gce_range_cell_config(backend=backend)
        config = _config_for_range_placement(request_id, config)
        raes_plan = parse_plan(operation_input.plan, cleanup_only=True)
        network_allocation = _allocated_networks_for_destroy(
            request_id,
            generation,
            raes_plan,
            config,
        )
        destroy_options = _destroy_options(config, network_allocation, operation_input)
        destroy_raes_range_cell(request_id, range_id, raes_plan, destroy_options)
        # The gateway is gone; delete the generation's OpenVPN credentials (#2030).
        cleanup_raes_openvpn(run.request_id, range_id, operation_input.remote_access)
    except Exception as exc:
        reason_code, diagnostic = _classify_failure(exc, "raes range destroy")
        logger.error("RAES range destroy failed for request_id=%s", request_id)
        _report_failure(ref, operation, diagnostic, reason_code)
        raise
    # Independent inventory/readback of owned resources -- verified cleanup requires
    # this evidence, not the delete loop completing (#2086, ADR-063-R4/R5). The
    # reservation remains held until absence is proven so another range cannot
    # reuse an occupied CIDR after a partial or unreadable cleanup.
    cleanup_inventory = _raes_cleanup_inventory(request_id, range_id, raes_plan, destroy_options)
    if network_allocation.network_cidrs and cleanup_inventory.get("outcome") == VERIFIED_ABSENT:
        _release_subnet_allocations_best_effort(request_id, operation_id=generation)
    _report(
        ref,
        operation,
        ResultStep.RAES_TERMINAL_DESTROYED,
        {"raes_status": "succeeded", "cleanup_inventory": cleanup_inventory},
    )
