"""Project admitted model grants onto the administrator's pinned guest targets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.model_access import ContractError
from shared.runtime_plugin_binding import RuntimePluginPin

if TYPE_CHECKING:
    from engine.models import Range
from shared.model_access.guest_binding import ModelGuestBinding


def project_model_guest_bindings(target: Range, pin: RuntimePluginPin | None) -> tuple[ModelGuestBinding, ...]:
    """Bind every admitted workload role to its pinned administrator-selected guest."""
    from engine.models import ModelAllocation

    if pin is None:
        return ()
    if target.provisioner_operation_id is None:
        raise ContractError("allocation.guest_binding_unavailable")
    allocations = ModelAllocation.objects.filter(
        range_id=target.uuid, operation_id=target.provisioner_operation_id, released_at__isnull=True
    ).order_by("workload_role")
    result = []
    for allocation in allocations:
        binding = pin.manifest.model_bindings.get(allocation.workload_role)
        if binding is None:
            raise ContractError("allocation.guest_binding_unavailable")
        result.append(
            ModelGuestBinding(
                allocation_id=allocation.pk,
                workload_role=allocation.workload_role,
                target_address=pin.bindings.targets[binding],
            )
        )
    return tuple(result)
