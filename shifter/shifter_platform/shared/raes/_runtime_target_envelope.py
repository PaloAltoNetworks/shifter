"""Capability-envelope validation for the Shifter RAES provisioning backend.

Split out of :mod:`shared.raes.runtime_target` (Sonar S104) so that module keeps
the backend surface -- serialization, interpret, the ``ShifterProvisioner``
protocol implementation, and registration. This half is pure and fail-closed: the
supported resource-type vocabulary, the payload accessors that mirror the
reference RAES backends (``raes_backend_libvirt``) so the envelope agrees with
them, the bounded diagnostic builder, and the per-resource envelope checks that
turn every out-of-envelope plan term into a typed ERROR diagnostic.

No I/O, no dispatch: it reads a compiled plan's payloads and returns diagnostics.
"""

from __future__ import annotations

from collections.abc import Mapping

from raes_backend_protocols.capabilities import ProvisionerCapabilities
from raes_contracts.diagnostics import Diagnostic, Severity
from raes_contracts.planning import PlannedResource

from shared.log_sanitize import safe_log_value
from shared.raes.composition_envelope import COMPOSITION_RESOURCE_TYPES, composition_diagnostics
from shared.raes.network_family import network_address_family_diagnostics

_DOMAIN = "provisioning"
NODE_RESOURCE_TYPE = "node"
NETWORK_RESOURCE_TYPE = "network"
DOMAIN_CONTROLLER_PLACEMENT_RESOURCE_TYPE = "domain-controller-placement"
#: Node/network plus the composition and identity-topology placement types.
SUPPORTED_RESOURCE_TYPES: frozenset[str] = (
    frozenset({NODE_RESOURCE_TYPE, NETWORK_RESOURCE_TYPE, DOMAIN_CONTROLLER_PLACEMENT_RESOURCE_TYPE})
    | COMPOSITION_RESOURCE_TYPES
)


_MAX_DIAGNOSTIC = 480


def _diagnostic(code: str, address: str, message: str) -> Diagnostic:
    """Build a bounded, single-line ERROR provisioning diagnostic (ADR-031-R4)."""
    flat = " ".join(str(message).split())
    if len(flat) > _MAX_DIAGNOSTIC:
        flat = flat[: _MAX_DIAGNOSTIC - 1] + "…"
    return Diagnostic(code=code, domain=_DOMAIN, address=address, message=flat, severity=Severity.ERROR)


# --- validation accessors (mirror raes_backend_libvirt so the envelope agrees) ---
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
    from shared.raes.completion_evidence import MAX_COMPLETION_RESOURCES

    if len(resources) > MAX_COMPLETION_RESOURCES:
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.resource-budget-exceeded",
                "plan",
                f"plan requests {len(resources)} resources; backend allows at most {MAX_COMPLETION_RESOURCES}",
            )
        )
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
