"""Build a GCE range-cell plan from a serialized RAES plan (ADR-031, ADR-032).

The RAES-native counterpart of ``gcp_range_cell_plan.render_range_cell_plan``:
it maps the neutral :class:`raes_plan.RaesPlan` (parsed from the serialized RAES
ProvisioningPlan) into the provisioner's neutral ``RangeCellPlan`` so the whole
GCE apply layer (``_ensure_network``/``_ensure_subnetwork``/``_ensure_firewall``/
``_ensure_address`` + resource renderers) is reused unchanged. It carries **no**
cyberscript scenario semantics: the image comes from the authored RAES ``source``
resolved against the tenant registry (``resolve_gce_image``), sizing from
``resources``, and ``os_family`` drives only the OS realization dialect. Nodes are
placed on their authored network when one is selected. The GCE adapter supplies
a backend-owned subnet when the portable plan leaves that selection open; each
``count`` yields a distinct instance.

Base range firewalls (intra-subnet allow, management, egress posture) are reused
from ``gcp_range_cell_firewall.build_firewall_plan``; authored node ACLs are
realized as additional firewall rules by :mod:`raes_gcp_firewall` (layered on
top).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

from config import (
    GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
    GCE_BOOTSTRAP_PREPROMOTED_DC,
    GCERangeCellConfig,
    GCERangeImageProfile,
    gce_image_profile_fingerprint,
    load_gce_range_cell_config,
)
from gcp_range_cell_firewall import build_firewall_plan
from gcp_range_cell_naming import (
    _network_name_from_id,
    _network_self_link,
    _network_tag,
    _short_resource_name,
    _subnet_tag,
    _subnetwork_self_link,
    range_router_nat_plan,
    shared_router_nat_plan,
)
from gcp_range_cell_plan import _range_labels, range_telemetry_plan
from gcp_range_cell_types import (
    DEFAULT_GCE_EGRESS_POLICY,
    FirewallPlan,
    GceEgressPolicy,
    InstancePlan,
    RangeCellPlan,
    RouterNatPlan,
    SubnetPlan,
)
from raes_access import RealizedAccessBinding
from raes_gcp_adapter import RaesGceAdapterError, adapt_raes_plan_for_gce
from raes_gcp_addressing import instance_key as _instance_key
from raes_gcp_addressing import ip_assignments as _ip_assignments
from raes_gcp_firewall import (
    acl_cidr_lookup,
    build_acl_firewalls,
    build_service_firewalls,
    node_tag,
    service_base_priority,
)
from raes_gcp_plan_errors import RaesGcePlanError
from raes_gcp_vpn_plan import RaesGceVpnAccess, vpn_pool_firewalls
from raes_plan import RaesPlan, RaesPlanNetwork, RaesPlanNode

#: Default guest login user the provisioner injects (management reachability). The
#: participant-facing user is a later participant-runtime concern (not provisioning).
_DEFAULT_SSH_USERNAME = "raes"
#: A prepromoted-domain-controller guest is a pre-baked Windows DC. Its accounts
#: are domain accounts (a promoted DC has no local SAM), so the GCE guest agent
#: cannot create the "raes" local user the standard RAES node setup connects as,
#: and raes@22 is refused. The Windows boot script authorizes the provisioner key
#: via ``administrators_authorized_keys`` (any Administrators-group member), so
#: guest setup connects as the built-in domain "Administrator". Mirrors the legacy
#: get_ssh_username(role="dc") host access on the RAES-native path.
_WINDOWS_DC_ADMIN_USERNAME = "Administrator"


@dataclass(frozen=True)
class RaesGcePlanOptions:
    """Optional realization inputs grouped at the GCE adapter boundary."""

    config: GCERangeCellConfig | None = None
    access_bindings: Sequence[RealizedAccessBinding] = ()
    egress_policy: GceEgressPolicy = DEFAULT_GCE_EGRESS_POLICY
    allocated_network_cidrs: Sequence[tuple[str, str]] | None = None
    reconstruct_for_teardown: bool = False
    remote_access: RaesGceVpnAccess | None = None


def build_raes_range_cell_plan(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    resolve_image: Callable[[RaesPlanNode], GCERangeImageProfile],
    options: GCERangeCellConfig | RaesGcePlanOptions | None = None,
    **legacy: object,
) -> RangeCellPlan:
    """Render the deterministic GCE range-cell plan for a parsed RAES plan.

    ``resolve_image`` maps one node to its concrete image/sizing profile (wired to
    the tenant image registry by the caller), keeping this builder pure/testable.

    ``access_bindings`` are the #1710 participant-access declarations already
    joined to this plan by ``raes_access.join_participant_access``. They are the
    only source of a node's participant channels: authored services, ACLs, OS
    family, image, and account existence never synthesize one.

    ``egress_policy.model_broker`` is separately admitted and bound to the deployment VIP;
    neither scenario authorship nor installation enablement grants it.
    """
    resolved_options = _plan_options(options, legacy)
    resolved_config = resolved_options.config or load_gce_range_cell_config()
    authored_networks = {network.address: network for network in raes_plan.networks}
    try:
        raes_plan = adapt_raes_plan_for_gce(
            raes_plan,
            resolved_config,
            allocated_network_cidrs=resolved_options.allocated_network_cidrs,
            reconstruct_for_teardown=resolved_options.reconstruct_for_teardown,
        )
    except RaesGceAdapterError as exc:
        raise RaesGcePlanError(str(exc)) from None
    network_name, network_link, manage_network = _network_placement(resolved_config, range_id)

    networks_by_address = {network.address: network for network in raes_plan.networks}
    nodes_by_network = _nodes_by_network(raes_plan)

    subnet_plans = [
        _subnet_plan(
            network,
            authored_networks.get(network.address),
            nodes_by_network.get(network.address, ()),
            range_id,
            resolved_config,
            network_name,
            network_link,
        )
        for network in raes_plan.networks
    ]
    subnet_by_address = {
        network.address: subnet for network, subnet in zip(raes_plan.networks, subnet_plans, strict=True)
    }

    access_by_node = _access_by_node(resolved_options.access_bindings)

    # The deployment may expose a broker endpoint without admitting this range
    # to use it. Only a range-bound broker capability suppresses the host
    # identity; broker-free ranges keep their direct keyless Vertex path.
    attach_model_identity = (
        bool(resolved_config.service_account_email) and resolved_options.egress_policy.model_broker is None
    )
    instance_plans: list[InstancePlan] = []
    for network in raes_plan.networks:
        subnet = subnet_by_address[network.address]
        for node in nodes_by_network.get(network.address, ()):
            instance_plans.extend(
                _instance_plans_for_node(
                    node,
                    subnet,
                    range_id,
                    resolve_image,
                    access_by_node.get(node.address, ()),
                    attach_model_identity=attach_model_identity,
                )
            )

    _reject_unplaceable_nodes(raes_plan, networks_by_address)

    plan: RangeCellPlan = {
        "project_id": resolved_config.project_id,
        "region": resolved_config.region,
        "zone": resolved_config.zone,
        "request_uuid": request_uuid,
        "range_id": range_id,
        "private_google_access": resolved_config.private_google_access,
        "labels": _range_labels(range_id, request_uuid),
        "network": {"name": network_name, "self_link": network_link},
        "telemetry": range_telemetry_plan(resolved_config.range_telemetry),
        "manage_network": manage_network,
        "subnets": subnet_plans,
        "instances": instance_plans,
        "firewalls": _all_firewalls(
            range_id,
            subnet_plans,
            instance_plans,
            raes_plan,
            resolved_config,
            resolved_options.egress_policy,
        )
        + vpn_pool_firewalls(range_id, instance_plans, resolved_options.remote_access),
    }
    # A non-`none` range owns an explicit Cloud Router + NAT scoped to its subnets;
    # a `none` (zero-egress) range omits it so its subnets carry no NAT path.
    if (resolved_options.egress_policy.mode or "status-quo").strip().lower() != "none":
        if manage_network:
            plan["router_nat"] = cast(
                RouterNatPlan, range_router_nat_plan(range_id, [subnet["self_link"] for subnet in subnet_plans])
            )
        else:
            plan["shared_nat"] = cast(
                RouterNatPlan, shared_router_nat_plan(network_name, [subnet["self_link"] for subnet in subnet_plans])
            )
    return plan


def _plan_options(
    options: GCERangeCellConfig | RaesGcePlanOptions | None, legacy: dict[str, object]
) -> RaesGcePlanOptions:
    """Handle plan options."""
    resolved = options if isinstance(options, RaesGcePlanOptions) else RaesGcePlanOptions(config=options)
    allowed = {"config", "access_bindings", "egress_policy", "allocated_network_cidrs", "reconstruct_for_teardown"}
    if set(legacy) - allowed:
        raise TypeError("unknown GCE plan option")
    return RaesGcePlanOptions(
        remote_access=resolved.remote_access,
        config=cast(GCERangeCellConfig | None, legacy.get("config", resolved.config)),
        access_bindings=cast(Sequence[RealizedAccessBinding], legacy.get("access_bindings", resolved.access_bindings)),
        egress_policy=cast(GceEgressPolicy, legacy.get("egress_policy", resolved.egress_policy)),
        allocated_network_cidrs=cast(
            Sequence[tuple[str, str]] | None,
            legacy.get("allocated_network_cidrs", resolved.allocated_network_cidrs),
        ),
        reconstruct_for_teardown=cast(bool, legacy.get("reconstruct_for_teardown", resolved.reconstruct_for_teardown)),
    )


def _all_firewalls(
    range_id: int,
    subnet_plans: list[SubnetPlan],
    instance_plans: list[InstancePlan],
    raes_plan: RaesPlan,
    config: GCERangeCellConfig,
    egress_policy: GceEgressPolicy = DEFAULT_GCE_EGRESS_POLICY,
) -> list[FirewallPlan]:
    """Base range firewalls (reused, neutral) plus authored node ACL and service firewalls.

    Authored ``services`` are realized as fail-closed, range-scoped per-node-tag ingress
    (ADR-032-R8): admitted only from the concrete CIDRs of networks in *this* compiled
    range, at a priority strictly above the node's ACL band so authored ACL denies win.
    """
    firewalls = build_firewall_plan(
        range_id,
        subnet_plans,
        config,
        instance_plans=instance_plans,
        egress_policy=egress_policy,
    )
    cidr_lookup = acl_cidr_lookup(raes_plan.networks)
    # Validate the range-scoped service source set once, up front, only when needed --
    # so a universal or portal-overlapping CIDR fails the whole plan before mutation.
    service_source_cidrs = (
        _service_source_cidrs(subnet_plans, config) if any(node.services for node in raes_plan.nodes) else ()
    )
    for node in raes_plan.nodes:
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
            raise RaesGcePlanError(
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


def _primary_network(node: RaesPlanNode) -> str | None:
    """Return the node's primary (first) declared network address, or None."""
    return node.network_addresses[0] if node.network_addresses else None


