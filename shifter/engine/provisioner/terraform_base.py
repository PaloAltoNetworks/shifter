"""Shared Terraform runner helpers.

Provides common functions used by both terraform_runner.py (NGFW) and
range_terraform_runner.py (Range). Each caller passes a state_key_prefix
and label to distinguish its state path and log messages.

State path pattern: s3://{bucket}/{state_key_prefix}/{request_uuid}/terraform.tfstate
"""

import contextlib
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from cloud import get_object_storage

logger = logging.getLogger(__name__)


def get_state_bucket() -> str:
    """Get the S3 bucket name for Terraform state.

    Uses PULUMI_BACKEND_URL environment variable and extracts the bucket name.
    Falls back to TF_STATE_BUCKET if set.

    Returns:
        S3 bucket name

    Raises:
        ValueError: If neither env var is set
    """
    # Check for explicit TF_STATE_BUCKET first
    if bucket := os.environ.get("TF_STATE_BUCKET"):
        return bucket

    # Extract from PULUMI_BACKEND_URL (format: s3://bucket-name)
    pulumi_url = os.environ.get("PULUMI_BACKEND_URL", "")
    if pulumi_url.startswith("s3://"):
        return pulumi_url[5:]  # Strip "s3://"

    raise ValueError("TF_STATE_BUCKET or PULUMI_BACKEND_URL environment variable is required")


def get_locks_table() -> str:
    """Get the DynamoDB table name for state locking.

    Uses TF_LOCKS_TABLE if set, otherwise derives from state bucket name.
    Convention: {name_prefix}-pulumi-state -> {name_prefix}-pulumi-locks

    Returns:
        DynamoDB table name
    """
    if table := os.environ.get("TF_LOCKS_TABLE"):
        return table

    # Derive from bucket name: replace -pulumi-state with -pulumi-locks
    bucket = get_state_bucket()
    if bucket.endswith("-pulumi-state"):
        return bucket.replace("-pulumi-state", "-pulumi-locks")

    # Fallback: append -locks
    return f"{bucket}-locks"


def get_state_key(state_key_prefix: str, request_uuid: str) -> str:
    """Get the S3 key for Terraform state file.

    Args:
        state_key_prefix: Prefix for the state key (e.g. "user_ngfw", "ranges")
        request_uuid: UUID of the provisioning request

    Returns:
        S3 key path
    """
    return f"{state_key_prefix}/{request_uuid}/terraform.tfstate"


def has_terraform_state(state_key_prefix: str, request_uuid: str) -> bool:
    """Check if Terraform state exists for the given request.

    Args:
        state_key_prefix: Prefix for the state key
        request_uuid: UUID of the provisioning request

    Returns:
        True if Terraform state file exists in S3, False otherwise
    """
    try:
        bucket = get_state_bucket()
    except ValueError:
        # No state bucket configured
        return False

    state_key = get_state_key(state_key_prefix, request_uuid)
    storage = get_object_storage()
    result = storage.object_exists(bucket=bucket, key=state_key)
    logger.debug("Terraform state %s for request %s", "exists" if result else "not found", request_uuid)
    return result


