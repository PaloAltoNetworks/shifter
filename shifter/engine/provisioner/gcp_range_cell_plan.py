"""Resource planning helpers for GCE-backed range cells."""

from __future__ import annotations

import ipaddress
from typing import NotRequired, TypedDict, cast

from config import GCERangeCellConfig, GCERangeImageProfile, load_gce_range_cell_config
from executors.factory import get_ssh_username
from gcp_range_cell_naming import (
    _label_value,
    _network_name_from_id,
    _network_self_link,
    _network_tag,
    _short_resource_name,
    _subnet_tag,
    _subnetwork_self_link,
)

_MANAGED_BY_LABEL = "shifter-provisioner"

_DEFAULT_SSH_PORT = 22

# private.googleapis.com VIP range. Private Google Access on the range subnet,
# the range VPC's private-googleapis DNS zone, and a route for this /30 (all in
# the range VPC Terraform) let no-external-IP guests reach Google APIs over
# Google's internal fabric. This is the only egress hole the range opens when
# private_google_access is set, so guests reach Vertex AI / Cloud Storage /
# Secret Manager while staying off the general internet.
_GOOGLE_PRIVATE_API_VIP_CIDR = "199.36.153.8/30"  # NOSONAR

# Scenario image keys whose range host is an Ubuntu Docker host: the
# participant-facing service (e.g. the Polaris Kali container) publishes the
# host's :22/:3389, so the provisioner drives the host sshd on the management
# port as the host login user, keeping :22/:3389 for participant access. The
# scenario image key is translated to a validated GCE profile here rather than
# passing the AWS ``ami_key``/``instance_type`` through to Compute Engine.
_DOCKER_HOST_AMI_KEYS = frozenset({"polaris-vm"})
_DOCKER_HOST_SSH_USERNAME = "ubuntu"

ResourceDict = dict[str, object]
ComputeResource = dict[str, object]
ScenarioInstance = ResourceDict


class NetworkPlan(TypedDict):
    """Planned Compute Engine network resource."""

    name: str
    self_link: str


class SubnetPlan(TypedDict):
    """Planned Compute Engine subnetwork resource."""

    name: str
    uuid: str
    resource_name: str
    self_link: str
    network: str
    network_link: str
    cidr: str
    region: str
    tag: str
    connected_source_ranges: list[str]
    ip_assignments: dict[str, str]
    instances: list[ScenarioInstance]


class FirewallEntry(TypedDict, total=False):
    """Compute Engine firewall allow/deny entry."""

    IPProtocol: str
    ports: list[str]


class FirewallPlan(TypedDict):
    """Planned Compute Engine firewall resource."""

    name: str
    direction: str
    priority: int
    target_tags: list[str]
    source_ranges: NotRequired[list[str]]
    destination_ranges: NotRequired[list[str]]
    allowed: NotRequired[list[FirewallEntry]]
    denied: NotRequired[list[FirewallEntry]]


class InstancePlan(TypedDict):
    """Planned Compute Engine instance and address resources."""

    name: str
    uuid: str
    resource_name: str
    address_name: str
    subnet_name: str
    subnet_resource_name: str
    subnetwork_link: str
    private_ip: str
    role: str
    os_type: str
    asset_type: str
    tags: list[str]
    profile: GCERangeImageProfile
    source: ScenarioInstance
    ssh_username: str
    host_ssh_username: str
    ssh_port: int


class RangeCellPlan(TypedDict):
    """Complete resource plan for a single GCE range cell."""

    project_id: str
    region: str
    zone: str
    request_uuid: str
    range_id: int
    private_google_access: bool
    labels: dict[str, str]
    network: NetworkPlan
    # True when the range owns its VPC (vpc-per-range) and apply/destroy must
    # create/delete it. False in shared-vpc mode, where the VPC is the pre-existing
    # platform-peered range network and only per-range subnets/firewalls are owned.
    manage_network: bool
    subnets: list[SubnetPlan]
    instances: list[InstancePlan]
    firewalls: list[FirewallPlan]


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


