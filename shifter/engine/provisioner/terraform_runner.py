"""Terraform runner for NGFW infrastructure operations.

This module provides functions to run Terraform commands for NGFW provisioning,
replacing the equivalent Pulumi subprocess calls. It uses the same S3 backend
and DynamoDB lock table as Pulumi, with a different key prefix.

State path: s3://{bucket}/user_ngfw/{request_uuid}/terraform.tfstate
"""

import contextlib
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import boto3

logger = logging.getLogger(__name__)

# Path to the NGFW Terraform module
NGFW_MODULE_PATH = Path(__file__).parent / "terraform" / "modules" / "ngfw"


def _get_state_bucket() -> str:
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


def _get_locks_table() -> str:
    """Get the DynamoDB table name for state locking.

    Uses TF_LOCKS_TABLE if set, otherwise derives from state bucket name.
    Convention: {name_prefix}-pulumi-state -> {name_prefix}-pulumi-locks

    Returns:
        DynamoDB table name
    """
    if table := os.environ.get("TF_LOCKS_TABLE"):
        return table

    # Derive from bucket name: replace -pulumi-state with -pulumi-locks
    bucket = _get_state_bucket()
    if bucket.endswith("-pulumi-state"):
        return bucket.replace("-pulumi-state", "-pulumi-locks")

    # Fallback: append -locks
    return f"{bucket}-locks"


def _get_state_key(request_uuid: str) -> str:
    """Get the S3 key for Terraform state file.

    Args:
        request_uuid: UUID of the provisioning request

    Returns:
        S3 key path
    """
    return f"user_ngfw/{request_uuid}/terraform.tfstate"


def has_terraform_state(request_uuid: str) -> bool:
    """Check if Terraform state exists for the given request.

    Used to determine if an NGFW was provisioned with Terraform (vs Pulumi).

    Args:
        request_uuid: UUID of the provisioning request

    Returns:
        True if Terraform state file exists in S3, False otherwise
    """
    try:
        bucket = _get_state_bucket()
    except ValueError:
        # No state bucket configured
        return False

    state_key = _get_state_key(request_uuid)
    s3_client = boto3.client("s3")

    try:
        s3_client.head_object(Bucket=bucket, Key=state_key)
        logger.debug("Terraform state exists for request %s", request_uuid)
        return True
    except s3_client.exceptions.ClientError as e:
        if e.response.get("Error", {}).get("Code") == "404":
            logger.debug("No Terraform state for request %s", request_uuid)
            return False
        # Re-raise other errors (permissions, etc.)
        raise


def _run_terraform(
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

    result = subprocess.run(  # noqa: S603
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


def init_ngfw_workspace(request_uuid: str, working_dir: Path) -> None:
    """Initialize Terraform workspace with dynamic backend configuration.

    Runs terraform init with S3 backend configuration passed via -backend-config flags.

    Args:
        request_uuid: UUID of the provisioning request (used for state key)
        working_dir: Directory containing Terraform files

    Raises:
        RuntimeError: If init fails
    """
    bucket = _get_state_bucket()
    locks_table = _get_locks_table()
    state_key = _get_state_key(request_uuid)

    logger.info(
        "Initializing Terraform workspace: bucket=%s key=%s",
        bucket,
        state_key,
    )

    _run_terraform(
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

    logger.info("Terraform workspace initialized successfully")


def apply_ngfw(
    request_uuid: str,
    variables: dict[str, Any],
    working_dir: Path,
) -> dict[str, Any]:
    """Run terraform apply for NGFW and return outputs.

    Args:
        request_uuid: UUID of the provisioning request
        variables: Terraform input variables
        working_dir: Directory containing Terraform files

    Returns:
        Dict of Terraform outputs (matches DB state format):
        - ec2_instance_id
        - management_ip
        - dataplane_ip
        - data_eni_id
        - ssh_key_secret_arn

    Raises:
        RuntimeError: If apply fails
    """
    # Initialize workspace first
    init_ngfw_workspace(request_uuid, working_dir)

    # Write variables to tfvars.json
    tfvars_path = working_dir / "terraform.tfvars.json"
    with open(tfvars_path, "w") as f:
        json.dump(variables, f, indent=2)

    logger.info("Running terraform apply for NGFW...")

    # Run apply
    result = _run_terraform(
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
    output_result = _run_terraform(
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


def destroy_ngfw(
    request_uuid: str,
    working_dir: Path,
    variables: dict[str, Any] | None = None,
) -> None:
    """Run terraform destroy for NGFW.

    Args:
        request_uuid: UUID of the provisioning request
        working_dir: Directory containing Terraform files
        variables: Terraform input variables. Required because Terraform needs
            all declared variables even during destroy.

    Raises:
        RuntimeError: If destroy fails
    """
    # Initialize workspace (needed to connect to state)
    init_ngfw_workspace(request_uuid, working_dir)

    logger.info("Running terraform destroy for NGFW...")

    destroy_args = [
        "destroy",
        "-auto-approve",
        "-input=false",
        "-no-color",
    ]

    tfvars_path = None
    if variables:
        tfvars_path = working_dir / "terraform.tfvars.json"
        with open(tfvars_path, "w") as f:
            json.dump(variables, f, indent=2)
        destroy_args.append(f"-var-file={tfvars_path}")

    try:
        result = _run_terraform(destroy_args, working_dir)
    finally:
        if tfvars_path:
            tfvars_path.unlink(missing_ok=True)

    logger.info("Terraform destroy stdout:\n%s", result.stdout)
    logger.info("Terraform destroy completed successfully")


def cleanup_ngfw_state(request_uuid: str) -> None:
    """Delete Terraform state file from S3 after destroy.

    This removes the state file after resources are destroyed,
    similar to `pulumi stack rm`.

    Args:
        request_uuid: UUID of the provisioning request
    """
    bucket = _get_state_bucket()
    state_key = _get_state_key(request_uuid)

    logger.info("Deleting Terraform state: s3://%s/%s", bucket, state_key)

    s3_client = boto3.client("s3")

    # Delete state file
    try:
        s3_client.delete_object(Bucket=bucket, Key=state_key)
    except Exception as e:
        logger.warning("Failed to delete state file: %s", e)

    # Delete lock file if exists
    lock_key = f"{state_key}.tflock"
    with contextlib.suppress(Exception):
        s3_client.delete_object(Bucket=bucket, Key=lock_key)

    logger.info("Terraform state cleanup completed")
