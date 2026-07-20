"""Build a GCE range-cell plan from a serialized ACES plan (ADR-031, ADR-032).

The ACES-native counterpart of ``gcp_range_cell_plan.render_range_cell_plan``:
it maps the neutral :class:`aces_plan.AcesPlan` (parsed from the serialized ACES
ProvisioningPlan) into the provisioner's neutral ``RangeCellPlan`` so the whole
GCE apply layer (``_ensure_network``/``_ensure_subnetwork``/``_ensure_firewall``/
``_ensure_address`` + resource renderers) is reused unchanged. It carries **no**
cyberscript scenario semantics: the image comes from the authored ACES ``source``
resolved against the tenant registry (``resolve_gce_image``), sizing from
``resources``, and ``os_family`` drives only the OS realization dialect. Nodes are
placed on their authored network; each ``count`` yields a distinct instance.

Base range firewalls (intra-subnet allow, management, egress posture) are reused
from ``gcp_range_cell_firewall.build_firewall_plan``; authored node ACLs are
realized as additional firewall rules by :mod:`aces_gcp_firewall` (layered on
top).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable

from aces_gcp_firewall import (
    acl_cidr_lookup,
    build_acl_firewalls,
    build_service_firewalls,
    node_tag,
    service_base_priority,
)
from aces_plan import AcesPlan, AcesPlanNetwork, AcesPlanNode
from config import GCERangeCellConfig, GCERangeImageProfile, load_gce_range_cell_config
from gcp_range_cell_firewall import build_firewall_plan
from gcp_range_cell_naming import (
    _network_name_from_id,
    _network_self_link,
    _network_tag,
    _short_resource_name,
    _subnet_tag,
    _subnetwork_self_link,
)
from gcp_range_cell_plan import _range_labels
from gcp_range_cell_types import (
    FirewallPlan,
    InstancePlan,
    RangeCellPlan,
    SubnetPlan,
)

#: Default guest login user the provisioner injects (management reachability). The
#: participant-facing user is a later participant-runtime concern (not provisioning).
_DEFAULT_SSH_USERNAME = "aces"
_DEFAULT_SSH_PORT = 22


class AcesGcePlanError(RuntimeError):
    """Raised when an ACES plan cannot be realized as a GCE range-cell plan."""


def build_aces_range_cell_plan(
    request_uuid: str,
    range_id: int,
    aces_plan: AcesPlan,
    resolve_image: Callable[[AcesPlanNode], GCERangeImageProfile],
    config: GCERangeCellConfig | None = None,
) -> RangeCellPlan:
    """Render the deterministic GCE range-cell plan for a parsed ACES plan.

    ``resolve_image`` maps one node to its concrete image/sizing profile (wired to
    the tenant image registry by the caller), keeping this builder pure/testable.
    """
    resolved_config = config or load_gce_range_cell_config()
    network_name, network_link, manage_network = _network_placement(resolved_config, range_id)

    networks_by_address = {network.address: network for network in aces_plan.networks}
    nodes_by_network = _nodes_by_network(aces_plan)

    subnet_plans = [
        _subnet_plan(
            network, nodes_by_network.get(network.address, ()), range_id, resolved_config, network_name, network_link
        )
        for network in aces_plan.networks
    ]
    subnet_by_address = {
        network.address: subnet for network, subnet in zip(aces_plan.networks, subnet_plans, strict=True)
    }

    instance_plans: list[InstancePlan] = []
    for network in aces_plan.networks:
        subnet = subnet_by_address[network.address]
        for node in nodes_by_network.get(network.address, ()):
            instance_plans.extend(_instance_plans_for_node(node, subnet, range_id, resolve_image))

    _reject_unplaceable_nodes(aces_plan, networks_by_address)

    return {
        "project_id": resolved_config.project_id,
        "region": resolved_config.region,
        "zone": resolved_config.zone,
        "request_uuid": request_uuid,
        "range_id": range_id,
        "private_google_access": resolved_config.private_google_access,
        "labels": _range_labels(range_id, request_uuid),
        "network": {"name": network_name, "self_link": network_link},
        "manage_network": manage_network,
        "subnets": subnet_plans,
        "instances": instance_plans,
        "firewalls": _all_firewalls(range_id, subnet_plans, aces_plan, resolved_config),
    }


def _all_firewalls(
    range_id: int,
    subnet_plans: list[SubnetPlan],
    aces_plan: AcesPlan,
    config: GCERangeCellConfig,
) -> list[FirewallPlan]:
    """Base range firewalls (reused, neutral) plus authored node ACL and service firewalls.

    Authored ``services`` are realized as fail-closed, range-scoped per-node-tag ingress
    (ADR-032-R8): admitted only from the concrete CIDRs of networks in *this* compiled
    range, at a priority strictly above the node's ACL band so authored ACL denies win.
    """
    firewalls = build_firewall_plan(range_id, subnet_plans, config)
    cidr_lookup = acl_cidr_lookup(aces_plan.networks)
    # Validate the range-scoped service source set once, up front, only when needed --
    # so a universal or portal-overlapping CIDR fails the whole plan before mutation.
    service_source_cidrs = (
        _service_source_cidrs(subnet_plans, config) if any(node.services for node in aces_plan.nodes) else ()
    )
    for node in aces_plan.nodes:
        tag = node_tag(range_id, node.address)
        if node.acls:
            firewalls.extend(build_acl_firewalls(range_id, node, tag, cidr_lookup))
        if node.services:
            firewalls.extend(
                build_service_firewalls(
                    range_id, node, tag, service_source_cidrs, base_priority=service_base_priority(node)
                )
            )
    return firewalls


def _service_source_cidrs(subnet_plans: list[SubnetPlan], config: GCERangeCellConfig) -> tuple[str, ...]:
    """Validated, range-scoped source CIDRs for service ingress (ADR-032-R8, fail-closed).

    Sources are the range's own realized subnet CIDRs only -- every subnet plan carries a
    concrete, IPv4-validated CIDR, so no declared network is silently dropped. Universal /
    oversized CIDRs are already rejected at subnet realization (``_usable_host_ips``); this
    additionally rejects a CIDR overlapping a management/portal source range before any
    cloud mutation, so an authored network CIDR can never widen a service allow onto the
    management plane.
    """
    portal_networks = [ipaddress.ip_network(cidr) for cidr in config.portal_network_cidrs]
    sources: list[str] = []
    for subnet in subnet_plans:
        cidr = subnet["cidr"]
        network = ipaddress.ip_network(cidr)
        if any(network.overlaps(portal) for portal in portal_networks):
            raise AcesGcePlanError(
                f"service source CIDR {cidr} overlaps a management/portal source range; "
                "refusing to widen service ingress"
            )
        sources.append(cidr)
    return tuple(dict.fromkeys(sources))


def _network_placement(config: GCERangeCellConfig, range_id: int) -> tuple[str, str, bool]:
    """Resolve (network_name, network_link, manage_network) for the range VPC."""
    if config.network_mode == "shared-vpc":
        return _network_name_from_id(config.network_id), config.network_id, False
    name = _short_resource_name("shifter-range", range_id)
    return name, _network_self_link(config.project_id, name), True


def _primary_network(node: AcesPlanNode) -> str | None:
    """Return the node's primary (first) declared network address, or None."""
    return node.network_addresses[0] if node.network_addresses else None


