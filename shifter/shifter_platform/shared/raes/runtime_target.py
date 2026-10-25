"""Shifter's RAES RuntimeTarget provisioning backend (ADR-031, ADR-032).

Supersedes the #1262 ``scenario_ref`` passthrough. It validates a compiled RAES
``ProvisioningPlan`` against the declared capability envelope, then dispatches
the **serialized plan itself** through an injected
:class:`~shared.raes.dispatch_port.ShifterProvisioningDispatchPort`. Shifter
introduces no parallel SDL and no re-modeled provisioning schema; the realization
side (engine/provisioner) reads the RAES plan payloads directly via accessors
that mirror the reference RAES backends.

Validation, enqueue, and apply share the same pure admission step. Native
launch uses an enqueue receipt. Synchronous apply succeeds only after completed
provider and guest evidence has passed the public RAE realization boundary.

Only :mod:`shared.raes` may import ``raes`` (ADR-031-R1 / ADR-024); realization consumes the serialized plan as
plain data via the injected dispatch port.

The capability-envelope half -- the supported resource-type vocabulary, the
payload accessors, and the per-resource envelope diagnostics -- lives in
:mod:`shared.raes._runtime_target_envelope` (Sonar S104) and is re-exported here,
so this module's public surface is unchanged.
"""

from __future__ import annotations

import importlib.metadata
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from raes_backend_protocols.capabilities import BackendManifest, ProvisionerCapabilities
from raes_contracts.diagnostics import Diagnostic
from raes_contracts.planning import PlannedResource, ProvisioningPlan, RuntimeDomain
from raes_contracts.realization_envelope import BackendRealizationEnvelopeModel
from raes_contracts.runtime_state import ApplyResult, RuntimeSnapshot
from raes_runtime.registry import BackendRegistry, RuntimeTarget, RuntimeTargetComponents

from shared.log_sanitize import safe_log_value
from shared.raes._runtime_target_envelope import (
    DOMAIN_CONTROLLER_PLACEMENT_RESOURCE_TYPE,
    NETWORK_RESOURCE_TYPE,
    NODE_RESOURCE_TYPE,
    SUPPORTED_RESOURCE_TYPES,
    _capability_envelope_diagnostics,
    _diagnostic,
    _network_lookup,
    _network_refs,
)
from shared.raes.composition_envelope import account_operation_diagnostics, feature_operation_diagnostics
from shared.raes.contracts import RAES_PROVISIONING_PLAN_CONTRACT_VERSION, SHIFTER_BACKEND_NAME
from shared.raes.dispatch_port import ShifterDispatchResult, ShifterProvisioningDispatchPort
from shared.raes.domain_topology import (
    backend_effect_domain_topology_diagnostics,
    sanitized_domain_topology_diagnostics,
)
from shared.raes.manifest import SHIFTER_PROVISIONER_CAPABILITIES, create_shifter_backend_manifest
from shared.raes.network_addressing import static_network_address_diagnostics
from shared.raes.participant_access import ParticipantAccessBinding
from shared.raes.realization import create_shifter_realization_envelope

__all__ = [
    "DOMAIN_CONTROLLER_PLACEMENT_RESOURCE_TYPE",
    "NETWORK_RESOURCE_TYPE",
    "NODE_RESOURCE_TYPE",
    "RAES_PROVISIONING_PLAN_KIND",
    "SUPPORTED_RESOURCE_TYPES",
    "ShifterProvisioner",
    "create_shifter_backend_components",
    "create_shifter_backend_target",
    "interpret_provisioning_plan",
    "is_raes_provisioning_plan",
    "register_shifter_backend",
    "serialize_provisioning_plan",
]

#: Discriminator for the serialized plan persisted in ``range_config`` so the
#: provisioner ``raes-range`` path can tell it apart from a cyberscript envelope.
RAES_PROVISIONING_PLAN_KIND = "raes_provisioning_plan"


def is_raes_provisioning_plan(range_config: object) -> bool:
    """Return whether a persisted ``Range.range_config`` is an RAES provisioning plan.

    The RAES-native create path stores a serialized ProvisioningPlan whose
    top-level ``kind`` is :data:`RAES_PROVISIONING_PLAN_KIND`; the legacy
    cyberscript path stores a wrapped-spec envelope with no top-level ``kind``.
    Provision/status/teardown for an existing range is selected from this
    persisted, validated discriminator -- never from the current catalog selector
    or capability flag (ADR-031-R6). Anything that is not positively an RAES plan
    (``None``, a cyberscript envelope, an unknown ``kind``) is treated as legacy.
    """
    return isinstance(range_config, dict) and range_config.get("kind") == RAES_PROVISIONING_PLAN_KIND


