"""Validate byte-free enrollment against the administrator's immutable guest pin."""

from typing import Any

from shared.model_access.guest_binding import ModelGuestBinding
from shared.runtime_plugin_binding import RuntimePluginPin

from .operation_input_identity import RaesOperationInputError


def _validate_enrollment_targets(
    obj: dict[str, Any],
    plugin: RuntimePluginPin | None,
    bindings: tuple[ModelGuestBinding, ...],
) -> None:
    """Require every enrollment to match its pinned model role and Linux guest."""
    for row in bindings:
        if plugin is None:
            raise ValueError
        name = plugin.manifest.model_bindings[row.workload_role]
        if row.target_address != plugin.bindings.targets[name]:
            raise ValueError
        guest = obj["plan"]["resources"][row.target_address]["payload"]
        if guest["os_family"] != "linux":
            raise ValueError


def _model_enrollments(obj: dict[str, Any], plugin: RuntimePluginPin | None) -> tuple[ModelGuestBinding, ...]:
    """Require unique admitted grants targeting the pinned Linux guests."""
    try:
        rows = obj.get("model_enrollments", [])
        if not isinstance(rows, list) or len(rows) > 16:
            raise ValueError
        bindings = tuple(ModelGuestBinding.model_validate(row) for row in rows)
        if len({row.allocation_id for row in bindings}) != len(bindings):
            raise ValueError
        if len({row.workload_role for row in bindings}) != len(bindings):
            raise ValueError
        _validate_enrollment_targets(obj, plugin, bindings)
        return bindings
    except (ValueError, KeyError, TypeError):
        raise RaesOperationInputError("raes model enrollment binding is invalid") from None
