"""Realize authored RAES node ACLs as GCE firewall rules (ADR-031, ADR-032).

The reference backend renders a node's ``acls`` as libvirt ``nwfilter`` rules;
the GCE backend renders them as Compute Engine firewall rules targeting a
per-node network tag. Translation is fail-closed, mirroring
``raes_backend_libvirt.acls``: a *specified* ``from_net``/``to_net`` that does not
resolve to a concrete CIDR raises rather than widening into a broad allow; an
*omitted* endpoint is the plan's own "any" (``0.0.0.0/0``).

Precedence policy (deliberate): authored ACLs are placed at priority
``1000 + author-index`` -- author order preserved (lower number wins), and
strictly *below* the base management firewall (priority 900) that grants the
provisioner SSH/RDP reachability. An authored "deny all inbound" therefore
segments participant traffic without severing the provisioner's own management
plane (host setup, verification, teardown), exactly as the cyberscript backend
keeps its management rule authoritative.
"""

from __future__ import annotations

from gcp_range_cell_naming import _short_resource_name
from gcp_range_cell_types import FirewallEntry, FirewallPlan
from raes_plan import RaesPlanAcl, RaesPlanNetwork, RaesPlanNode

#: Authored-ACL firewalls sit at 1000+index: below the priority-900 management
#: rule (so provisioner reachability is never blocked) but authoritative over the
#: base per-subnet ingress; ``+index`` preserves author order (lower number wins).
_ACL_FIREWALL_BASE_PRIORITY = 1000
_ANY_CIDR = "0.0.0.0/0"

#: Service-derived ingress allows are rendered in this deterministic protocol order;
#: one aggregated rule per protocol keeps the GCP rule count minimal (ADR-032-R8).
_SERVICE_PROTOCOL_ORDER = ("tcp", "udp")
#: Service allows sit ABOVE authored ACLs (the plan layer passes a per-node base
#: above that node's ACL band), so an authored ACL deny still wins over a service
#: allow and both stay below the priority-900 management rule. This ceiling fails
#: closed before emitting an out-of-band (unrepresentable) priority (ADR-032-R8).
_SERVICE_FIREWALL_PRIORITY_CEILING = 60000


class RaesGceFirewallError(RuntimeError):
    """Raised when an authored ACL cannot be realized fail-closed as a GCE firewall."""


def node_tag(range_id: int, node_address: str) -> str:
    """Return the per-node network tag ACL firewalls target this node's instances by."""
    return _short_resource_name("shifter-node", range_id, node_address)


def acl_cidr_lookup(networks: tuple[RaesPlanNetwork, ...]) -> dict[str, str]:
    """Map every handle an ACL might reference a network by to its CIDR.

    Mirrors ``raes_backend_libvirt.realization._network_cidr_lookup``: each network
    with a CIDR is keyed by its address, name, and address leaf.
    """
    lookup: dict[str, str] = {}
    for network in networks:
        if not network.cidr:
            continue
        for key in (network.address, network.name, network.address.rsplit(".", 1)[-1]):
            if key:
                lookup[key] = network.cidr
    return lookup


def _resolve_endpoint(ref: str | None, cidr_lookup: dict[str, str]) -> str:
    """Resolve an ACL endpoint ref to a CIDR; omitted = any, unresolvable = fail-closed."""
    if ref is None:
        return _ANY_CIDR
    cidr = cidr_lookup.get(ref)
    if not cidr:
        raise RaesGceFirewallError(f"ACL endpoint {ref!r} references a network with no resolvable CIDR")
    return cidr


def _acl_rule(acl: RaesPlanAcl) -> FirewallEntry:
    """Render the protocol/ports clause for one ACL firewall rule."""
    if acl.protocol == "all":
        return {"IPProtocol": "all"}
    rule: FirewallEntry = {"IPProtocol": acl.protocol}
    if acl.ports:
        rule["ports"] = [str(port) for port in acl.ports]
    return rule


def _acl_firewall(range_id: int, node_name: str, tag: str, acl: RaesPlanAcl, index: int, ingress: bool) -> FirewallPlan:
    """Render one directional GCE firewall for an authored ACL targeting a node tag."""
    direction_label = "in" if ingress else "out"
    firewall: FirewallPlan = {
        "name": _short_resource_name("shifter-r", range_id, node_name, "acl", index, direction_label),
        "direction": "INGRESS" if ingress else "EGRESS",
        "priority": _ACL_FIREWALL_BASE_PRIORITY + index,
        "target_tags": [tag],
    }
    # Literal keys (not a variable) so the FirewallPlan TypedDict stays well-typed.
    if acl.action == "accept":
        firewall["allowed"] = [_acl_rule(acl)]
    else:
        firewall["denied"] = [_acl_rule(acl)]
    return firewall