def _nodes_by_network(aces_plan: AcesPlan) -> dict[str, list[AcesPlanNode]]:
    """Group nodes by their primary network address (declaration order preserved)."""
    grouped: dict[str, list[AcesPlanNode]] = {}
    for node in aces_plan.nodes:
        primary = _primary_network(node)
        if primary is not None:
            grouped.setdefault(primary, []).append(node)
    return grouped


def _reject_unplaceable_nodes(aces_plan: AcesPlan, networks_by_address: dict[str, AcesPlanNetwork]) -> None:
    """Fail loud on nodes with no network or an undeclared primary network."""
    for node in aces_plan.nodes:
        primary = _primary_network(node)
        if primary is None:
            raise AcesGcePlanError(f"node {node.address!r} declares no network to attach to")
        if primary not in networks_by_address:
            raise AcesGcePlanError(f"node {node.address!r} references undeclared network {primary!r}")


#: A range subnet holds a handful of guests; refuse to enumerate host addresses for a
#: network larger than /16. A universal (``/0``) or otherwise oversized authored CIDR
#: would otherwise materialize billions of addresses here (a DoS) and can never be a
#: legitimate range subnet or service source (fail-closed, ADR-032-R8).
_MAX_SUBNET_ADDRESSES = 1 << 16


def _usable_host_ips(cidr: str) -> list[str]:
    """Return assignable IPv4 host addresses in ``cidr`` (GCP reserves 2 at each end).

    Backstop for the IPv4-only network address family (issue #1568): the RuntimeTarget
    admission path rejects non-IPv4 networks before dispatch, and this repeats the check
    for persisted/replayed plans. The message must not echo the authored CIDR --
    ``aces_range_ops`` forwards ``str(exc)`` into published failure events.
    """
    network = ipaddress.ip_network(cidr)
    if not isinstance(network, ipaddress.IPv4Network):
        raise AcesGcePlanError("GCE range cells require IPv4 subnets; got an unsupported network address family")
    if network.num_addresses > _MAX_SUBNET_ADDRESSES:
        raise AcesGcePlanError(f"GCE range subnet {cidr} is larger than /16; refusing to enumerate host addresses")
    return [str(host) for host in list(network.hosts())[2:-2]]