def _instance_assignment_key(instance: ScenarioInstance, index: int) -> str:
    """Return the stable key used to map an instance to an assigned IP."""
    return str(instance.get("uuid") or instance.get("name") or f"asset-{index}")


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


def _profile_for_instance(
    config: GCERangeCellConfig,
    instance: ScenarioInstance,
    *,
    require_images: bool,
) -> GCERangeImageProfile:
    """Resolve the image profile for one range instance.

    Machine size comes from the GCE range profile (``GCP_RANGE_*_MACHINE_TYPE``),
    never the scenario's AWS ``instance_type`` (e.g. ``m5.2xlarge``), which is an
    EC2 shape and is not a valid Compute Engine machine type.
    """
    if not require_images:
        return GCERangeImageProfile()
    return config.get_profile(
        role=str(instance.get("role", "victim")),
        os_type=str(instance.get("os_type", instance.get("os", "ubuntu"))),
    )


def _host_access(
    config: GCERangeCellConfig, instance: ScenarioInstance, os_type: str, role: str
) -> tuple[str, str, int]:
    """Resolve ``(participant_ssh_username, host_ssh_username, host_ssh_port)``.

    The participant SSH user is what the portal terminal / Guacamole connects
    as on :22 (the participant-facing service). The host SSH user + port are
    what the provisioner drives for guest setup.

    Docker-host scenarios (whose participant container publishes host :22)
    split the two: the participant reaches the container as its native user on
    :22, while the provisioner reaches the host sshd on the management port as
    the host login user. Native single-service guests use the same user on :22
    for both.
    """
    participant_user = get_ssh_username(os_type, role)
    ami_key = str(instance.get("ami_key", "")).strip().lower()
    if ami_key in _DOCKER_HOST_AMI_KEYS:
        return participant_user, _DOCKER_HOST_SSH_USERNAME, config.host_mgmt_ssh_port
    return participant_user, participant_user, _DEFAULT_SSH_PORT


def _build_instance_plans(
    *,
    variables: ResourceDict,
    config: GCERangeCellConfig,
    subnet_plans: list[SubnetPlan],
    require_images: bool,
) -> list[InstancePlan]:
    """Render deterministic instance plans for every planned subnet."""
    range_id = int(str(variables["range_id"]))
    plans: list[InstancePlan] = []
    for subnet_plan in subnet_plans:
        for index, instance in enumerate(subnet_plan["instances"]):
            key = _instance_assignment_key(instance, index)
            role = str(instance.get("role", "victim"))
            os_type = str(instance.get("os_type", instance.get("os", "ubuntu")))
            ssh_username, host_ssh_username, ssh_port = _host_access(config, instance, os_type, role)
            resource_name = _short_resource_name(
                "shifter-r",
                range_id,
                subnet_plan["name"],
                instance.get("name") or instance.get("uuid") or index,
            )
            plans.append(
                {
                    "name": str(instance.get("name", "")).strip() or resource_name,
                    "uuid": str(instance.get("uuid", "")),
                    "resource_name": resource_name,
                    "address_name": _short_resource_name(resource_name, "ip"),
                    "subnet_name": subnet_plan["name"],
                    "subnet_resource_name": subnet_plan["resource_name"],
                    "subnetwork_link": subnet_plan["self_link"],
                    # Destroy (no CIDR, empty ip_assignments) deletes by resource
                    # name and needs no private IP; provision always has the key.
                    "private_ip": subnet_plan["ip_assignments"].get(key, ""),
                    "role": role,
                    "os_type": os_type,
                    "asset_type": "gce_vm",
                    "tags": [_network_tag(range_id), subnet_plan["tag"], _short_resource_name("shifter-role", role)],
                    "profile": _profile_for_instance(config, instance, require_images=require_images),
                    "source": instance,
                    "ssh_username": ssh_username,
                    "host_ssh_username": host_ssh_username,
                    "ssh_port": ssh_port,
                }
            )
    return plans


