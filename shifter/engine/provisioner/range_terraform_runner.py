"""Runner for range infrastructure operations.

AWS ranges still use Terraform-backed infrastructure modules. The active GCP
range path is GDC-based and no longer routes through the retired Compute Engine
Terraform module.
"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import gcp_range_cells
import gdc_range_networks
import gdc_scenario_pods
import gdc_vmruntime_assets
import terraform_base
from config import get_gcp_range_backend

AWS_RANGE_MODULE_PATH = Path(__file__).parent / "terraform" / "modules" / "range"

_LABEL = "Range"


def _get_provider() -> str:
    return os.environ.get("CLOUD_PROVIDER", "aws")


def get_range_module_path() -> Path:
    """Return the provider-specific range Terraform module path."""
    if _get_provider() == "gcp":
        raise RuntimeError(
            "Active GCP range provisioning targets a provider-native runner and does not expose a "
            "Terraform module path. Call apply_range()/destroy_range() for the provider-routed path."
        )
    return AWS_RANGE_MODULE_PATH


def _uses_active_gdc_range_plane() -> bool:
    return _get_provider() == "gcp" and get_gcp_range_backend() == "gdc"


def _uses_gce_range_cells() -> bool:
    """Return whether the active provider uses the GCE range-cell backend."""
    return _get_provider() == "gcp" and get_gcp_range_backend() == "gce"


def get_range_state_key_prefix() -> str:
    """Return the provider-specific Terraform state key prefix."""
    if _uses_active_gdc_range_plane():
        return "gcp/gdc-ranges"
    if _uses_gce_range_cells():
        return "gcp/gce-range-cells"
    return "ranges"


def has_terraform_state(request_uuid: str) -> bool:
    """Check if Terraform state exists for the given Range request."""
    if _uses_active_gdc_range_plane() or _uses_gce_range_cells():
        return False
    return terraform_base.has_terraform_state(get_range_state_key_prefix(), request_uuid)


def apply_range(
    request_uuid: str,
    variables: dict[str, Any],
    working_dir: Path | None = None,
    *,
    gce_apply_range_cell: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run terraform apply for Range and return outputs."""
    if _uses_gce_range_cells():
        apply_gce = gce_apply_range_cell or gcp_range_cells.apply_range_cell
        return apply_gce(request_uuid, variables)

    if _uses_active_gdc_range_plane():
        network_output = gdc_range_networks.apply_range_networks(request_uuid, variables)
        vm_output = gdc_vmruntime_assets.apply_range_assets(
            request_uuid,
            variables,
            network_output.get("subnets", {}),
        )
        pod_output = gdc_scenario_pods.apply_range_assets(
            request_uuid,
            variables,
            network_output.get("subnets", {}),
        )
        return {
            "subnets": network_output.get("subnets", {}),
            "instances": [*vm_output, *pod_output],
        }

    if working_dir is None:
        working_dir = get_range_module_path()
    return terraform_base.apply(get_range_state_key_prefix(), request_uuid, variables, working_dir, _LABEL)


def destroy_range(
    request_uuid: str,
    working_dir: Path | None = None,
    variables: dict[str, Any] | None = None,
    *,
    gce_destroy_range_cell: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> None:
    """Run terraform destroy for Range."""
    if _uses_gce_range_cells():
        destroy_gce = gce_destroy_range_cell or gcp_range_cells.destroy_range_cell
        destroy_gce(request_uuid, variables)
        return

    if _uses_active_gdc_range_plane():
        gdc_scenario_pods.destroy_range_assets(request_uuid, variables)
        gdc_vmruntime_assets.destroy_range_assets(request_uuid, variables)
        gdc_range_networks.destroy_range_networks(request_uuid, variables)
        return

    if working_dir is None:
        working_dir = get_range_module_path()
    terraform_base.destroy(get_range_state_key_prefix(), request_uuid, working_dir, _LABEL, variables=variables)


def cleanup_range_state(request_uuid: str) -> None:
    """Delete range Terraform state after destroy."""
    if _uses_active_gdc_range_plane() or _uses_gce_range_cells():
        return
    terraform_base.cleanup_state(get_range_state_key_prefix(), request_uuid, _LABEL)
