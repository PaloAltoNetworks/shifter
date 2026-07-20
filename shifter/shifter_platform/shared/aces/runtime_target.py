"""Shifter's ACES RuntimeTarget provisioning backend (ADR-031, ADR-032).

Supersedes the #1262 ``scenario_ref`` passthrough. It validates a compiled ACES
``ProvisioningPlan`` against the declared capability envelope, then dispatches
the **serialized plan itself** through an injected
:class:`~shared.aces.dispatch_port.ShifterProvisioningDispatchPort`. Shifter
introduces no parallel SDL and no re-modeled provisioning schema; the realization
side (engine/provisioner) reads the ACES plan payloads directly via accessors
that mirror the reference ACES backends.

It mirrors the reference backend pattern: ``validate`` and ``apply`` funnel
through one pure interpret step; every plan term is checked against the
declared capability envelope and unsupported terms yield typed diagnostics;
* ``apply`` refuses to dispatch on any error, and on a valid plan returns an
  ``ApplyResult`` with non-empty ``changed_addresses`` and a PROVISIONING
  ``RuntimeSnapshot`` reflecting the accepted realization.

Only :mod:`shared.aces` may import ``aces-sdl`` (ADR-031-R1 / ADR-024); realization consumes the serialized plan as
plain data via the injected dispatch port.
"""

from __future__ import annotations

import importlib.metadata
import json
from collections.abc import Mapping
from typing import Any

from aces_backend_protocols.capabilities import BackendManifest, ProvisionerCapabilities
from aces_contracts.diagnostics import Diagnostic, Severity
from aces_contracts.planning import PlannedResource, ProvisioningPlan, RuntimeDomain
from aces_contracts.runtime_state import ApplyResult, RuntimeSnapshot, SnapshotEntry
from aces_processor.semantics.realization import CONCERN_PAYLOAD_PATH
from aces_runtime.registry import BackendRegistry, RuntimeTarget, RuntimeTargetComponents

from shared.aces.composition_envelope import (
    COMPOSITION_RESOURCE_TYPES,
    account_operation_diagnostics,
    composition_diagnostics,
    feature_operation_diagnostics,
)
from shared.aces.contracts import ACES_PROVISIONING_PLAN_CONTRACT_VERSION, SHIFTER_BACKEND_NAME
from shared.aces.dispatch_port import ShifterDispatchResult, ShifterProvisioningDispatchPort
from shared.aces.domain_topology import (
    backend_effect_domain_topology_diagnostics,
    sanitized_domain_topology_diagnostics,
)
from shared.aces.manifest import SHIFTER_PROVISIONER_CAPABILITIES, create_shifter_backend_manifest
from shared.aces.network_family import network_address_family_diagnostics
from shared.log_sanitize import safe_log_value

__all__ = [
    "ACES_PROVISIONING_PLAN_KIND",
    "NETWORK_RESOURCE_TYPE",
    "NODE_RESOURCE_TYPE",
    "SUPPORTED_RESOURCE_TYPES",
    "ShifterProvisioner",
    "create_shifter_backend_components",
    "create_shifter_backend_target",
    "interpret_provisioning_plan",
    "register_shifter_backend",
    "serialize_provisioning_plan",
]

_DOMAIN = "provisioning"
NODE_RESOURCE_TYPE = "node"
NETWORK_RESOURCE_TYPE = "network"
#: Node/network plus the composition placement types (content/features/accounts).
SUPPORTED_RESOURCE_TYPES: frozenset[str] = (
    frozenset({NODE_RESOURCE_TYPE, NETWORK_RESOURCE_TYPE}) | COMPOSITION_RESOURCE_TYPES
)

#: Discriminator for the serialized plan persisted in ``range_config`` so the
#: provisioner ``aces-range`` path can tell it apart from a cyberscript envelope.
ACES_PROVISIONING_PLAN_KIND = "aces_provisioning_plan"

_MAX_DIAGNOSTIC = 480


def _diagnostic(code: str, address: str, message: str) -> Diagnostic:
    """Build a bounded, single-line ERROR provisioning diagnostic (ADR-031-R4)."""
    flat = " ".join(str(message).split())
    if len(flat) > _MAX_DIAGNOSTIC:
        flat = flat[: _MAX_DIAGNOSTIC - 1] + "…"
    return Diagnostic(code=code, domain=_DOMAIN, address=address, message=flat, severity=Severity.ERROR)