def run_terraform(
    args: list[str],
    working_dir: Path,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a Terraform command.

    Args:
        args: Terraform command arguments (without 'terraform' prefix)
        working_dir: Directory to run command in
        env: Environment variables (merged with current env)
        capture_output: Whether to capture stdout/stderr

    Returns:
        Completed process result

    Raises:
        RuntimeError: If command fails
    """
    cmd = ["terraform", *args]
    run_env = {**os.environ, **(env or {})}

    logger.debug("Running: %s in %s", " ".join(cmd), working_dir)

    result = subprocess.run(  # noqa: S603  # NOSONAR — hardcoded binary, list args, no shell
        cmd,
        cwd=working_dir,
        env=run_env,
        capture_output=capture_output,
        text=True,
    )

    if result.returncode != 0:
        logger.error("Terraform command failed: %s", result.stderr)
        raise RuntimeError(f"Terraform command failed: {result.stderr}")

    return result


def init_workspace(
    state_key_prefix: str,
    request_uuid: str,
    working_dir: Path,
    label: str,
) -> None:
    """Initialize Terraform workspace with dynamic backend configuration.

    Args:
        state_key_prefix: Prefix for the state key
        request_uuid: UUID of the provisioning request
        working_dir: Directory containing Terraform files
        label: Label for log messages (e.g. "NGFW", "Range")

    Raises:
        RuntimeError: If init fails
    """
    bucket = get_state_bucket()
    locks_table = get_locks_table()
    state_key = get_state_key(state_key_prefix, request_uuid)

    logger.info(
        "Initializing %s Terraform workspace: bucket=%s key=%s",
        label,
        bucket,
        state_key,
    )

    run_terraform(
        [
            "init",
            "-backend=true",
            f"-backend-config=bucket={bucket}",
            f"-backend-config=key={state_key}",
            "-backend-config=region=us-east-2",
            f"-backend-config=dynamodb_table={locks_table}",
            "-backend-config=encrypt=true",
            "-input=false",
            "-no-color",
        ],
        working_dir,
    )

    logger.info("%s Terraform workspace initialized successfully", label)


def apply(
    state_key_prefix: str,
    request_uuid: str,
    variables: dict[str, Any],
    working_dir: Path,
    label: str,
) -> dict[str, Any]:
    """Run terraform apply and return outputs.

    Args:
        state_key_prefix: Prefix for the state key
        request_uuid: UUID of the provisioning request
        variables: Terraform input variables
        working_dir: Directory containing Terraform files
        label: Label for log messages

    Returns:
        Dict of Terraform outputs

    Raises:
        RuntimeError: If apply fails
    """
    # Initialize workspace first
    init_workspace(state_key_prefix, request_uuid, working_dir, label)

    # Write variables to tfvars.json
    tfvars_path = working_dir / "terraform.tfvars.json"
    with open(tfvars_path, "w") as f:
        json.dump(variables, f, indent=2)

    logger.info("Running terraform apply for %s...", label)

    # Run apply
    result = run_terraform(
        [
            "apply",
            "-auto-approve",
            "-input=false",
            "-no-color",
            f"-var-file={tfvars_path}",
        ],
        working_dir,
    )

    logger.info("Terraform apply stdout:\n%s", result.stdout)

    # Get outputs
    logger.info("Retrieving Terraform outputs...")
    output_result = run_terraform(
        ["output", "-json", "-no-color"],
        working_dir,
    )

    # Parse outputs - Terraform wraps each output in {"value": X, "type": T}
    try:
        raw_outputs = json.loads(output_result.stdout)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Terraform output: %s", output_result.stdout[:500])
        raise RuntimeError(f"Failed to parse Terraform output as JSON: {e}") from e

    outputs: dict[str, Any] = {}
    for key, val in raw_outputs.items():
        if not isinstance(val, dict) or "value" not in val:
            logger.warning("Unexpected output format for %s: %s", key, val)
            continue
        outputs[key] = val["value"]

    logger.info("Terraform outputs: %s", json.dumps(outputs, indent=2))

    # Clean up tfvars file (contains sensitive data)
    tfvars_path.unlink(missing_ok=True)

    return outputs


def destroy(
    state_key_prefix: str,
    request_uuid: str,
    working_dir: Path,
    label: str,
    variables: dict[str, Any] | None = None,
) -> None:
    """Run terraform destroy.

    Args:
        state_key_prefix: Prefix for the state key
        request_uuid: UUID of the provisioning request
        working_dir: Directory containing Terraform files
        label: Label for log messages
        variables: Optional Terraform variables dict. Required when the
            module has variables with no defaults.

    Raises:
        RuntimeError: If destroy fails
    """
    # Initialize workspace (needed to connect to state)
    init_workspace(state_key_prefix, request_uuid, working_dir, label)

    logger.info("Running terraform destroy for %s...", label)

    destroy_args = [
        "destroy",
        "-auto-approve",
        "-input=false",
        "-no-color",
    ]

    # Write tfvars if variables provided (needed for modules with required variables)
    tfvars_path = working_dir / "terraform.tfvars.json"
    if variables:
        with open(tfvars_path, "w") as f:
            json.dump(variables, f, indent=2)
        destroy_args.append(f"-var-file={tfvars_path}")

    try:
        result = run_terraform(destroy_args, working_dir)
    finally:
        if variables:
            tfvars_path.unlink(missing_ok=True)

    logger.info("Terraform destroy stdout:\n%s", result.stdout)
    logger.info("%s Terraform destroy completed successfully", label)


def cleanup_state(state_key_prefix: str, request_uuid: str, label: str) -> None:
    """Delete Terraform state file from S3 after destroy.

    This removes the state file after resources are destroyed,
    similar to `pulumi stack rm`.

    Args:
        state_key_prefix: Prefix for the state key
        request_uuid: UUID of the provisioning request
        label: Label for log messages
    """
    bucket = get_state_bucket()
    state_key = get_state_key(state_key_prefix, request_uuid)

    logger.info("Deleting %s Terraform state: s3://%s/%s", label, bucket, state_key)

    storage = get_object_storage()

    # Delete state file
    try:
        storage.delete_object(bucket=bucket, key=state_key)
    except Exception as e:
        logger.warning("Failed to delete state file: %s", e)

    # Delete lock file if exists
    lock_key = f"{state_key}.tflock"
    with contextlib.suppress(Exception):
        storage.delete_object(bucket=bucket, key=lock_key)

    logger.info("%s Terraform state cleanup completed", label)