def _firewall_plan(
    range_id: int,
    subnet_plans: list[SubnetPlan],
    config: GCERangeCellConfig,
) -> list[FirewallPlan]:
    """Render the firewall plan for internal range traffic and management."""
    range_tag = _network_tag(range_id)
    subnet_cidrs = [subnet["cidr"] for subnet in subnet_plans]
    firewalls: list[FirewallPlan] = []
    for subnet in subnet_plans:
        firewalls.append(
            {
                "name": _short_resource_name("shifter-r", range_id, subnet["name"], "ingress"),
                "direction": "INGRESS",
                "priority": 1000,
                "target_tags": [subnet["tag"]],
                "source_ranges": subnet["connected_source_ranges"],
                "allowed": [{"IPProtocol": "all"}],
            }
        )
    if config.portal_network_cidrs:
        # SSH (participant + native-guest host), RDP, and the Docker-host
        # management sshd port (Polaris host, whose Kali container binds :22).
        mgmt_ports = ["22", "3389"]
        if str(config.host_mgmt_ssh_port) not in mgmt_ports:
            mgmt_ports.append(str(config.host_mgmt_ssh_port))
        firewalls.append(
            {
                "name": _short_resource_name("shifter-r", range_id, "mgmt"),
                "direction": "INGRESS",
                "priority": 900,
                "target_tags": [range_tag],
                "source_ranges": list(config.portal_network_cidrs),
                "allowed": [{"IPProtocol": "tcp", "ports": mgmt_ports}],
            }
        )
    firewalls.extend(
        [
            {
                "name": _short_resource_name("shifter-r", range_id, "egress-internal"),
                "direction": "EGRESS",
                "priority": 1000,
                "target_tags": [range_tag],
                "destination_ranges": subnet_cidrs,
                "allowed": [{"IPProtocol": "all"}],
            },
            {
                "name": _short_resource_name("shifter-r", range_id, "egress-deny"),
                "direction": "EGRESS",
                "priority": 65534,
                "target_tags": [range_tag],
                "destination_ranges": ["0.0.0.0/0"],
                "denied": [{"IPProtocol": "all"}],
            },
        ]
    )
    if config.egress_allow_cidrs:
        firewalls.append(
            {
                "name": _short_resource_name("shifter-r", range_id, "egress-allow"),
                "direction": "EGRESS",
                "priority": 1100,
                "target_tags": [range_tag],
                "destination_ranges": list(config.egress_allow_cidrs),
                "allowed": [{"IPProtocol": "all"}],
            }
        )
    if config.private_google_access:
        # Couple Private Google Access with its egress hole automatically: with
        # PGA the range VPC resolves *.googleapis.com to the private VIP and
        # routes it internally, but the per-range egress-deny still blocks it
        # without this allow. Guests reach Vertex AI (a14-kali agent), Cloud
        # Storage (smoketest tarball), and Secret Manager (per-range Vertex key)
        # over HTTPS to the VIP only, staying off the general internet.
        firewalls.append(
            {
                "name": _short_resource_name("shifter-r", range_id, "egress-googleapis"),
                "direction": "EGRESS",
                "priority": 1100,
                "target_tags": [range_tag],
                "destination_ranges": [_GOOGLE_PRIVATE_API_VIP_CIDR],
                "allowed": [{"IPProtocol": "tcp", "ports": ["443"]}],
            }
        )
    return firewalls


def render_range_cell_plan(
    request_uuid: str,
    variables: ResourceDict,
    config: GCERangeCellConfig | None = None,
    *,
    require_images: bool = True,
) -> RangeCellPlan:
    """Render the deterministic GCE resources for one range cell."""
    resolved_config = config or load_gce_range_cell_config()
    range_id = int(str(variables["range_id"]))
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
        variables=variables,
        config=resolved_config,
        network_name=network_name,
        network_link=network_link,
        require_images=require_images,
    )
    instance_plans = _build_instance_plans(
        variables=variables,
        config=resolved_config,
        subnet_plans=subnet_plans,
        require_images=require_images,
    )
    return {
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
        "firewalls": _firewall_plan(range_id, subnet_plans, resolved_config),
    }