# --- serialization (the artifact that crosses the platform -> provisioner boundary) ---


def _raes_version() -> str:
    """Return the installed raes version (recorded on the serialized plan).

    raes is a runtime dependency imported at this module's top, so it is
    always installed by the time this runs.
    """
    return importlib.metadata.version("raes")


def serialize_provisioning_plan(
    plan: ProvisioningPlan, *, backend_realization_envelope: object | None = None
) -> dict[str, Any]:
    """Serialize the PROVISIONING resources of a compiled RAES plan to JSON-safe dict.

    The payloads are the RAES plan's own payloads, verbatim -- this is
    serialization for the cross-process boundary, not a re-modeled schema
    (ADR-032-R3). A ``kind`` discriminator lets the provisioner distinguish the
    serialized plan from a cyberscript envelope in ``range_config``; the
    ``contract_version`` declares the transport envelope shape the consumer must
    support (ADR-032-R7); and the ``raes_version`` records the producer
    (raes) version the plan was compiled against.
    """
    resources: dict[str, Any] = {}
    for address, resource in plan.resources.items():
        if resource.domain != RuntimeDomain.PROVISIONING:
            continue
        resources[address] = {
            "address": resource.address,
            "domain": resource.domain.value,
            "resource_type": resource.resource_type,
            "payload": resource.payload,
            "ordering_dependencies": list(resource.ordering_dependencies),
            "refresh_dependencies": list(resource.refresh_dependencies),
        }
    envelope = {
        "kind": RAES_PROVISIONING_PLAN_KIND,
        "contract_version": RAES_PROVISIONING_PLAN_CONTRACT_VERSION,
        "raes_version": _raes_version(),
        "resources": resources,
        "operations": [_plan_json(item) for item in plan.operations],
        "realization_authority": [_plan_json(item) for item in plan.realization_authority],
        "realization_envelope": _plan_json(plan.realization_envelope),
        "backend_realization_envelope": _plan_json(backend_realization_envelope),
        "realization_constraints": [_plan_json(item) for item in plan.realization_constraints],
        "operation_id": plan.operation_id,
    }
    # Unknown values must fail serialization; their string representation is
    # neither the authored contract nor a safe cross-process substitute.
    return json.loads(json.dumps(envelope, allow_nan=False))


def _plan_json(value: object) -> object:
    """Serialize public contract objects without inventing string fallbacks."""
    result: object
    if isinstance(value, BaseModel):
        result = value.model_dump(mode="json")
    elif is_dataclass(value) and not isinstance(value, type):
        result = _plan_json(asdict(value))
    elif isinstance(value, Enum):
        result = value.value
    elif isinstance(value, dict):
        result = {key: _plan_json(item) for key, item in value.items()}
    elif isinstance(value, tuple | list):
        result = [_plan_json(item) for item in value]
    else:
        result = value
    return result


# --- interpret (validate the plan, then serialize it) ---


def _unknown_network_diagnostics(
    node_resources: list[tuple[PlannedResource, Mapping[str, object]]], lookup: dict[str, str]
) -> list[Diagnostic]:
    """Return diagnostics for node network refs that no declared network resolves."""
    diagnostics: list[Diagnostic] = []
    for resource, payload in node_resources:
        for ref in _network_refs(payload):
            if lookup.get(ref) is None:
                diagnostics.append(
                    _diagnostic(
                        "shifter-provisioner.unknown-network",
                        resource.address,
                        f"node references network '{ref}' not declared in this plan",
                    )
                )
    return diagnostics


def _extend_unique_diagnostics(diagnostics: list[Diagnostic], additions: list[Diagnostic]) -> None:
    """Append diagnostics not already present by code, address, and message."""
    seen = {(item.code, item.address, item.message) for item in diagnostics}
    for diagnostic in additions:
        key = (diagnostic.code, diagnostic.address, diagnostic.message)
        if key not in seen:
            seen.add(key)
            diagnostics.append(diagnostic)


