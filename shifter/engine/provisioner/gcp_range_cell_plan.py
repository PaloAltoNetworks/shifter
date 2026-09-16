"""Resource planning helpers for GCE-backed range cells."""

from __future__ import annotations

import ipaddress
from dataclasses import replace
from typing import cast

from shared.range_cells import RangeCellContractError, validate_gcp_vm_range_cell_request

from config import GCERangeCellConfig, load_gce_range_cell_config
from gcp_range_cell_firewall import build_firewall_plan
from gcp_range_cell_naming import (
    _label_value,
    _network_name_from_id,
    _network_self_link,
    _short_resource_name,
    _subnet_tag,
    _subnetwork_self_link,
    range_router_nat_plan,
)
from gcp_range_cell_scenario import build_instance_plans, realize_range_spec
from gcp_range_cell_types import (
    DEFAULT_GCE_EGRESS_POLICY,
    ComputeResource,
    FirewallEntry,
    FirewallPlan,
    GceEgressPolicy,
    InstancePlan,
    NetworkPlan,
    OpenVpnGatewayPlan,
    RangeCellPlan,
    ResourceDict,
    RouterNatPlan,
    ScenarioInstance,
    SubnetPlan,
)
from gcp_vpn_identity import gcp_vpn_gateway_pool_service_account_email

_MANAGED_BY_LABEL = "shifter-provisioner"

__all__ = [
    "ComputeResource",
    "FirewallEntry",
    "FirewallPlan",
    "InstancePlan",
    "NetworkPlan",
    "OpenVpnGatewayPlan",
    "RangeCellPlan",
    "ResourceDict",
    "ScenarioInstance",
    "SubnetPlan",
    "render_range_cell_plan",
]


