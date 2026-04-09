"""Terraform runner for range infrastructure operations.

Thin wrapper around terraform_base that provides range-specific function names,
provider-routed module selection, and provider-aware state key prefixes.
"""

import os
from pathlib import Path
from typing import Any

import terraform_base

AWS_RANGE_MODULE_PATH = Path(__file__).parent / "terraform" / "modules" / "range"
GCP_RANGE_MODULE_PATH = Path(__file__).parent / "terraform" / "modules" / "gcp-range"

_LABEL = "Range"


def _get_provider() -> str:
    return os.environ.get("CLOUD_PROVIDER", "aws")


def get_range_module_path() -> Path:
    """Return the provider-specific range Terraform module path."""
    return GCP_RANGE_MODULE_PATH if _get_provider() == "gcp" else AWS_RANGE_MODULE_PATH


def get_range_state_key_prefix() -> str:
    """Return the provider-specific Terraform state key prefix."""
    return "gcp/ranges" if _get_provider() == "gcp" else "ranges"


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