def _instance_keys(nodes: tuple[AcesPlanNode, ...] | list[AcesPlanNode]) -> list[str]:
    """Return the ordered per-instance assignment keys (one per node ``count``)."""
    return [_instance_key(node, index) for node in nodes for index in range(node.count)]


def _instance_key(node: AcesPlanNode, index: int) -> str:
    """Return the stable IP-assignment key for one instance of a node."""
    return f"{node.address}#{index}"


def _subnet_plan(
    network: AcesPlanNetwork,
    nodes: tuple[AcesPlanNode, ...] | list[AcesPlanNode],
    range_id: int,
    config: GCERangeCellConfig,
    network_name: str,
    network_link: str,
) -> SubnetPlan:
    """Render one subnet plan from an ACES network + the nodes placed on it."""
    if not network.cidr:
        raise AcesGcePlanError(f"ACES network {network.address!r} has no cidr to provision a GCE subnet")
    resource_name = _short_resource_name("shifter-r", range_id, network.name)
    keys = _instance_keys(nodes)
    usable = _usable_host_ips(network.cidr)
    if len(keys) > len(usable):
        raise AcesGcePlanError(
            f"subnet {network.cidr} has {len(usable)} usable addresses but {len(keys)} instances were requested"
        )
    return {
        "name": network.name,
        "uuid": network.address,
        "resource_name": resource_name,
        "self_link": _subnetwork_self_link(config.project_id, config.region, resource_name),
        "network": network_name,
        "network_link": network_link,
        "cidr": network.cidr,
        "region": config.region,
        "tag": _subnet_tag(range_id, network.name),
        # ACES segments via node ACLs (realized separately); the base firewall
        # allows intra-subnet traffic only.
        "connected_source_ranges": [network.cidr],
        "ip_assignments": dict(zip(keys, usable, strict=False)),
        "instances": [],
    }


def _instance_plans_for_node(
    node: AcesPlanNode,
    subnet: SubnetPlan,
    range_id: int,
    resolve_image: Callable[[AcesPlanNode], GCERangeImageProfile],
) -> list[InstancePlan]:
    """Render one InstancePlan per ``count`` for a node placed on ``subnet``."""
    profile = resolve_image(node)
    os_type = node.os_family or "linux"
    plans: list[InstancePlan] = []
    for index in range(node.count):
        resource_name = _short_resource_name("shifter-r", range_id, subnet["name"], node.name, index)
        plans.append(
            {
                "name": f"{node.name}-{index}" if node.count > 1 else node.name,
                "uuid": _instance_key(node, index),
                "resource_name": resource_name,
                "address_name": _short_resource_name(resource_name, "ip"),
                "subnet_name": subnet["name"],
                "subnet_resource_name": subnet["resource_name"],
                "subnetwork_link": subnet["self_link"],
                "private_ip": subnet["ip_assignments"][_instance_key(node, index)],
                # Neutral labels only: no cyberscript role/os_type enums or
                # scenario secrets. os_type carries the OS family for the guest
                # boot dialect (linux vs windows) that instance_resource keys on.
                "role": "aces-node",
                "os_type": os_type,
                "asset_type": "gce_vm",
                "tags": [_network_tag(range_id), subnet["tag"], node_tag(range_id, node.address)],
                "profile": profile,
                "source": {},
                "ssh_username": _DEFAULT_SSH_USERNAME,
                "host_ssh_username": _DEFAULT_SSH_USERNAME,
                "ssh_port": _DEFAULT_SSH_PORT,
                # ACES account/access realization remains owned by its native
                # plan and must not inherit legacy scenario access channels.
                "participant_access_channels": [],
                "attach_service_account": False,
            }
        )
    return plans
