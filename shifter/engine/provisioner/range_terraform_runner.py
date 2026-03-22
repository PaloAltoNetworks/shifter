"""Terraform runner for Range infrastructure operations.

Thin wrapper around terraform_base that provides Range-specific
function names and state key prefix.

State path: s3://{bucket}/ranges/{request_uuid}/terraform.tfstate
"""

from pathlib import Path
from typing import Any

import terraform_base

# Path to the Range Terraform module
RANGE_MODULE_PATH = Path(__file__).parent / "terraform" / "modules" / "range"

_STATE_KEY_PREFIX = "ranges"
_LABEL = "Range"


def has_terraform_state(request_uuid: str) -> bool:
    """Check if Terraform state exists for the given Range request."""
    return terraform_base.has_terraform_state(_STATE_KEY_PREFIX, request_uuid)


def init_range_workspace(request_uuid: str, working_dir: Path) -> None:
    """Initialize Terraform workspace for Range."""
    terraform_base.init_workspace(_STATE_KEY_PREFIX, request_uuid, working_dir, _LABEL)


def apply_range(
    request_uuid: str,
    variables: dict[str, Any],
    working_dir: Path,
) -> dict[str, Any]:
    """Run terraform apply for Range and return outputs."""
    return terraform_base.apply(_STATE_KEY_PREFIX, request_uuid, variables, working_dir, _LABEL)


def destroy_range(
    request_uuid: str,
    working_dir: Path,
    variables: dict[str, Any] | None = None,
) -> None:
    """Run terraform destroy for Range."""
    terraform_base.destroy(_STATE_KEY_PREFIX, request_uuid, working_dir, _LABEL, variables=variables)


def cleanup_range_state(request_uuid: str) -> None:
    """Delete Range Terraform state file from S3 after destroy."""
    terraform_base.cleanup_state(_STATE_KEY_PREFIX, request_uuid, _LABEL)
