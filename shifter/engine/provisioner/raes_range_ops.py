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
from collections.abc import Callable
from typing import Any

from shared.operation_results import MAX_DIAGNOSTIC_CHARS, ResultStep
from shared.raes.completion_evidence import build_completion_evidence
from shared.raes.operation_input import RaesOperationInput, image_lookup_key
from shared.range_instantiation_policy import (
    POLICY_DENIAL_CODE,
    PREREQUISITE_DENIAL_CODE,
    InstantiationPurpose,
    evaluate_gcp_backend_admission,
)

from cloud.exceptions import CloudError
from config import GCERangeCellConfig, GCERangeImageProfile, load_gce_range_cell_config
from provisioner_db_appends import OperationRef, append_operation_step_result
from provisioner_db_operation_input import (
    RaesOperationRun,
    get_activation_operation_input,
    get_raes_operation_input,
)
from raes_gce_image import resolve_gce_image, resolve_gce_image_from_binding
from raes_gcp_apply import RaesGceApplyOptions, RaesGceDestroyOptions, apply_raes_range_cell, destroy_raes_range_cell
from raes_gcp_inventory import inventory_raes_range_cell
from raes_gcp_network_allocation import (
    GceNetworkAllocation,
    RaesRealizationError,
)
from raes_gcp_network_allocation import (
    allocated_open_network_for_destroy as _allocated_open_network_for_destroy,
)
from raes_gcp_network_allocation import (
    allocated_open_network_for_provision as _allocated_open_network_for_provision,
)
from raes_plan import RaesPlan, RaesPlanNode, parse_plan
from raes_snapshot import snapshot_resources
from range_placement import resolve_range_cell_placement
from range_subnet_allocation import _release_subnet_allocations_best_effort

logger = logging.getLogger(__name__)
_GceNetworkAllocation = GceNetworkAllocation

#: Registry provider key for the GCE realization backend (engine_raes_image_mapping).
_GCE_REGISTRY_PROVIDER = "gce"

#: The single closed failure code an RAES realization/teardown failure reports.
#: The bounded diagnostic rides the result payload; only this code reaches the
#: range's user-visible error text (ADR-043-R5).
_FAILURE_REASON_CODE = "cloud_operation_failed"

#: Reported when this generation's immutable input cannot be read or validated.
_INPUT_REASON_CODE = "dependency_unavailable"

#: Reported when the realization contract itself was violated (bad plan, missing proof).
_INVALID_STATE_REASON_CODE = "invalid_state"

#: Reported when a cloud operation exceeded its budget.
_TIMEOUT_REASON_CODE = "cloud_timeout"

_RESOURCE = "raes-range"


class RaesGenerationError(RuntimeError):
    """An RAES operation was invoked without its canonical operation generation."""


def _binding_error(message: str, code: str) -> CloudError:
    """Return an authored lifecycle failure with a stable classification."""
    error = CloudError(message)
    error.code = code
    return error


def _require_gce_live_fire_binding(operation_input: RaesOperationInput) -> str:
    """Validate the projected ownership/purpose pair for a normal RAES range."""
    raw_backend = operation_input.range_backend
    if not raw_backend:
        raise _binding_error(
            "RAES GCP range ownership binding is missing",
            PREREQUISITE_DENIAL_CODE,
        )
    try:
        purpose = InstantiationPurpose(operation_input.instantiation_purpose)
    except (TypeError, ValueError):
        raise _binding_error(
            "RAES GCP range instantiation purpose is missing or invalid",
            PREREQUISITE_DENIAL_CODE,
        ) from None
    if purpose is not InstantiationPurpose.LIVE_FIRE:
        raise _binding_error(
            "Normal RAES GCP ranges require the live_fire instantiation purpose",
            POLICY_DENIAL_CODE,
        )
    admission = evaluate_gcp_backend_admission(raw_backend, None, purpose)
    if not admission.admitted:
        raise _binding_error(admission.reason, admission.code)
    return admission.backend


def _config_for_range_placement(request_id: str, config: GCERangeCellConfig) -> GCERangeCellConfig:
    """Bind ``config`` to this range's realized zone before any plan/cloud work.

    The RAES lifecycle boundary is the symmetric counterpart of the legacy
    ``gcp_range_cells`` binding: it reads the zone chosen at range creation and
    stored on the row, so provision and destroy target the exact same zone and
    teardown never recomputes against a pool that may have changed. An empty stored
    zone returns the config unchanged, preserving single-region behaviour.
    """
    return resolve_range_cell_placement(request_id, config)


