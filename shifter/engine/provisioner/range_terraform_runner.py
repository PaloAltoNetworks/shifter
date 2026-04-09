"""Terraform runner for range infrastructure operations.

Thin wrapper around terraform_base that provides range-specific function names,
provider-routed module selection, and provider-aware state key prefixes.
"""

import os
from pathlib import Path
from typing import Any

import terraform_base

AWS_RANGE_MODULE_PATH = Path(__file__).parent / "terraform" / "modules" / "range"
LEGACY_GCP_RANGE_MODULE_PATH = Path(__file__).parent / "terraform" / "modules" / "gcp-range"

_LABEL = "Range"
_GCP_RANGE_PLANE_ENV = "GCP_RANGE_PLANE"
_DEFAULT_GCP_RANGE_PLANE = "gdc-vmruntime"
_LEGACY_GCP_RANGE_PLANES = {"legacy-compute-engine", "compute-engine", "legacy-ce"}


def _get_provider() -> str:
    return os.environ.get("CLOUD_PROVIDER", "aws")


def get_gcp_range_plane() -> str:
    """Return the active GCP range-plane implementation selector."""
    return os.environ.get(_GCP_RANGE_PLANE_ENV, _DEFAULT_GCP_RANGE_PLANE).strip().lower()


def get_range_module_path() -> Path:
    """Return the provider-specific range Terraform module path."""
    if _get_provider() != "gcp":
        return AWS_RANGE_MODULE_PATH

    if get_gcp_range_plane() in _LEGACY_GCP_RANGE_PLANES:
        return LEGACY_GCP_RANGE_MODULE_PATH

    raise RuntimeError(
        "Active GCP range provisioning now targets GDC VM Runtime, not the legacy Compute Engine "
        "terraform/modules/gcp-range module. Slice 10/11 must provide the GDC range-plane "
        f"implementation before GCP range provisioning can run. Set {_GCP_RANGE_PLANE_ENV}=legacy-compute-engine "
        "only if you intentionally need the retired path for migration/debug work."
    )


def get_range_state_key_prefix() -> str:
    """Return the provider-specific Terraform state key prefix."""
    if _get_provider() != "gcp":
        return "ranges"

    if get_gcp_range_plane() in _LEGACY_GCP_RANGE_PLANES:
        return "gcp/legacy-ce-ranges"

    return "gcp/gdc-ranges"


def has_terraform_state(request_uuid: str) -> bool:
    """Check if Terraform state exists for the given Range request."""
    return terraform_base.has_terraform_state(get_range_state_key_prefix(), request_uuid)


def init_range_workspace(request_uuid: str, working_dir: Path) -> None:
    """Initialize Terraform workspace for Range."""
    terraform_base.init_workspace(get_range_state_key_prefix(), request_uuid, working_dir, _LABEL)


def apply_range(
    request_uuid: str,
    variables: dict[str, Any],
    working_dir: Path,
) -> dict[str, Any]:
    """Run terraform apply for Range and return outputs."""
    return terraform_base.apply(get_range_state_key_prefix(), request_uuid, variables, working_dir, _LABEL)


def destroy_range(
    request_uuid: str,
    working_dir: Path,
    variables: dict[str, Any] | None = None,
) -> None:
    """Run terraform destroy for Range."""
    terraform_base.destroy(get_range_state_key_prefix(), request_uuid, working_dir, _LABEL, variables=variables)


def cleanup_range_state(request_uuid: str) -> None:
    """Delete range Terraform state after destroy."""
    terraform_base.cleanup_state(get_range_state_key_prefix(), request_uuid, _LABEL)
