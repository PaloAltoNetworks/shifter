"""Runner for range infrastructure operations.

AWS ranges still use Terraform-backed infrastructure modules. The active GCP
range path is GDC-based and no longer routes through the retired Compute Engine
Terraform module.
"""

import os
from pathlib import Path
from typing import Any

import gdc_range_networks
import terraform_base

AWS_RANGE_MODULE_PATH = Path(__file__).parent / "terraform" / "modules" / "range"

_LABEL = "Range"


def _get_provider() -> str:
    return os.environ.get("CLOUD_PROVIDER", "aws")


def get_range_module_path() -> Path:
    """Return the provider-specific range Terraform module path."""
    if _get_provider() == "gcp":
        raise RuntimeError(
            "Active GCP range provisioning now targets the GDC VM Runtime runner and does not expose a "
            "Terraform module path. Call apply_range()/destroy_range() for the provider-routed path."
        )
    return AWS_RANGE_MODULE_PATH


def _uses_active_gdc_range_plane() -> bool:
    return _get_provider() == "gcp"


def get_range_state_key_prefix() -> str:
    """Return the provider-specific Terraform state key prefix."""
    return "gcp/gdc-ranges" if _get_provider() == "gcp" else "ranges"


def has_terraform_state(request_uuid: str) -> bool:
    """Check if Terraform state exists for the given Range request."""
    if _uses_active_gdc_range_plane():
        return False
    return terraform_base.has_terraform_state(get_range_state_key_prefix(), request_uuid)


def init_range_workspace(request_uuid: str, working_dir: Path) -> None:
    """Initialize Terraform workspace for Range."""
    if _uses_active_gdc_range_plane():
        return
    terraform_base.init_workspace(get_range_state_key_prefix(), request_uuid, working_dir, _LABEL)


def apply_range(
    request_uuid: str,
    variables: dict[str, Any],
    working_dir: Path | None = None,
) -> dict[str, Any]:
    """Run terraform apply for Range and return outputs."""
    if _uses_active_gdc_range_plane():
        return gdc_range_networks.apply_range_networks(request_uuid, variables)

    if working_dir is None:
        working_dir = get_range_module_path()
    return terraform_base.apply(get_range_state_key_prefix(), request_uuid, variables, working_dir, _LABEL)


def destroy_range(
    request_uuid: str,
    working_dir: Path | None = None,
    variables: dict[str, Any] | None = None,
) -> None:
    """Run terraform destroy for Range."""
    if _uses_active_gdc_range_plane():
        gdc_range_networks.destroy_range_networks(request_uuid, variables)
        return

    if working_dir is None:
        working_dir = get_range_module_path()
    terraform_base.destroy(get_range_state_key_prefix(), request_uuid, working_dir, _LABEL, variables=variables)


def cleanup_range_state(request_uuid: str) -> None:
    """Delete range Terraform state after destroy."""
    if _uses_active_gdc_range_plane():
        return
    terraform_base.cleanup_state(get_range_state_key_prefix(), request_uuid, _LABEL)
