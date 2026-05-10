"""Terraform runner for NGFW infrastructure operations.

Thin wrapper around terraform_base that provides NGFW-specific
function names and state key prefix.

State path: s3://{bucket}/user_ngfw/{request_uuid}/terraform.tfstate
"""

from pathlib import Path
from typing import Any

import terraform_base

# Path to the NGFW Terraform module
NGFW_MODULE_PATH = Path(__file__).parent / "terraform" / "modules" / "ngfw"

_STATE_KEY_PREFIX = "user_ngfw"
_LABEL = "NGFW"


def has_terraform_state(request_uuid: str) -> bool:
    """Check if Terraform state exists for the given NGFW request."""
    return terraform_base.has_terraform_state(_STATE_KEY_PREFIX, request_uuid)


def apply_ngfw(
    request_uuid: str,
    variables: dict[str, Any],
    working_dir: Path,
) -> dict[str, Any]:
    """Run terraform apply for NGFW and return outputs."""
    return terraform_base.apply(_STATE_KEY_PREFIX, request_uuid, variables, working_dir, _LABEL)


def destroy_ngfw(
    request_uuid: str,
    working_dir: Path,
    variables: dict[str, Any] | None = None,
) -> None:
    """Run terraform destroy for NGFW."""
    terraform_base.destroy(_STATE_KEY_PREFIX, request_uuid, working_dir, _LABEL, variables=variables)


def cleanup_ngfw_state(request_uuid: str) -> None:
    """Delete NGFW Terraform state file from S3 after destroy."""
    terraform_base.cleanup_state(_STATE_KEY_PREFIX, request_uuid, _LABEL)
