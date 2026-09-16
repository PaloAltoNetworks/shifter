"""GCE adapter allocation for portable network intent left open by RAE."""

from dataclasses import dataclass
from typing import Any

from config import GCERangeCellConfig
from raes_gcp_adapter import requires_allocated_gce_network
from raes_plan import RaesPlan
from range_subnet_allocation import _realized_range_spec_for_destroy, _reserve_range_subnet_cidrs

_OPEN_NETWORK_SPEC = {
    "subnets": [{"uuid": "backend.gce.network.default", "name": "backend-default"}],
}


class RaesRealizationError(ValueError):
    """A realization failure whose message the provisioner authored."""


@dataclass(frozen=True)
class GceNetworkAllocation:
    """The closed shared-VPC allocation state used by every GCE lifecycle."""

    required: bool
    cidr: str | None = None

    def require_available(self) -> str | None:
        """Return the allocation, failing when this lifecycle needs a missing one."""
        if self.required and self.cidr is None:
            raise RaesRealizationError("GCE adapter subnet allocation is unavailable")
        return self.cidr


def _allocated_cidr(realized: dict[str, Any]) -> str:
    """Handle allocated cidr."""
    subnets = realized.get("subnets")
    if not isinstance(subnets, list) or len(subnets) != 1:
        raise RaesRealizationError("GCE adapter subnet allocation is invalid")
    cidr = subnets[0].get("cidr") if isinstance(subnets[0], dict) else None
    if not isinstance(cidr, str) or not cidr:
        raise RaesRealizationError("GCE adapter subnet allocation is unavailable")
    return cidr


def allocated_open_network_for_provision(
    request_id: str, operation_id: str, raes_plan: RaesPlan, config: GCERangeCellConfig
) -> GceNetworkAllocation:
    """Reserve a shared-VPC subnet for network intent left open by RAE."""
    if not requires_allocated_gce_network(raes_plan, config):
        return GceNetworkAllocation(required=False)
    realized = _reserve_range_subnet_cidrs(request_id, _OPEN_NETWORK_SPEC, operation_id=operation_id)
    return GceNetworkAllocation(required=True, cidr=_allocated_cidr(realized))


def allocated_open_network_for_destroy(
    request_id: str, operation_id: str, raes_plan: RaesPlan, config: GCERangeCellConfig
) -> GceNetworkAllocation:
    """Read the adapter's reserved subnet for reconstructive teardown."""
    if not requires_allocated_gce_network(raes_plan, config):
        return GceNetworkAllocation(required=False)
    realized = _realized_range_spec_for_destroy(request_id, _OPEN_NETWORK_SPEC, operation_id=operation_id)
    try:
        cidr = _allocated_cidr(realized)
    except RaesRealizationError:
        cidr = None
    return GceNetworkAllocation(required=True, cidr=cidr)