def _resource_dicts(value: object) -> list[ResourceDict]:
    """Return dict items from a dynamic scenario payload list."""
    if not isinstance(value, list):
        return []
    return [cast(ResourceDict, item) for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    """Return string values from a dynamic scenario payload list."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _range_labels(range_id: int, request_uuid: str) -> dict[str, str]:
    """Return labels shared by resources in one range cell."""
    return {
        "managed-by": _MANAGED_BY_LABEL,
        "range-id": _label_value(range_id),
        "request-id": _label_value(request_uuid),
    }


def _assign_instance_ips(subnet_cidr: str, instances: list[ScenarioInstance]) -> dict[str, str]:
    """Assign deterministic internal IPs while skipping GCP-reserved addresses."""
    network = ipaddress.ip_network(subnet_cidr)
    if not isinstance(network, ipaddress.IPv4Network):
        raise RuntimeError(f"GCE range cells require IPv4 subnets, got {subnet_cidr}")

    hosts = list(network.hosts())
    usable = hosts[2:-2]
    if len(instances) > len(usable):
        raise RuntimeError(
            f"Subnet {subnet_cidr} has {len(usable)} usable GCE guest addresses, "
            f"but {len(instances)} instances were requested"
        )

    assignments: dict[str, str] = {}
    for index, instance in enumerate(instances):
        key = str(instance.get("uuid") or instance.get("name") or f"asset-{index}")
        assignments[key] = str(usable[index])
    return assignments


def _connected_source_ranges(subnet: ResourceDict, subnet_by_name: dict[str, ResourceDict]) -> list[str]:
    """Return CIDRs allowed to reach one subnet from declared peer links."""
    source_ranges = [str(subnet.get("cidr", "")).strip()]
    for peer_name in _string_list(subnet.get("connected_to")):
        peer = subnet_by_name.get(peer_name)
        if peer:
            source_ranges.append(str(peer.get("cidr", "")).strip())
    return [cidr for cidr in source_ranges if cidr]


def _build_subnet_plans(
    *,
    variables: ResourceDict,
    config: GCERangeCellConfig,
    network_name: str,
    network_link: str,
    require_images: bool,
) -> list[SubnetPlan]:
    """Render deterministic subnetwork plans from range variables.

    Provision (``require_images=True``) needs a CIDR to create the subnet and
    assign instance IPs. Destroy (``require_images=False``) deletes subnets by
    resource name, so a subnet whose CIDR was never allocated (e.g. auto-cleanup
    after a provision that failed before CIDR allocation) is tolerated with an
    empty CIDR rather than raising.
    """
    range_id = int(str(variables["range_id"]))
    subnets = _resource_dicts(variables.get("subnets"))
    subnet_by_name = {str(subnet.get("name", "")): subnet for subnet in subnets}
    plans: list[SubnetPlan] = []
    for subnet in subnets:
        subnet_name = str(subnet.get("name", "")).strip()
        subnet_uuid = str(subnet.get("uuid", "")).strip()
        subnet_cidr = str(subnet.get("cidr", "")).strip()
        if not subnet_name or not subnet_uuid:
            raise RuntimeError(f"GCE range subnet requires name and uuid: {subnet!r}")
        if require_images and not subnet_cidr:
            raise RuntimeError(f"GCE range subnet requires a cidr to provision: {subnet!r}")
        instances = _resource_dicts(subnet.get("instances"))
        resource_name = _short_resource_name("shifter-r", range_id, subnet_name)
        plans.append(
            {
                "name": subnet_name,
                "uuid": subnet_uuid,
                "resource_name": resource_name,
                "self_link": _subnetwork_self_link(config.project_id, config.region, resource_name),
                "network": network_name,
                "network_link": network_link,
                "cidr": subnet_cidr,
                "region": config.region,
                "tag": _subnet_tag(range_id, subnet_name),
                "connected_source_ranges": _connected_source_ranges(subnet, subnet_by_name),
                "ip_assignments": _assign_instance_ips(subnet_cidr, instances) if subnet_cidr else {},
                "instances": instances,
            }
        )
    return plans


def _require_openvpn_capable_config(config: GCERangeCellConfig) -> None:
    """Reject configurations that cannot realize the authorized capability."""
    if (
        config.network_mode != "shared-vpc"
        or not config.private_google_access
        or not config.linux.source_image
        or not config.portal_network_cidrs
        or "https://www.googleapis.com/auth/cloud-platform" not in config.service_account_scopes
    ):
        raise RuntimeError("The authorized OpenVPN capability cannot be realized by this GCE adapter")


def _free_guest_address(subnet: SubnetPlan) -> str:
    """Return the first usable guest address not already assigned in the subnet."""
    network = ipaddress.ip_network(subnet["cidr"])
    used = set(subnet["ip_assignments"].values())
    available = [str(address) for address in list(network.hosts())[2:-2] if str(address) not in used]
    if not available:
        raise RuntimeError("The Kali subnet has no address available for its OpenVPN gateway")
    return available[0]


def _openvpn_gateway_plan(
    range_id: int,
    vpn_gateway_pool_slot: int | None,
    instance_plans: list[InstancePlan],
    subnet_plans: list[SubnetPlan],
    config: GCERangeCellConfig,
    remote_access: dict[str, object] | None,
    *,
    require_provision_values: bool,
) -> OpenVpnGatewayPlan | None:
    """Plan the request-owned OpenVPN gateway adjacent to the authorized Kali.

    ``vpn_gateway_pool_slot`` is the range's reserved index into the pre-provisioned
    gateway SA pool (ADR-008-R7); the gateway VM runs as that pooled identity.
    """
    if remote_access is None:
        return None
    if vpn_gateway_pool_slot is None and require_provision_values:
        raise RuntimeError(
            f"Range {range_id} requests OpenVPN but has no reserved gateway pool slot; "
            "it was not created with an OpenVPN capability"
        )
    if require_provision_values:
        _require_openvpn_capable_config(config)
    targets = [instance for instance in instance_plans if instance["uuid"] == remote_access["target_ref"]]
    if len(targets) != 1:
        raise RuntimeError("OpenVPN capability must identify exactly one GCE range member")
    target = targets[0]
    subnet = next(item for item in subnet_plans if item["name"] == target["subnet_name"])
    private_ip = _free_guest_address(subnet) if subnet["cidr"] else ""
    return {
        "resource_name": _short_resource_name("shifter-r", range_id, "vpn-gateway"),
        "address_name": _short_resource_name("shifter-r", range_id, "vpn-gateway-ip"),
        "private_ip": private_ip,
        "subnet_resource_name": subnet["resource_name"],
        "subnetwork_link": subnet["self_link"],
        "target_ref": target["uuid"],
        "target_ip": target["private_ip"],
        "tag": _short_resource_name("shifter-r", range_id, "vpn-gateway"),
        "profile": config.get_profile(role="victim", os_type="ubuntu"),
        "service_account_email": (
            gcp_vpn_gateway_pool_service_account_email(config.project_id, vpn_gateway_pool_slot)
            if vpn_gateway_pool_slot is not None
            else ""
        ),
    }


def render_range_cell_plan(
    request_uuid: str,
    variables: ResourceDict,
    config: GCERangeCellConfig | None = None,
    *,
    require_images: bool = True,
    vpn_gateway_pool_slot: int | None = None,
    range_host_pool_slot: int | None = None,
    egress_policy: GceEgressPolicy = DEFAULT_GCE_EGRESS_POLICY,
) -> RangeCellPlan:
    """Render the deterministic GCE resources for one range cell.

    ``vpn_gateway_pool_slot`` is the range's reserved gateway SA pool slot
    (ADR-008-R7), threaded to the OpenVPN gateway plan; ``None`` for ranges
    without an OpenVPN capability.

    ``egress_policy.model_broker`` is explicitly admitted, never inferred from
    installation enablement. Its VIP is bound to ``config.model_broker_vip``.
    """
    validated_request = validate_gcp_vm_range_cell_request(variables)
    operation = validated_request["operation"]
    if operation["request_id"] != request_uuid:
        raise RangeCellContractError("range-cell request_id does not match the invoked operation")
    # The pinned effective egress posture rides in the operation block (PLAT-238);
    # it is authoritative over the caller default so apply and destroy realize and
    # tear down the same firewall + range-owned NAT topology.
    egress_policy = replace(egress_policy, mode=str(operation.get("egress_mode", egress_policy.mode)))
    resolved_config = config or load_gce_range_cell_config()
    realized_variables = realize_range_spec(
        validated_request,
        config=resolved_config,
        require_network_bindings=require_images,
        require_supported_capabilities=require_images,
    )
    range_id = int(operation["range_id"])
    if resolved_config.network_mode == "shared-vpc":
        # Range subnets live in the pre-existing, platform-peered range VPC; the
        # range never creates or deletes the VPC itself.
        network_link = resolved_config.network_id
        network_name = _network_name_from_id(resolved_config.network_id)
        manage_network = False
    else:
        network_name = _short_resource_name("shifter-range", range_id)
        network_link = _network_self_link(resolved_config.project_id, network_name)
        manage_network = True
    subnet_plans = _build_subnet_plans(
        variables=realized_variables,
        config=resolved_config,
        network_name=network_name,
        network_link=network_link,
        require_images=require_images,
    )
    instance_plans = cast(
        list[InstancePlan],
        build_instance_plans(
            range_id=range_id,
            config=resolved_config,
            subnet_plans=cast(list[ResourceDict], subnet_plans),
            access_declarations=cast(list[ResourceDict], realized_variables["access_declarations"]),
            require_images=require_images,
            range_host_pool_slot=range_host_pool_slot,
        ),
    )
    remote_access = validated_request["remote_access"]
    vpn_gateway = _openvpn_gateway_plan(
        range_id,
        vpn_gateway_pool_slot,
        instance_plans,
        subnet_plans,
        resolved_config,
        remote_access,
        require_provision_values=require_images,
    )
    plan: RangeCellPlan = {
        "project_id": resolved_config.project_id,
        "region": resolved_config.region,
        "zone": resolved_config.zone,
        "request_uuid": request_uuid,
        "range_id": range_id,
        "private_google_access": resolved_config.private_google_access,
        "labels": _range_labels(range_id, request_uuid),
        "network": {
            "name": network_name,
            "self_link": network_link,
        },
        "manage_network": manage_network,
        "subnets": subnet_plans,
        "instances": instance_plans,
        "firewalls": build_firewall_plan(
            range_id,
            subnet_plans,
            resolved_config,
            vpn_gateway,
            instance_plans=instance_plans,
            include_optional_cleanup=not require_images,
            egress_policy=egress_policy,
        ),
    }
    if vpn_gateway is not None:
        plan["vpn_gateway"] = vpn_gateway
    # A non-`none` range owns an explicit Cloud Router + NAT scoped to its subnets;
    # a `none` (zero-egress) range omits it so its subnets carry no NAT path
    # (PLAT-238, ADR-026-R6), mirroring the RAES plan builder.
    if egress_policy.mode.strip().lower() != "none":
        plan["router_nat"] = cast(
            RouterNatPlan,
            range_router_nat_plan(range_id, [subnet["self_link"] for subnet in subnet_plans]),
        )
    return plan
