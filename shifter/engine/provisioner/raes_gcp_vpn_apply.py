"""Participant OpenVPN steps within an RAES GCE apply (ADR-039-R10, #2030, #2480).

The pool firewall rule is part of the range plan, so it is created and cleaned
up with the rest of the attempt. The profile is minted only after the range is
verified, so a range that fails never publishes one.
"""

from __future__ import annotations

from typing import Any

from raes_gcp_apply_types import RaesGceApplyOptions, RaesGceApplyRuntime
from raes_gcp_vpn_plan import RaesGceVpnAccess

__all__ = ["publish_vpn_access", "vpn_access_plan"]


def vpn_access_plan(options: RaesGceApplyOptions) -> RaesGceVpnAccess | None:
    """Return the pool firewall inputs for a realizing apply, if any."""
    return options.openvpn.plan_access() if options.openvpn is not None else None


def publish_vpn_access(runtime: RaesGceApplyRuntime) -> dict[str, Any]:
    """Mint the generation's profile; return the apply-result fragment."""
    if runtime.openvpn is None:
        return {}
    return {"vpn_access": runtime.openvpn.publish()}