def _registry_resolver(operation_input: RaesOperationInput) -> Callable[[RaesPlanNode], GCERangeImageProfile]:
    """Return an image resolver bound to the projected candidates + GCE policy."""

    def resolve(node: RaesPlanNode) -> GCERangeImageProfile:
        """Resolve one node's image profile: a fenced artifact binding first, else the registry projection."""
        # A generation-fenced artifact binding means the Engine already resolved
        # this node's authored artifact requirement to an exact backend image at
        # launch; realize it verbatim and never re-resolve (ADR-034-R8). Only a
        # node with no artifact requirement falls through to the legacy
        # source-alias registry projection.
        binding = operation_input.artifact_binding_for(node.address)
        if binding is not None:
            return resolve_gce_image_from_binding(node, binding)
        # The lookup key rule is shared with the Engine that scoped the
        # projection; deriving it separately here is what would make an image
        # silently go missing.
        name = image_lookup_key(
            source_name=node.image.name if node.image else None,
            os_family=node.os_family,
        )
        candidates = operation_input.image_candidates_for(_GCE_REGISTRY_PROVIDER, name) if name else []
        return resolve_gce_image(node, candidates)

    return resolve


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


def _classify_failure(exc: BaseException, stage: str) -> tuple[str, str]:
    """Map a realization failure onto an authored reason code and diagnostic.

    The exception *message* must never cross this boundary. RAES failures travel
    through cloud-provider, storage, content-delivery, and guest-realization
    code whose messages can carry provider response bodies, resource ids,
    storage references, signed URLs, and guest output; the result inbox is a
    durable channel readable by anyone permitted to inspect diagnostics, and an
    authenticated range author can deliberately provoke failures to populate it.
    Truncation bounds size, not confidentiality, and ``safe_log_value`` is
    injection defence, not redaction (ADR-043-R5).

    The exception *type* is a code identifier rather than runtime data, so it
    crosses to keep the channel useful for triage. Full context stays in the
    provisioner's own logs, where the raw error is re-raised to the task runner.
    """
    if isinstance(exc, RaesRealizationError):
        # Authored by this module, so its text is already safe to report.
        return _INVALID_STATE_REASON_CODE, f"{stage}: {exc}"
    if isinstance(exc, TimeoutError):
        return _TIMEOUT_REASON_CODE, f"{stage} timed out ({type(exc).__name__})"
    return _FAILURE_REASON_CODE, f"{stage} failed ({type(exc).__name__})"


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
    try:
        backend = _require_gce_live_fire_binding(operation_input)
        config = load_gce_range_cell_config(backend=backend)
        config = _config_for_range_placement(request_id, config)
        raes_plan = parse_plan(operation_input.plan)
        network_allocation = _allocated_open_network_for_provision(
            request_id,
            generation,
            raes_plan,
            config,
        )
        apply_result = apply_raes_range_cell(
            request_id,
            range_id,
            raes_plan,
            _registry_resolver(operation_input),
            options=RaesGceApplyOptions(
                config=config,
                egress_mode=operation_input.egress_mode,
                allocated_network_cidr=network_allocation.require_available(),
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
        reason_code, diagnostic = _classify_failure(exc, "raes range provision")
        logger.error("RAES range provision failed for request_id=%s", request_id)
        _report_failure(ref, operation, diagnostic, reason_code)
        raise
    _report(ref, operation, ResultStep.RAES_PROVISION_SNAPSHOT, {"resources": resources})
    # The realized member/access projection rides the terminal result itself, so
    # the Engine validates it and transitions READY in one transaction against
    # this generation's own state (#1710, ADR-032-R10).
    _report(
        ref,
        operation,
        ResultStep.RAES_TERMINAL_READY,
        {"raes_status": "succeeded", "members": members, "completion": completion},
    )


def _realized_members(apply_result: dict[str, object]) -> list[dict[str, object]]:
    """Project realized instances into the bounded member/access result (#1710).

    Carries only what ``Range.provisioned_instances`` needs for the portal to
    authorize and dial, and secret *references* only -- never a credential value,
    the reserved management secret, or a raw provider response.
    """
    instances = apply_result.get("instances")
    if not isinstance(instances, list):
        raise RaesRealizationError("realized instance outputs are invalid")
    members: list[dict[str, object]] = []
    for instance in instances:
        if not isinstance(instance, dict):
            raise RaesRealizationError("realized instance outputs are invalid")
        channels = list(instance.get("participant_access_channels") or [])
        member: dict[str, object] = {
            "uuid": str(instance.get("uuid", "")),
            "name": str(instance.get("name", "")),
            "os_type": str(instance.get("os", "")),
            "private_ip": str(instance.get("private_ip", "")),
            "instance_id": str(instance.get("instance_id", "")),
            "subnet_name": str(instance.get("subnet_name", "")),
            "participant_access_channels": channels,
            "participant_access_usernames": dict(instance.get("participant_access_usernames") or {}),
        }
        host_public_key = str(instance.get("gcp_host_public_key", ""))
        if host_public_key:
            member["host_public_key"] = host_public_key
        sftp_root_directory = str(instance.get("sftp_root_directory", ""))
        if sftp_root_directory:
            member["sftp_root_directory"] = sftp_root_directory
        for channel, key in (("ssh", "ssh_key_secret_arn"), ("rdp", "rdp_password_secret_arn")):
            if channel in channels:
                member[key] = str(instance.get(key, ""))
        members.append(member)
    return members


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
        backend = _require_gce_live_fire_binding(operation_input)
        config = _config_for_range_placement(request_id, load_gce_range_cell_config(backend=backend))
        raes_plan = parse_plan(operation_input.plan)
        network_allocation = _allocated_open_network_for_destroy(
            request_id,
            activation.prepared_generation_fence,
            raes_plan,
            config,
        )
        result = activate_raes_range_cell(
            activation=activation,
            prepared_generation=UUID(activation.prepared_generation_fence),
            activate_generation=UUID(run.operation_id),
            ops=default_activation_ops(
                config=config,
                allocated_network_cidr=network_allocation.require_available(),
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
        {"raes_status": "succeeded", "members": result.members, "completion": result.completion},
    )


def _raes_cleanup_inventory(
    request_id: str, range_id: int, raes_plan: RaesPlan, config: GCERangeCellConfig
) -> dict[str, Any]:
    """Inventory owned resources after a successful destroy; never fail the terminal report.

    A failed inventory yields ``INCOMPLETE`` (unknown, never an empty success), so
    the destroy still terminalizes but no consumer treats it as verified cleanup.
    """
    try:
        return inventory_raes_range_cell(request_id, range_id, raes_plan, config=config)
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
        backend = _require_gce_live_fire_binding(operation_input)
        config = load_gce_range_cell_config(backend=backend)
        config = _config_for_range_placement(request_id, config)
        raes_plan = parse_plan(operation_input.plan, cleanup_only=True)
        network_allocation = _allocated_open_network_for_destroy(
            request_id,
            generation,
            raes_plan,
            config,
        )
        destroy_raes_range_cell(
            request_id,
            range_id,
            raes_plan,
            RaesGceDestroyOptions(
                config=config,
                allocated_network_cidr=network_allocation.cidr,
                reconstruct_without_allocation=network_allocation.required and network_allocation.cidr is None,
            ),
        )
    except Exception as exc:
        reason_code, diagnostic = _classify_failure(exc, "raes range destroy")
        logger.error("RAES range destroy failed for request_id=%s", request_id)
        _report_failure(ref, operation, diagnostic, reason_code)
        raise
    if network_allocation.cidr is not None:
        _release_subnet_allocations_best_effort(request_id, operation_id=generation)
    # Independent inventory/readback of owned resources -- verified cleanup requires
    # this evidence, not the delete loop completing (#2086, ADR-063-R4/R5). Run after
    # subnet release so the readback reflects the true final state.
    cleanup_inventory = _raes_cleanup_inventory(request_id, range_id, raes_plan, config)
    _report(
        ref,
        operation,
        ResultStep.RAES_TERMINAL_DESTROYED,
        {"raes_status": "succeeded", "cleanup_inventory": cleanup_inventory},
    )
