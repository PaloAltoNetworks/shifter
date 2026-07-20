"""Terraform backend type, bucket, and state-key resolution.

Resolves the Terraform backend (S3 for AWS, GCS for GCP), the state bucket,
the DynamoDB locks table (AWS only), and the backend object key for a
Terraform operation, and checks whether state already exists for a request.
"""

import logging
import os
import re
from dataclasses import dataclass

from cloud.exceptions import CloudProviderNotImplementedError

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
    """Resolve the active cloud provider name (late-bound for test patchability)."""
    # Late-bound call to ``terraform_base.resolve_cloud_provider`` so a test
    # patch applied at the package level (``monkeypatch.setattr(terraform_base,
    # "resolve_cloud_provider", ...)``) takes effect here.
    import terraform_base as _tb

    return _tb.resolve_cloud_provider()


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

    provider = _get_provider()
    if provider == "gcp":
        return _GCP_BACKEND
    if provider == "aws":
        return _AWS_BACKEND
    raise CloudProviderNotImplementedError(provider)


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
    # Bucket may end in "-pulumi-state" (legacy) or "-pulumi-state-<account_id>"
    # (post-3.95.6, where the account_id suffix dodged the global S3 namespace
    # collision). The DynamoDB lock table itself isn't globally namespaced and
    # kept its original "<prefix>-pulumi-locks" name in both cases.
    match = re.search(r"-pulumi-state(?:-\d+)?$", bucket)
    return (bucket[: match.start()] + "-pulumi-locks") if match else f"{bucket}-locks"


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

    # Late-bound call to ``terraform_base.get_object_storage`` so a test patch
    # applied at the package level (``@patch("terraform_base.get_object_storage")``)
    # takes effect here.
    import terraform_base as _tb

    storage = _tb.get_object_storage()
    result = storage.object_exists(bucket=backend.bucket, key=backend.state_object_key)
    logger.debug("Terraform state %s for request %s", "exists" if result else "not found", request_uuid)
    return result
