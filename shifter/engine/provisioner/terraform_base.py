"""Shared Terraform runner helpers.

Provides common functions used by both terraform_runner.py (NGFW) and
range_terraform_runner.py (Range). Each caller passes a state key prefix
and label to distinguish its state path and log messages.

Backends:
- AWS uses the S3 backend with object keys like
  ``{prefix}/{request_uuid}/terraform.tfstate`` and DynamoDB locking.
- GCP uses the GCS backend with object keys like
  ``{prefix}/{request_uuid}/default.tfstate`` and no external lock table.
"""

import contextlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloud import get_object_storage

logger = logging.getLogger(__name__)

_AWS_BACKEND = "s3"
_GCP_BACKEND = "gcs"
_AWS_STATE_FILENAME = "terraform.tfstate"
_GCP_STATE_FILENAME = "default.tfstate"
_SUPPORTED_BACKEND_URL_SCHEMES = {
    "s3://": _AWS_BACKEND,
    "gs://": _GCP_BACKEND,
}


@dataclass(frozen=True)
class TerraformBackendConfig:
    """Resolved backend configuration for the active cloud provider."""

    backend_type: str
    bucket: str
    backend_path: str
    state_object_key: str


def _get_provider() -> str:
    return os.environ.get("CLOUD_PROVIDER", "aws")


def _parse_backend_url(bucket_url: str) -> tuple[str, str]:
    """Parse a Terraform backend URL into backend type and bucket name."""
    normalized_url = bucket_url.strip()
    for prefix, backend_type in _SUPPORTED_BACKEND_URL_SCHEMES.items():
        if normalized_url.startswith(prefix):
            bucket = normalized_url[len(prefix) :].strip("/")
            if not bucket:
                raise ValueError(f"Invalid Terraform backend URL: {bucket_url}")
            return backend_type, bucket
    raise ValueError(f"Unsupported Terraform backend URL: {bucket_url}")


def get_backend_type() -> str:
    """Resolve the Terraform backend type for the active provider."""
    bucket_url = os.environ.get("STATE_BUCKET_URL") or os.environ.get("PULUMI_BACKEND_URL", "")
    if bucket_url:
        backend_type, _ = _parse_backend_url(bucket_url)
        return backend_type

    return _GCP_BACKEND if _get_provider() == "gcp" else _AWS_BACKEND


def get_state_bucket() -> str:
    """Get the Terraform state bucket name.

    Uses TF_STATE_BUCKET environment variable. Falls back to STATE_BUCKET_URL
    or legacy PULUMI_BACKEND_URL (s3://bucket-name or gs://bucket-name format) for backward
    compatibility during rollout.

    Returns:
        Backend bucket name

    Raises:
        ValueError: If no state bucket env var is set
    """
    if bucket := os.environ.get("TF_STATE_BUCKET"):
        return bucket

    bucket_url = os.environ.get("STATE_BUCKET_URL") or os.environ.get("PULUMI_BACKEND_URL", "")
    if bucket_url:
        _, bucket = _parse_backend_url(bucket_url)
        return bucket

    raise ValueError("TF_STATE_BUCKET, STATE_BUCKET_URL, or PULUMI_BACKEND_URL environment variable is required")


def get_locks_table() -> str | None:
    """Get the DynamoDB table name for S3 backend locking.

    Uses TF_LOCKS_TABLE if set, otherwise derives from the state bucket name.
    Convention: {name_prefix}-pulumi-state -> {name_prefix}-pulumi-locks

    Returns:
        DynamoDB table name for AWS backends, otherwise None
    """
    if get_backend_type() != _AWS_BACKEND:
        return None

    if table := os.environ.get("TF_LOCKS_TABLE"):
        return table

    bucket = get_state_bucket()
    if bucket.endswith("-pulumi-state"):
        return bucket.replace("-pulumi-state", "-pulumi-locks")

    return f"{bucket}-locks"


def get_state_key(
    state_key_prefix: str,
    request_uuid: str,
    *,
    backend_type: str | None = None,
) -> str:
    """Get the object key for the Terraform state file.

    Args:
        state_key_prefix: Prefix for the state key (e.g. "user_ngfw", "ranges")
        request_uuid: UUID of the provisioning request
        backend_type: Optional explicit backend type override

    Returns:
        Backend object key path
    """
    resolved_backend_type = backend_type or get_backend_type()
    state_filename = _GCP_STATE_FILENAME if resolved_backend_type == _GCP_BACKEND else _AWS_STATE_FILENAME
    return f"{state_key_prefix}/{request_uuid}/{state_filename}"


def get_backend_config(state_key_prefix: str, request_uuid: str) -> TerraformBackendConfig:
    """Resolve backend config for a Terraform operation."""
    backend_type = get_backend_type()
    bucket = get_state_bucket()
    backend_path = f"{state_key_prefix}/{request_uuid}"
    return TerraformBackendConfig(
        backend_type=backend_type,
        bucket=bucket,
        backend_path=backend_path,
        state_object_key=get_state_key(
            state_key_prefix,
            request_uuid,
            backend_type=backend_type,
        ),
    )


def has_terraform_state(state_key_prefix: str, request_uuid: str) -> bool:
    """Check if Terraform state exists for the given request.

    Args:
        state_key_prefix: Prefix for the state key
        request_uuid: UUID of the provisioning request

    Returns:
        True if Terraform state file exists, False otherwise
    """
    try:
        backend = get_backend_config(state_key_prefix, request_uuid)
    except ValueError:
        return False

    storage = get_object_storage()
    result = storage.object_exists(bucket=backend.bucket, key=backend.state_object_key)
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
    backend = get_backend_config(state_key_prefix, request_uuid)

    logger.info(
        "Initializing %s Terraform workspace: backend=%s bucket=%s path=%s",
        label,
        backend.backend_type,
        backend.bucket,
        backend.backend_path,
    )

    init_args = [
        "init",
        "-backend=true",
        f"-backend-config=bucket={backend.bucket}",
        "-input=false",
        "-no-color",
    ]

    if backend.backend_type == _AWS_BACKEND:
        locks_table = get_locks_table()
        init_args.extend(
            [
                f"-backend-config=key={backend.state_object_key}",
                "-backend-config=region=us-east-2",
                f"-backend-config=dynamodb_table={locks_table}",
                "-backend-config=encrypt=true",
            ]
        )
    else:
        init_args.append(f"-backend-config=prefix={backend.backend_path}")

    run_terraform(init_args, working_dir)

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
    """Delete the backend state file after destroy.

    This removes the state file after resources are destroyed,
    similar to `pulumi stack rm`.

    Args:
        state_key_prefix: Prefix for the state key
        request_uuid: UUID of the provisioning request
        label: Label for log messages
    """
    backend = get_backend_config(state_key_prefix, request_uuid)

    logger.info(
        "Deleting %s Terraform state: %s://%s/%s",
        label,
        backend.backend_type,
        backend.bucket,
        backend.state_object_key,
    )

    storage = get_object_storage()

    try:
        storage.delete_object(bucket=backend.bucket, key=backend.state_object_key)
    except Exception as e:
        logger.warning("Failed to delete state file: %s", e)

    if backend.backend_type == _AWS_BACKEND:
        lock_key = f"{backend.state_object_key}.tflock"
        with contextlib.suppress(Exception):
            storage.delete_object(bucket=backend.bucket, key=lock_key)

    logger.info("%s Terraform state cleanup completed", label)
