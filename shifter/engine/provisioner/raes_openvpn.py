"""Participant OpenVPN access on the RAES GCE range-cell path (ADR-039-R10, #2030, #2480).

The tenant's shared OpenVPN server pool carries every participant tunnel. For a
range that holds an OpenVPN capability, the provisioner does two things:

* plans one ingress rule that lets the pool reach the authorized target node on
  its declared participant channels (``raes_gcp_vpn_plan``); and
* after the range is verified, mints the generation's client profile against the
  tenant CA and returns the owner-free realization in the READY result.

The capability comes from the immutable operation input (ADR-043), never from
``mission_control_range``. The profile is keyed on the range's ``request_id`` --
the generation the Engine validates delivery and connections against -- for a
cold provision and a warm activation alike.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from dataclasses import dataclass

from shared.raes.operation_input import RaesRemoteAccess

from raes_gcp_network_allocation import RaesRealizationError
from raes_gcp_vpn_plan import RaesGceVpnAccess
from raes_plan import RaesPlan
from vpn_access import OpenVpnPoolEndpoint, cleanup_openvpn_access, mint_openvpn_profile, openvpn_pool_endpoint
from vpn_secrets import GCPVpnSecretOps, openvpn_access_enabled

logger = logging.getLogger(__name__)

__all__ = [
    "RaesOpenVpn",
    "cleanup_failed_provision_openvpn",
    "cleanup_raes_openvpn",
    "prepare_raes_openvpn",
    "vpn_access_fragment",
    "vpn_access_names",
]


def _pool_cidrs() -> tuple[str, ...]:
    """Return the pool's private source networks, rejecting anything broader."""
    cidrs: list[str] = []
    for value in os.environ.get("RANGE_OPENVPN_POOL_CIDRS", "").split(","):
        if not value.strip():
            continue
        network = ipaddress.ip_network(value.strip(), strict=True)
        if network.version != 4 or not network.is_private or network.prefixlen < 16:
            raise RaesRealizationError("RANGE_OPENVPN_POOL_CIDRS must list private IPv4 networks of /16 or smaller")
        cidrs.append(str(network))
    return tuple(cidrs)


@dataclass(frozen=True)
class RaesOpenVpn:
    """One generation's OpenVPN access for a GCE apply or activation."""

    request_id: str
    range_id: int
    remote_access: RaesRemoteAccess
    member_refs: tuple[str, ...]
    endpoint: OpenVpnPoolEndpoint
    pool_cidrs: tuple[str, ...]

    def plan_access(self) -> RaesGceVpnAccess:
        """Return the pool firewall inputs for this range."""
        return RaesGceVpnAccess(target_ref=self.remote_access.target_ref, pool_cidrs=self.pool_cidrs)

    def publish(self) -> dict[str, object]:
        """Mint and store the generation's profile; return the owner-free realization."""
        return mint_openvpn_profile(
            self.request_id,
            self.range_id,
            self.member_refs,
            self.remote_access.capability,
            GCPVpnSecretOps(),
            self.endpoint,
        )


def vpn_access_names(remote_access: RaesRemoteAccess | None) -> RaesGceVpnAccess | None:
    """Return the pool firewall inputs destroy and inventory need: the rule name only."""
    if remote_access is None:
        return None
    return RaesGceVpnAccess(target_ref=remote_access.target_ref)


def _member_refs(raes_plan: RaesPlan) -> tuple[str, ...]:
    """Return every realized member key the plan declares (``<node address>#<index>``)."""
    return tuple(f"{node.address}#{index}" for node in raes_plan.nodes for index in range(node.count))


def prepare_raes_openvpn(
    request_id: str,
    range_id: int,
    raes_plan: RaesPlan,
    remote_access: RaesRemoteAccess | None,
) -> RaesOpenVpn | None:
    """Check the installation can serve the authorized access, before any provider mutation."""
    if remote_access is None:
        return None
    endpoint = openvpn_pool_endpoint()
    if not openvpn_access_enabled() or endpoint is None:
        raise RaesRealizationError("This range requests OpenVPN access, but no shared OpenVPN pool is deployed")
    member_refs = _member_refs(raes_plan)
    if member_refs.count(remote_access.target_ref) != 1:
        raise RaesRealizationError("OpenVPN capability must identify exactly one range member")
    pool_cidrs = _pool_cidrs()
    if not pool_cidrs:
        # An ingress rule without a source would admit every address.
        raise RaesRealizationError("The shared OpenVPN pool has no source networks configured")
    return RaesOpenVpn(
        request_id=request_id,
        range_id=range_id,
        remote_access=remote_access,
        member_refs=member_refs,
        endpoint=endpoint,
        pool_cidrs=pool_cidrs,
    )


def cleanup_raes_openvpn(request_id: str, range_id: int, remote_access: RaesRemoteAccess | None) -> None:
    """Delete the generation's participant profile (idempotent)."""
    if remote_access is None:
        return
    cleanup_openvpn_access(range_id, request_id, GCPVpnSecretOps())


def cleanup_failed_provision_openvpn(request_id: str, range_id: int, remote_access: RaesRemoteAccess | None) -> None:
    """Delete a failed provision's profile without masking the provision's failure."""
    try:
        cleanup_raes_openvpn(request_id, range_id, remote_access)
    except Exception:
        logger.exception("RAES OpenVPN profile cleanup failed for request_id=%s", request_id)


def vpn_access_fragment(vpn_access: object) -> dict[str, object]:
    """Return the terminal-result ``vpn_access`` fragment when a realization exists."""
    return {"vpn_access": vpn_access} if vpn_access is not None else {}
