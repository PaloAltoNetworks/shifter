"""Admit the shared OpenVPN pool to an RAES range's participant target (ADR-039-R10, #2480).

The pool servers live in the shared range VPC. A range that holds an OpenVPN
capability gets one ingress rule: the pool's source networks may reach the
target node, and only on that node's declared participant channels. No other
range host admits the pool, so a domain controller or a second guest is
unreachable from the pool at the cloud layer whatever the servers do.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcp_range_cell_firewall import PARTICIPANT_CHANNEL_PORTS
from gcp_range_cell_naming import _short_resource_name
from gcp_range_cell_types import FirewallPlan, InstancePlan
from raes_gcp_firewall import node_tag
from raes_gcp_plan_errors import RaesGcePlanError

__all__ = ["RaesGceVpnAccess", "vpn_pool_firewall_name", "vpn_pool_firewalls"]

_VPN_POOL_PRIORITY = 900


@dataclass(frozen=True)
class RaesGceVpnAccess:
    """The range's OpenVPN target member and the pool's source networks.

    Destroy and inventory reconstruct the rule name only and leave
    ``pool_cidrs`` empty; such a plan is never used to create the rule.
    """

    target_ref: str
    pool_cidrs: tuple[str, ...] = ()

    def names_only(self) -> RaesGceVpnAccess:
        """Return the input teardown needs: the rule name, never a creatable rule."""
        return RaesGceVpnAccess(target_ref=self.target_ref)


def vpn_pool_firewall_name(range_id: int) -> str:
    """Return the deterministic name of the range's pool ingress rule."""
    return _short_resource_name("shifter-r", range_id, "vpn-pool")


def vpn_pool_firewalls(
    range_id: int,
    instance_plans: list[InstancePlan],
    access: RaesGceVpnAccess | None,
) -> list[FirewallPlan]:
    """Return the pool ingress rule for the authorized target, or nothing without one."""
    if access is None:
        return []
    realizing = bool(access.pool_cidrs)
    target = next((instance for instance in instance_plans if instance["uuid"] == access.target_ref), None)
    channels = target.get("participant_access_channels", []) if target is not None else []
    ports = sorted({PARTICIPANT_CHANNEL_PORTS[channel] for channel in channels}, key=int)
    if realizing and (target is None or not ports):
        raise RaesGcePlanError("the OpenVPN target declares no participant channel the pool can reach")
    return [
        {
            "name": vpn_pool_firewall_name(range_id),
            "direction": "INGRESS",
            "priority": _VPN_POOL_PRIORITY,
            "target_tags": [node_tag(range_id, access.target_ref.rsplit("#", 1)[0])],
            "source_ranges": list(access.pool_cidrs),
            "allowed": [{"IPProtocol": "tcp", "ports": ports or list(PARTICIPANT_CHANNEL_PORTS.values())}],
        }
    ]