# --- validation accessors (mirror aces_backend_libvirt so the envelope agrees) ---
# Realization-time extraction (image/resources/services/network properties) lives
# on the provisioner side, which reads the same payloads at realization (ADR-032):
# Shifter never re-models the plan into an intermediate spec.


def _spec(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Return the payload's ``spec`` mapping, or an empty mapping."""
    spec = payload.get("spec")
    return spec if isinstance(spec, Mapping) else {}


def _node_spec(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Return the payload's ``spec.node`` mapping, or an empty mapping."""
    node = _spec(payload).get("node")
    return node if isinstance(node, Mapping) else {}


def _infrastructure_spec(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Return the payload's ``spec.infrastructure`` mapping, or an empty mapping."""
    infra = _spec(payload).get("infrastructure")
    return infra if isinstance(infra, Mapping) else {}


def _resource_name(resource: PlannedResource, payload: Mapping[str, object]) -> str:
    """Return the authored resource name, falling back to the address leaf."""
    name = payload.get("name") or payload.get("node_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return resource.address.rsplit(".", 1)[-1]


def _os_family(payload: Mapping[str, object]) -> str:
    """Return the node OS family (``os_family`` then ``spec.node.os``), or empty."""
    family = payload.get("os_family")
    if isinstance(family, str) and family.strip():
        return family.strip()
    node_os = _node_spec(payload).get("os")
    return node_os.strip() if isinstance(node_os, str) and node_os.strip() else ""


def _node_type(payload: Mapping[str, object]) -> str:
    """Return the node type (``node_type`` then ``spec.node.type``), or empty."""
    node_type = payload.get("node_type")
    if isinstance(node_type, str) and node_type.strip():
        return node_type.strip()
    nested = _node_spec(payload).get("type")
    return nested.strip() if isinstance(nested, str) and nested.strip() else ""


def _node_count(payload: Mapping[str, object]) -> int:
    """Return the node instance count (>= 1); default 1 for missing/invalid values."""
    raw = payload.get("count")
    if isinstance(raw, str):
        try:
            raw = int(raw)
        except ValueError:
            return 1
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1:
        return raw
    return 1


def _network_refs(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return the network handles a node references (``networks`` then ``links``)."""
    infra = _infrastructure_spec(payload)
    for field_name in ("networks", "links"):
        raw = infra.get(field_name)
        if isinstance(raw, list | tuple):
            return tuple(ref for ref in raw if isinstance(ref, str) and ref.strip())
    return ()


def _network_lookup(network_resources: list[tuple[PlannedResource, Mapping[str, object]]]) -> dict[str, str]:
    """Map every handle a node might reference a network by to its canonical address."""
    lookup: dict[str, str] = {}
    for resource, payload in network_resources:
        name = _resource_name(resource, payload)
        for key in (resource.address, name, resource.address.rsplit(".", 1)[-1]):
            if key:
                lookup[key] = resource.address
    return lookup


# --- capability envelope (fail closed on out-of-envelope terms) ---


def _node_envelope_diagnostics(
    resource: PlannedResource, payload: Mapping[str, object], capabilities: ProvisionerCapabilities
) -> list[Diagnostic]:
    """Return capability-envelope diagnostics for a single node resource."""
    diagnostics: list[Diagnostic] = []
    node_type = _node_type(payload)
    if node_type and node_type not in capabilities.supported_node_types:
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.unsupported-node-type",
                resource.address,
                f"unsupported node type '{node_type}' (supported: {sorted(capabilities.supported_node_types)})",
            )
        )
    os_family = _os_family(payload)
    if os_family and os_family not in capabilities.supported_os_families:
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.unsupported-os-family",
                resource.address,
                f"unsupported os_family '{safe_log_value(os_family)}' "
                f"(supported: {sorted(capabilities.supported_os_families)})",
            )
        )
    if not capabilities.supports_acls and _infrastructure_spec(payload).get("acls"):
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.acls-unsupported",
                resource.address,
                "this provisioning-only backend does not yet realize network ACLs",
            )
        )
    return diagnostics


def _capability_envelope_diagnostics(
    resources: list[PlannedResource], capabilities: ProvisionerCapabilities
) -> list[Diagnostic]:
    """Return fail-closed diagnostics for every out-of-envelope term in the plan."""
    diagnostics: list[Diagnostic] = []
    node_addresses = {r.address for r in resources if r.resource_type == NODE_RESOURCE_TYPE}
    total_nodes = 0
    for resource in resources:
        payload = resource.payload
        if not isinstance(payload, Mapping):
            diagnostics.append(
                _diagnostic(
                    "shifter-provisioner.invalid-payload", resource.address, "resource payload must be a mapping"
                )
            )
            continue
        if resource.resource_type not in SUPPORTED_RESOURCE_TYPES:
            diagnostics.append(
                _diagnostic(
                    "shifter-provisioner.unsupported-resource-type",
                    resource.address,
                    f"provisioning-only backend does not support resource type '{resource.resource_type}' "
                    f"(supported: {sorted(SUPPORTED_RESOURCE_TYPES)})",
                )
            )
        elif resource.resource_type == NODE_RESOURCE_TYPE:
            total_nodes += _node_count(payload)
            diagnostics.extend(_node_envelope_diagnostics(resource, payload, capabilities))
        elif resource.resource_type == NETWORK_RESOURCE_TYPE:
            diagnostics.extend(network_address_family_diagnostics(resource, payload, capabilities, _diagnostic))
        elif resource.resource_type in COMPOSITION_RESOURCE_TYPES:
            diagnostics.extend(composition_diagnostics(resource, payload, capabilities, node_addresses))
    if capabilities.max_total_nodes is not None and total_nodes > capabilities.max_total_nodes:
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.node-budget-exceeded",
                "plan",
                f"plan requests {total_nodes} nodes; backend allows at most {capabilities.max_total_nodes}",
            )
        )
    return diagnostics


# --- serialization (the artifact that crosses the platform -> provisioner boundary) ---


def _aces_sdl_version() -> str:
    """Return the installed aces-sdl version (recorded on the serialized plan).

    aces-sdl is a runtime dependency imported at this module's top, so it is
    always installed by the time this runs.
    """
    return importlib.metadata.version("aces-sdl")


def serialize_provisioning_plan(plan: ProvisioningPlan) -> dict[str, Any]:
    """Serialize the PROVISIONING resources of a compiled ACES plan to JSON-safe dict.

    The payloads are the ACES plan's own payloads, verbatim -- this is
    serialization for the cross-process boundary, not a re-modeled schema
    (ADR-032-R3). A ``kind`` discriminator lets the provisioner distinguish the
    serialized plan from a cyberscript envelope in ``range_config``; the
    ``contract_version`` declares the transport envelope shape the consumer must
    support (ADR-032-R7); and the ``aces_sdl_version`` records the producer
    (aces-sdl) version the plan was compiled against.
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
        "kind": ACES_PROVISIONING_PLAN_KIND,
        "contract_version": ACES_PROVISIONING_PLAN_CONTRACT_VERSION,
        "aces_sdl_version": _aces_sdl_version(),
        "resources": resources,
    }
    # Guarantee the envelope is JSON-safe for range_config persistence (payload
    # Any values are compiler-produced primitives; default=str is a backstop).
    return json.loads(json.dumps(envelope, default=str))


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
    """Validate a compiled ACES provisioning plan and return its serialized form.

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
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """Validate + serialize ``plan`` for validate/apply; (None, diagnostics) if unusable."""
    if not isinstance(plan, ProvisioningPlan):
        return None, [_diagnostic("shifter-provisioner.invalid-plan", "plan", "expected an ACES ProvisioningPlan")]
    return interpret_provisioning_plan(plan, snapshot=snapshot)


class ShifterProvisioner:
    """Provisioner protocol implementation for Shifter's provisioning-only backend."""

    def __init__(self, port: ShifterProvisioningDispatchPort) -> None:
        self._port = port

    @staticmethod
    def validate(plan: ProvisioningPlan) -> list[Diagnostic]:
        """Return capability-envelope + plan-consistency diagnostics without dispatching."""
        _, diagnostics = _serialized_for_apply(plan)
        return diagnostics

    def apply(self, plan: ProvisioningPlan, snapshot: RuntimeSnapshot) -> ApplyResult:
        """Validate + dispatch the serialized ``plan``; never dispatch on error."""
        serialized, diagnostics = _serialized_for_apply(plan, snapshot=snapshot)
        if serialized is None:
            return ApplyResult(success=False, snapshot=snapshot, diagnostics=diagnostics)

        # Boundary: never leak a raw dispatch exception past apply.
        try:
            result = self._port.realize(serialized)
        except Exception as exc:
            failure = _diagnostic(
                "shifter-provisioner.dispatch-failed", "plan", f"provisioning dispatch failed: {safe_log_value(exc)}"
            )
            return ApplyResult(success=False, snapshot=snapshot, diagnostics=[*diagnostics, failure])

        entries = dict(snapshot.entries)
        changed_addresses: list[str] = []
        for resource in sorted(plan.resources.values(), key=lambda item: item.address):
            if resource.domain != RuntimeDomain.PROVISIONING or resource.resource_type not in SUPPORTED_RESOURCE_TYPES:
                continue
            entries[resource.address] = _snapshot_entry(resource, result)
            changed_addresses.append(resource.address)

        return ApplyResult(
            success=result.accepted,
            snapshot=snapshot.with_entries(entries),
            diagnostics=diagnostics,
            changed_addresses=changed_addresses,
        )


def _echo_concern_values(source: Mapping[str, object], payload: dict[str, Any]) -> None:
    """Echo authored realization-concern values into the snapshot entry payload.

    The aces-sdl runtime non-approximation gate (SEM-218) compares each exact
    authored requirement (``os_family``, ``node_type``, content ``spec.type``)
    against the value the backend recorded at ``CONCERN_PAYLOAD_PATH`` in its
    returned snapshot; an omitted value is a forbidden silent approximation.
    Shifter dispatches asynchronously, so its provisional entry echoes the exact
    values it commits to realize, and the gate sees realized == authored.
    """
    for path in CONCERN_PAYLOAD_PATH.values():
        value: object = source
        for key in path:
            if isinstance(value, Mapping) and key in value:
                value = value[key]
            else:
                value = None
                break
        if value is None:
            continue
        target = payload
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = value


def _snapshot_entry(resource: PlannedResource, result: ShifterDispatchResult) -> SnapshotEntry:
    """Build a provisional PROVISIONING snapshot entry from the dispatch result.

    Echoes the authored realization-concern values (see ``_echo_concern_values``)
    so the runtime non-approximation gate confirms Shifter committed to realize
    exactly what the author declared.
    """
    payload: dict[str, Any] = {"request_id": result.request_id, "status": result.status}
    if result.range_id:
        payload["range_id"] = result.range_id
    _echo_concern_values(resource.payload, payload)
    return SnapshotEntry(
        address=resource.address,
        domain=RuntimeDomain.PROVISIONING,
        resource_type=resource.resource_type,
        payload=payload,
        status=result.status,
    )


def create_shifter_backend_components(
    *,
    manifest: BackendManifest,
    port: ShifterProvisioningDispatchPort,
    **config: Any,
) -> RuntimeTargetComponents:
    """Build the ``provisioning-only`` Shifter backend components for ``manifest``."""
    del manifest, config
    return RuntimeTargetComponents(provisioner=ShifterProvisioner(port=port))


def register_shifter_backend(registry: BackendRegistry) -> None:
    """Register the Shifter backend descriptor on ``registry``."""
    registry.register(SHIFTER_BACKEND_NAME, create_shifter_backend_manifest, create_shifter_backend_components)


def create_shifter_backend_target(*, port: ShifterProvisioningDispatchPort, **config: Any) -> RuntimeTarget:
    """Return a fully configured, provisioning-only Shifter ``RuntimeTarget``."""
    manifest = create_shifter_backend_manifest(**config)
    components = create_shifter_backend_components(manifest=manifest, port=port, **config)
    return RuntimeTarget(name=SHIFTER_BACKEND_NAME, manifest=manifest, provisioner=components.provisioner)