def interpret_provisioning_plan(
    plan: ProvisioningPlan,
    *,
    capabilities: ProvisionerCapabilities | None = None,
    snapshot: RuntimeSnapshot | None = None,
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """Validate a compiled RAES provisioning plan and return its serialized form.

    Pure (no I/O). Returns ``(serialized_plan, diagnostics)`` on a fully-supported
    plan, or ``(None, diagnostics)`` with at least one ERROR diagnostic when any
    plan term is outside the backend capability envelope or references a network
    not declared in the plan.
    """
    capabilities = capabilities or SHIFTER_PROVISIONER_CAPABILITIES
    provisioning = [
        resource
        for resource in sorted(plan.resources.values(), key=lambda item: item.address)
        if resource.domain == RuntimeDomain.PROVISIONING
    ]
    diagnostics = _capability_envelope_diagnostics(provisioning, capabilities)
    if any(
        operation.address not in plan.resources or operation.action.value not in {"create", "unchanged"}
        for operation in plan.operations
    ):
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.incremental-unsupported",
                "plan",
                "native dispatch requires a complete fresh provisioning plan",
            )
        )

    diagnostics.extend(sanitized_domain_topology_diagnostics(plan, capabilities, snapshot))
    diagnostics.extend(backend_effect_domain_topology_diagnostics(plan, snapshot))

    network_resources = [
        (r, r.payload)
        for r in provisioning
        if r.resource_type == NETWORK_RESOURCE_TYPE and isinstance(r.payload, Mapping)
    ]
    node_resources = [
        (r, r.payload) for r in provisioning if r.resource_type == NODE_RESOURCE_TYPE and isinstance(r.payload, Mapping)
    ]
    diagnostics.extend(_unknown_network_diagnostics(node_resources, _network_lookup(network_resources)))
    diagnostics.extend(static_network_address_diagnostics(node_resources, network_resources, _diagnostic))

    # Gate account features carried by materializing (CREATE/UPDATE) operations too, so an
    # operation-only or resource-divergent account payload cannot bypass the realization
    # ledger before dispatch (#1563 codex review). Deduplicate against the resource pass:
    # a resource and its own CREATE operation produce an identical diagnostic.
    _extend_unique_diagnostics(diagnostics, account_operation_diagnostics(plan.operations, capabilities))
    _extend_unique_diagnostics(diagnostics, feature_operation_diagnostics(plan.operations))

    if any(diagnostic.is_error for diagnostic in diagnostics):
        return None, diagnostics
    return serialize_provisioning_plan(plan), diagnostics


def _serialized_for_apply(
    plan: ProvisioningPlan,
    *,
    snapshot: RuntimeSnapshot | None = None,
    backend_realization_envelope: object | None = None,
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """Validate + serialize ``plan`` for validate/apply; (None, diagnostics) if unusable."""
    if not isinstance(plan, ProvisioningPlan):
        return None, [_diagnostic("shifter-provisioner.invalid-plan", "plan", "expected an RAES ProvisioningPlan")]
    serialized, diagnostics = interpret_provisioning_plan(plan, snapshot=snapshot)
    if serialized is not None:
        serialized["backend_realization_envelope"] = _plan_json(backend_realization_envelope)
    return serialized, diagnostics


class ShifterProvisioner:
    """Provisioner protocol implementation for Shifter's provisioning-only backend."""

    def __init__(
        self,
        port: ShifterProvisioningDispatchPort,
        *,
        realization_envelope: BackendRealizationEnvelopeModel | None = None,
    ) -> None:
        self._port = port
        self._realization_envelope = realization_envelope
        self._participant_access: tuple[ParticipantAccessBinding, ...] = ()

    def bind_participant_access(self, bindings: Sequence[ParticipantAccessBinding]) -> None:
        """Bind the #1710 participant-access sidecar for the next ``apply``.

        The sidecar is lowered from the compiled ``RuntimeModel``, which the
        provisioner protocol's ``apply(plan, snapshot)`` never sees, so the
        launch path (``package_loader.launch_raes_package``) binds it here after
        planning and before applying. It rides beside the serialized plan and is
        never merged into it (ADR-032-R10). The default of ``()`` keeps the
        conformance fixture/probe suites -- which apply a plan directly -- working
        unchanged, since a scenario authoring no interactive access is the common
        case.
        """
        self._participant_access = tuple(bindings)

    @staticmethod
    def validate(plan: ProvisioningPlan) -> list[Diagnostic]:
        """Return capability-envelope + plan-consistency diagnostics without dispatching."""
        _, diagnostics = _serialized_for_apply(plan)
        return diagnostics

    def apply(self, plan: ProvisioningPlan, snapshot: RuntimeSnapshot) -> ApplyResult:
        """Return realization success only for independently verified completion."""
        if isinstance(plan, ProvisioningPlan):
            plan = replace(plan, operation_id=plan.operation_id or str(uuid4()))
        serialized, diagnostics = _serialized_for_apply(
            plan,
            snapshot=snapshot,
            backend_realization_envelope=self._realization_envelope,
        )
        if serialized is None:
            return ApplyResult(success=False, snapshot=snapshot, diagnostics=diagnostics)

        # Boundary: never leak a raw dispatch exception past apply.
        try:
            result = self._port.realize(serialized, self._participant_access)
        except Exception as exc:
            failure = _diagnostic(
                "shifter-provisioner.dispatch-failed", "plan", f"provisioning dispatch failed: {safe_log_value(exc)}"
            )
            return ApplyResult(success=False, snapshot=snapshot, diagnostics=[*diagnostics, failure])

        return _completed_apply_result(plan, snapshot, serialized, diagnostics, result)

    def enqueue(self, plan: ProvisioningPlan) -> ShifterEnqueueResult:
        """Validate and queue a native launch without claiming an observed state."""
        if isinstance(plan, ProvisioningPlan):
            plan = replace(plan, operation_id=plan.operation_id or str(uuid4()))
        serialized, diagnostics = _serialized_for_apply(plan, backend_realization_envelope=self._realization_envelope)
        if serialized is None:
            return ShifterEnqueueResult(False, "rejected", (), tuple(diagnostics))
        try:
            receipt = self._port.realize(serialized, self._participant_access)
        except Exception as exc:
            failure = _diagnostic("shifter-provisioner.dispatch-failed", "plan", safe_log_value(exc))
            return ShifterEnqueueResult(False, "rejected", (), (*diagnostics, failure))
        addresses = tuple(serialized["resources"]) if receipt.accepted else ()
        return ShifterEnqueueResult(receipt.accepted, receipt.status, addresses, tuple(diagnostics))


@dataclass(frozen=True)
class ShifterEnqueueResult:
    """A queue receipt with admission diagnostics; never a runtime snapshot."""

    accepted: bool
    status: str
    addresses: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]


