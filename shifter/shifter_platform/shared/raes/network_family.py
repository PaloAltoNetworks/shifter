"""IPv4-only network address-family admission for the RAES provisioning backend (#1568).

The GCE range-cell substrate is IPv4-only across planning, addressing, firewall
posture, and outputs. The provisioner manifest publishes a
``network-address-family = ipv4-only`` constraint, and this module classifies a
compiled RAES ``network`` resource's CIDR against it so
:mod:`shared.raes.runtime_target` can reject a non-IPv4 network as an unsupported
*capability* (not malformed SDL) on the shared ``validate()`` / ``apply()`` path,
before dispatch or engine persistence. The diagnostic names only the supported
family and never echoes the authored CIDR. A missing or unparseable CIDR is left
to the SDL/transport/plan validators, so this gate does not mislabel malformed
input as an address-family rejection.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Mapping

from raes_backend_protocols.capabilities import ProvisionerCapabilities
from raes_contracts.diagnostics import Diagnostic
from raes_contracts.planning import PlannedResource

#: Provisioner ``constraints`` key that publishes the supported network address
#: family, and its only supported value. Kept in lockstep with
#: ``shared.raes.manifest.SHIFTER_PROVISIONER_CAPABILITIES.constraints``.
NETWORK_ADDRESS_FAMILY_CONSTRAINT = "network-address-family"
IPV4_ONLY_ADDRESS_FAMILY = "ipv4-only"
UNSUPPORTED_NETWORK_ADDRESS_FAMILY_CODE = "shifter-provisioner.unsupported-network-address-family"


def _network_cidr(payload: Mapping[str, object]) -> str:
    """Return the network's authored CIDR (``spec.infrastructure.properties.cidr``), or empty."""
    spec = payload.get("spec")
    infrastructure = spec.get("infrastructure") if isinstance(spec, Mapping) else None
    properties = infrastructure.get("properties") if isinstance(infrastructure, Mapping) else None
    if isinstance(properties, Mapping):
        cidr = properties.get("cidr")
        if isinstance(cidr, str) and cidr.strip():
            return cidr.strip()
    return ""


def _is_non_ipv4(cidr: str) -> bool:
    """True only when ``cidr`` parses to a non-IPv4 network; malformed CIDRs defer (False)."""
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
    return not isinstance(network, ipaddress.IPv4Network)


def network_address_family_diagnostics(
    resource: PlannedResource,
    payload: Mapping[str, object],
    capabilities: ProvisionerCapabilities,
    diagnostic_factory: Callable[[str, str, str], Diagnostic],
) -> list[Diagnostic]:
    """Return the unsupported-address-family diagnostic for a non-IPv4 network, else none.

    Enforced only when the backend publishes the ``ipv4-only`` constraint. Uses the
    caller's ``diagnostic_factory`` so the diagnostic stays bounded/single-line and
    the authored CIDR is never disclosed.
    """
    if capabilities.constraints.get(NETWORK_ADDRESS_FAMILY_CONSTRAINT) != IPV4_ONLY_ADDRESS_FAMILY:
        return []
    cidr = _network_cidr(payload)
    if cidr and _is_non_ipv4(cidr):
        return [
            diagnostic_factory(
                UNSUPPORTED_NETWORK_ADDRESS_FAMILY_CODE,
                resource.address,
                "unsupported network address family; this provisioning-only backend supports only ipv4 networks",
            )
        ]
    return []
