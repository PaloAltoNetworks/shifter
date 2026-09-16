"""Admission checks for broker egress in GCE range-cell plans."""

from __future__ import annotations

import ipaddress

from shared.model_access.network import broker_egress_destination

from config import GCERangeCellConfig
from gcp_range_cell_types import GceEgressPolicy, InstancePlan, OpenVpnGatewayPlan, SubnetPlan


def admitted_broker_destination(
    policy: GceEgressPolicy,
    config: GCERangeCellConfig,
    subnet_plans: list[SubnetPlan],
    instances: list[InstancePlan],
    vpn_gateway: OpenVpnGatewayPlan | None,
    bypass: bool,
) -> str | None:
    """Validate the exact endpoint and every client bypass before rendering."""
    if policy.model_broker is None:
        return None
    destination = broker_egress_destination(
        policy.model_broker,
        expected_vip=config.model_broker_vip,
        egress_mode=policy.mode,
    )
    unsafe_clients = any(
        any(instance.get(key) for key in ("can_ip_forward", "attach_service_account", "service_account_email"))
        for instance in instances
    )
    if any((bypass, config.private_google_access, unsafe_clients, vpn_gateway is not None)):
        raise RuntimeError("model broker clients require source-preserving keyless isolated egress")
    if any(ipaddress.ip_network(destination).overlaps(ipaddress.ip_network(subnet["cidr"])) for subnet in subnet_plans):
        raise RuntimeError("model broker VIP must not overlap an intra-range egress destination")
    return destination
