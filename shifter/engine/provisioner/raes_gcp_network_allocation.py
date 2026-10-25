"""Generation-fenced subnet allocation for RAES GCE shared-VPC ranges."""

import ipaddress
from dataclasses import dataclass

from components.network import read_range_subnets, reserve_range_subnets
from config import GCERangeCellConfig, load_range_network_config
from raes_gcp_adapter import DEFAULT_NETWORK_ADDRESS
from raes_plan import RaesPlan

_DEFAULT_RANGE_VPC_CIDR = "10.1.0.0/16"  # NOSONAR(S1313)
_DEFAULT_OPEN_PREFIX = 28
_SUPPORTED_PREFIXES = frozenset({24, 28})


class RaesRealizationError(ValueError):
    """A realization failure whose message the provisioner authored."""


@dataclass(frozen=True)
class GceNetworkAllocation:
    """Ordered network-address-to-CIDR projection used by every GCE lifecycle."""

    required: bool
    network_cidrs: tuple[tuple[str, str], ...] = ()

    def require_available(self) -> tuple[tuple[str, str], ...] | None:
        """Return the allocation, failing when this lifecycle needs a missing one."""
        if self.required and not self.network_cidrs:
            raise RaesRealizationError("GCE adapter subnet allocation is unavailable")
        return self.network_cidrs or None


def _shared_vpc_shape(raes_plan: RaesPlan, config: GCERangeCellConfig) -> tuple[tuple[str, ...], int] | None:
    """Return the one atomic reservation shape for a shared-VPC plan."""
    if config.network_mode != "shared-vpc":
        return None

    identities: list[str] = []
    prefixes: set[int] = set()
    for network in raes_plan.networks:
        if not network.cidr:
            raise RaesRealizationError(f"RAES network {network.address!r} has no cidr for shared-VPC allocation")
        try:
            authored = ipaddress.ip_network(network.cidr, strict=True)
        except ValueError as exc:
            raise RaesRealizationError("RAES shared-VPC network must be a canonical IPv4 subnet") from exc
        if not isinstance(authored, ipaddress.IPv4Network):
            raise RaesRealizationError("RAES shared-VPC network must use IPv4")
        if authored.prefixlen not in _SUPPORTED_PREFIXES:
            raise RaesRealizationError("RAES shared-VPC networks must use a supported /24 or /28 prefix")
        identities.append(network.address)
        prefixes.add(authored.prefixlen)

    if any(node.network_selection_open for node in raes_plan.nodes):
        if DEFAULT_NETWORK_ADDRESS in identities:
            raise RaesRealizationError("portable plan collides with the reserved GCE adapter network identity")
        identities.append(DEFAULT_NETWORK_ADDRESS)

    if not identities:
        return None
    if len(prefixes) > 1:
        raise RaesRealizationError("RAES shared-VPC networks must use the same supported prefix")
    return tuple(identities), next(iter(prefixes), _DEFAULT_OPEN_PREFIX)


def _projection(
    identities: tuple[str, ...], reserved: tuple[str, ...], *, prefix_length: int
) -> tuple[tuple[str, str], ...]:
    """Validate and pair one ordered allocation result with its network identities."""
    if len(reserved) != len(identities):
        raise RaesRealizationError("GCE adapter subnet allocation has the wrong shape")
    projected: list[tuple[str, str]] = []
    for identity, cidr in zip(identities, reserved, strict=True):
        try:
            network = ipaddress.ip_network(cidr, strict=True)
        except ValueError as exc:
            raise RaesRealizationError("GCE adapter subnet allocation is invalid") from exc
        if not isinstance(network, ipaddress.IPv4Network) or network.prefixlen != prefix_length:
            raise RaesRealizationError("GCE adapter subnet allocation is invalid")
        projected.append((identity, str(network)))
    return tuple(projected)


def allocated_networks_for_provision(
    request_id: str, operation_id: str, raes_plan: RaesPlan, config: GCERangeCellConfig
) -> GceNetworkAllocation:
    """Reserve every realized shared-VPC network in one atomic allocation batch."""
    shape = _shared_vpc_shape(raes_plan, config)
    if shape is None:
        return GceNetworkAllocation(required=False)
    identities, prefix_length = shape
    range_network = load_range_network_config()
    reserved = reserve_range_subnets(
        operation_id=operation_id,
        request_id=request_id,
        network_id=range_network.network_id,
        network_cidr=range_network.network_cidr or _DEFAULT_RANGE_VPC_CIDR,
        subnets=identities,
        prefix_length=prefix_length,
    )
    return GceNetworkAllocation(
        required=True,
        network_cidrs=_projection(identities, reserved, prefix_length=prefix_length),
    )


def allocated_networks_for_destroy(
    request_id: str, operation_id: str, raes_plan: RaesPlan, config: GCERangeCellConfig
) -> GceNetworkAllocation:
    """Read the complete persisted projection for activation or teardown."""
    shape = _shared_vpc_shape(raes_plan, config)
    if shape is None:
        return GceNetworkAllocation(required=False)
    identities, prefix_length = shape
    reserved = read_range_subnets(operation_id=operation_id, request_id=request_id)
    if not reserved:
        return GceNetworkAllocation(required=True)
    return GceNetworkAllocation(
        required=True,
        network_cidrs=_projection(identities, reserved, prefix_length=prefix_length),
    )