def _nodes_by_network(raes_plan: RaesPlan) -> dict[str, list[RaesPlanNode]]:
    """Group nodes by their primary network address (declaration order preserved)."""
    grouped: dict[str, list[RaesPlanNode]] = {}
    for node in raes_plan.nodes:
        primary = _primary_network(node)
        if primary is not None:
            grouped.setdefault(primary, []).append(node)
    return grouped


def _reject_unplaceable_nodes(raes_plan: RaesPlan, networks_by_address: dict[str, RaesPlanNetwork]) -> None:
    """Fail loud on nodes with no network or an undeclared primary network."""
    for node in raes_plan.nodes:
        primary = _primary_network(node)
        if primary is None:
            raise RaesGcePlanError(f"node {node.address!r} declares no network to attach to")
        if primary not in networks_by_address:
            raise RaesGcePlanError(f"node {node.address!r} references undeclared network {primary!r}")


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
    ``raes_range_ops`` forwards ``str(exc)`` into published failure events.
    """
    network = ipaddress.ip_network(cidr)
    if not isinstance(network, ipaddress.IPv4Network):
        raise RaesGcePlanError("GCE range cells require IPv4 subnets; got an unsupported network address family")
    if network.num_addresses > _MAX_SUBNET_ADDRESSES:
        raise RaesGcePlanError(f"GCE range subnet {cidr} is larger than /16; refusing to enumerate host addresses")
    return [str(host) for host in list(network.hosts())[2:-2]]


def _instance_keys(nodes: tuple[RaesPlanNode, ...] | list[RaesPlanNode]) -> list[str]:
    """Return the ordered per-instance assignment keys (one per node ``count``)."""
    return [_instance_key(node, index) for node in nodes for index in range(node.count)]


def _subnet_plan(
    network: RaesPlanNetwork,
    authored_network: RaesPlanNetwork | None,
    nodes: tuple[RaesPlanNode, ...] | list[RaesPlanNode],
    range_id: int,
    config: GCERangeCellConfig,
    network_name: str,
    network_link: str,
) -> SubnetPlan:
    """Render one subnet plan from an RAES network + the nodes placed on it."""
    if not network.cidr:
        raise RaesGcePlanError(f"RAES network {network.address!r} has no cidr to provision a GCE subnet")
    resource_name = _short_resource_name("shifter-r", range_id, network.name)
    keys = _instance_keys(nodes)
    usable = _usable_host_ips(network.cidr)
    if len(keys) > len(usable):
        raise RaesGcePlanError(
            f"subnet {network.cidr} has {len(usable)} usable addresses but {len(keys)} instances were requested"
        )
    assignments = _ip_assignments(network, authored_network, nodes, keys, usable)
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
        # RAES segments via node ACLs (realized separately); the base firewall
        # allows intra-subnet traffic only.
        "connected_source_ranges": [network.cidr],
        "ip_assignments": assignments,
        "instances": [],
    }


def _access_by_node(
    access_bindings: Sequence[RealizedAccessBinding],
) -> dict[str, tuple[RealizedAccessBinding, ...]]:
    """Group already-joined participant access by target node address."""
    grouped: dict[str, list[RealizedAccessBinding]] = {}
    for binding in access_bindings:
        grouped.setdefault(binding.target_address, []).append(binding)
    return {address: tuple(bindings) for address, bindings in grouped.items()}


def _instance_plans_for_node(
    node: RaesPlanNode,
    subnet: SubnetPlan,
    range_id: int,
    resolve_image: Callable[[RaesPlanNode], GCERangeImageProfile],
    access_bindings: Sequence[RealizedAccessBinding] = (),
    *,
    attach_model_identity: bool = False,
) -> list[InstancePlan]:
    """Render one InstancePlan per ``count`` for a node placed on ``subnet``.

    ``access_bindings`` carry this node's declared participant channels. The join
    already proved a node bearing access materializes exactly one instance, so
    the channels bind to that instance without any fan-out choice.
    """
    profile = resolve_image(node)
    # A promoted domain controller has no local SAM. Its existing domain
    # administrator receives the key through administrators_authorized_keys.
    host_ssh_username = profile.host_ssh_username or (
        _WINDOWS_DC_ADMIN_USERNAME
        if profile.bootstrap_capability == GCE_BOOTSTRAP_PREPROMOTED_DC
        else _DEFAULT_SSH_USERNAME
    )
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
                "role": "raes-node",
                "os_type": os_type,
                "asset_type": "gce_vm",
                "tags": [_network_tag(range_id), subnet["tag"], node_tag(range_id, node.address)],
                "profile": profile,
                "image_key": "",
                "image_profile_fingerprint": gce_image_profile_fingerprint(profile),
                "source": {},
                "ssh_username": (
                    profile.participant_username
                    if profile.bootstrap_capability == GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST
                    else _DEFAULT_SSH_USERNAME
                ),
                "host_ssh_username": host_ssh_username,
                "ssh_port": profile.host_ssh_port,
                # The closed realized access binding the portal authorizes
                # against (#1349), sourced only from the authored RAES
                # interactive_access declarations joined to this plan (#1710).
                # Empty when the scenario authored none.
                "participant_access_channels": [binding.channel for binding in access_bindings],
                "participant_access_usernames": {binding.channel: binding.username for binding in access_bindings},
                "attach_service_account": attach_model_identity,
            }
        )
    return plans