def build_acl_firewalls(range_id: int, node: RaesPlanNode, tag: str, cidr_lookup: dict[str, str]) -> list[FirewallPlan]:
    """Render every GCE firewall realizing one node's authored ACLs (fail-closed)."""
    firewalls: list[FirewallPlan] = []
    for index, acl in enumerate(node.acls):
        if acl.direction in ("in", "inout"):
            firewall = _acl_firewall(range_id, node.name, tag, acl, index, ingress=True)
            firewall["source_ranges"] = [_resolve_endpoint(acl.from_net, cidr_lookup)]
            firewalls.append(firewall)
        if acl.direction in ("out", "inout"):
            firewall = _acl_firewall(range_id, node.name, tag, acl, index, ingress=False)
            firewall["destination_ranges"] = [_resolve_endpoint(acl.to_net, cidr_lookup)]
            firewalls.append(firewall)
    return firewalls


def service_base_priority(node: RaesPlanNode) -> int:
    """Return the first service-firewall priority for a node: strictly above its ACL band.

    Authored ACLs occupy ``[1000, 1000 + len(acls) - 1]``; service allows start one slot
    above the whole band (and above the base per-subnet allow at 1000), so an authored
    ACL deny always outranks a service allow and the management rule (900) outranks both
    (ADR-032-R8).
    """
    return _ACL_FIREWALL_BASE_PRIORITY + 1 + len(node.acls)


def build_service_firewalls(
    range_id: int,
    node: RaesPlanNode,
    tag: str,
    source_cidrs: tuple[str, ...],
    base_priority: int,
) -> list[FirewallPlan]:
    """Render fail-closed per-node-tag INGRESS firewalls for a node's authored services.

    Realizes authored ``Node.services`` as layer-4 ingress reachability (ADR-032-R8):
    one aggregated INGRESS rule per protocol (``tcp`` then ``udp``, ports sorted),
    targeting this node's tag, admitting only the same-range ``source_cidrs`` -- never
    ``0.0.0.0/0``, portal/operator, or another range. Fails closed
    (:class:`RaesGceFirewallError`) when there is no source CIDR to admit from, when an
    unsupported protocol survived to realization, or when the required priority would
    fall outside the service band (so an unrepresentable ordering never widens policy).
    ``base_priority`` is supplied by the plan layer strictly above the node's ACL band,
    keeping authored ACL denies (and the management rule) higher precedence.
    """
    if not node.services:
        return []
    sources = sorted(set(source_cidrs))
    if not sources:
        raise RaesGceFirewallError(
            f"node {node.address!r} declares services but the range has no source CIDR to admit them from"
        )
    ports_by_protocol: dict[str, set[int]] = {}
    for service in node.services:
        ports_by_protocol.setdefault(service.protocol, set()).add(service.port)
    unsupported = set(ports_by_protocol) - set(_SERVICE_PROTOCOL_ORDER)
    if unsupported:
        raise RaesGceFirewallError(f"node {node.address!r} has unsupported service protocol(s) {sorted(unsupported)}")

    firewalls: list[FirewallPlan] = []
    priority = base_priority
    for protocol in _SERVICE_PROTOCOL_ORDER:
        ports = ports_by_protocol.get(protocol)
        if not ports:
            continue
        if not 0 < priority < _SERVICE_FIREWALL_PRIORITY_CEILING:
            raise RaesGceFirewallError(
                f"node {node.address!r} service firewall priority {priority} is outside the service band "
                f"(1, {_SERVICE_FIREWALL_PRIORITY_CEILING})"
            )
        firewalls.append(
            {
                "name": _short_resource_name("shifter-r", range_id, node.name, "svc", protocol),
                "direction": "INGRESS",
                "priority": priority,
                "target_tags": [tag],
                "source_ranges": sources,
                "allowed": [{"IPProtocol": protocol, "ports": [str(port) for port in sorted(ports)]}],
            }
        )
        priority += 1
    return firewalls