def _completed_apply_result(
    plan: ProvisioningPlan,
    snapshot: RuntimeSnapshot,
    serialized: Mapping[str, Any],
    diagnostics: list[Diagnostic],
    result: ShifterDispatchResult,
) -> ApplyResult:
    """Handle completed apply result."""
    from shared.raes.completion import completed_snapshot

    if not result.accepted or result.completion is None:
        pending = _diagnostic(
            "shifter-provisioner.completion-unavailable", "plan", "dispatch acceptance is not completed realization"
        )
        return ApplyResult(success=False, snapshot=snapshot, diagnostics=[*diagnostics, pending])
    try:
        observed = completed_snapshot(plan, result.completion, baseline=snapshot, serialized_plan=serialized)
    except ValueError:
        invalid = _diagnostic("shifter-provisioner.invalid-completion", "plan", "realization evidence is invalid")
        return ApplyResult(success=False, snapshot=snapshot, diagnostics=[*diagnostics, invalid])
    return ApplyResult(success=True, snapshot=observed, diagnostics=diagnostics, changed_addresses=list(plan.resources))


def create_shifter_backend_components(
    *,
    manifest: BackendManifest,
    port: ShifterProvisioningDispatchPort,
    **config: Any,
) -> RuntimeTargetComponents:
    """Build the ``provisioning-only`` Shifter backend components for ``manifest``."""
    del config
    return RuntimeTargetComponents(
        provisioner=ShifterProvisioner(port=port, realization_envelope=manifest.realization_envelope)
    )


def register_shifter_backend(registry: BackendRegistry) -> None:
    """Register the Shifter backend descriptor on ``registry``."""
    registry.register(SHIFTER_BACKEND_NAME, create_shifter_backend_manifest, create_shifter_backend_components)


def create_shifter_backend_target(
    *, port: ShifterProvisioningDispatchPort, scenario: object | None = None, **config: Any
) -> RuntimeTarget:
    """Return Shifter's generic or scenario-configured runtime target."""
    realization_envelope = None
    if scenario is not None:
        scenario_name = getattr(scenario, "name", None)
        nodes = getattr(scenario, "nodes", None)
        compute_node_name = (
            next(
                (
                    name
                    for name, node in nodes.items()
                    if getattr(getattr(node, "type", None), "value", None) == "compute"
                ),
                None,
            )
            if isinstance(nodes, Mapping)
            else None
        )
        if not isinstance(scenario_name, str) or not scenario_name or compute_node_name is None:
            raise ValueError("a configured Shifter target requires a named scenario with a compute node")
        realization_envelope = create_shifter_realization_envelope(
            scenario_name=scenario_name, compute_node_name=compute_node_name
        )
    manifest = create_shifter_backend_manifest(realization_envelope=realization_envelope, **config)
    components = create_shifter_backend_components(manifest=manifest, port=port, **config)
    return RuntimeTarget(name=SHIFTER_BACKEND_NAME, manifest=manifest, provisioner=components.provisioner)
