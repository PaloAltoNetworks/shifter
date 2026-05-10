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
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloud import get_object_storage

logger = logging.getLogger(__name__)

_AWS_BACKEND = "s3"
_GCP_BACKEND = "gcs"
_AWS_STATE_FILENAME = "terraform.tfstate"
_GCP_STATE_FILENAME = "default.tfstate"
_TF_INPUT_FALSE = "-input=false"
_SUPPORTED_BACKEND_URL_SCHEMES = {
    "s3://": _AWS_BACKEND,
    "gs://": _GCP_BACKEND,
}

# Default writable workspace path used when TERRAFORM_WORKSPACE_DIR is not set.
# In production the Dockerfile sets TERRAFORM_WORKSPACE_DIR explicitly to
# /var/run/provisioner/workspace and the runtime mounts an emptyDir / Fargate
# ephemeral volume there. Outside the container (local dev, CI, unit tests)
# /var/run is generally not writable for an unprivileged user, so the Python
# default falls back to a per-user temp directory.
_DEFAULT_TERRAFORM_WORKSPACE_DIR = str(Path(tempfile.gettempdir()) / "shifter-provisioner-workspace")

# The Kubernetes / ECS mount-point path. Documented separately from the
# Python default because the container ENV declares this exact path, and it
# is the path the Job/task volume is mounted at. Tests that assert on the
# Dockerfile / k8s contract use this constant.
_CONTAINER_TERRAFORM_WORKSPACE_DIR = "/var/run/provisioner/workspace"

# Filename Terraform writes input variables (incl. secrets) to. Hoisted to a
# constant because it is removed independently from the per-request workspace
# tree as a "secret-removal must not silently fail" safeguard.
_TFVARS_FILENAME = "terraform.tfvars.json"

# Pattern matching valid request_uuid path segments. The value reaches
# `shutil.rmtree(workspace_root / request_uuid)`, so a malformed input
# containing `..` or `/` could escape the workspace root. Internal callers
# always pass real UUIDs, but we enforce the contract locally rather than
# trusting every future caller to preserve a path-safe identifier.
# Allows letters, digits, dot (excluded as leading char), dash, underscore;
# bounded length to keep filesystem ops sane.
_REQUEST_UUID_PATTERN = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$")


# Patterns excluded from the staged workspace copy. These are runtime
# artifacts Terraform produces inside a working directory; if any leaked
# into the image (via `COPY . .` or a leftover from a previous build) they
# must NOT be propagated into every new request workspace, where stale
# state could pin the wrong provider version or break locking.
#
# `.terraform.lock.hcl` is intentionally NOT excluded: it is a trusted
# repo-reviewed lockfile that pins provider checksums. Excluding it
# would force every `terraform init` to dynamically resolve providers
# under the privileged Job's cloud credentials — a supply-chain risk.
# It is treated as source input and propagated into the staged workspace.
_TERRAFORM_RUNTIME_ARTIFACT_PATTERNS = (
    ".terraform",
    "*.tfstate",
    "*.tfstate.backup",
    "*.tflock",
    _TFVARS_FILENAME,
    "crash*.log",
)


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
    # Bucket may end in "-pulumi-state" (legacy) or "-pulumi-state-<account_id>"
    # (post-3.95.6, where the account_id suffix dodged the global S3 namespace
    # collision). The DynamoDB lock table itself isn't globally namespaced and
    # kept its original "<prefix>-pulumi-locks" name in both cases.
    match = re.search(r"-pulumi-state(?:-\d+)?$", bucket)
    if match:
        return bucket[: match.start()] + "-pulumi-locks"

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


def _validate_request_uuid(request_uuid: str) -> None:
    """Reject request_uuid values that would escape the workspace root.

    The value is concatenated into a filesystem path and then handed to
    `shutil.rmtree`. A `..`, `/`, or empty string would let cleanup walk
    outside the workspace tree. Internal callers always pass real UUIDs;
    this validator enforces the contract at the boundary so a future
    careless caller cannot turn this into a path-traversal sink.
    """
    if not isinstance(request_uuid, str) or not _REQUEST_UUID_PATTERN.fullmatch(request_uuid):
        raise ValueError(f"request_uuid must be a path-safe identifier, got {request_uuid!r}")


def _stage_workspace(source_dir: Path, request_uuid: str, label: str) -> Path:
    """Copy the read-only Terraform module source to a writable per-request workspace.

    Terraform writes `.terraform/`, `.terraform.lock.hcl`, and `terraform.tfvars.json`
    next to the module's `*.tf` files. When `/app` is mounted read-only those writes
    fail, so the runtime stages a copy of the module under
    ``${TERRAFORM_WORKSPACE_DIR}/<request_uuid>/`` and runs Terraform from there.
    Each request gets its own staged tree so concurrent provisioner Jobs do not
    collide.

    The per-request directory is created with mode 0o700 so other local users (in
    a multi-tenant CI host or local dev box where the fallback workspace lives
    under ``/tmp``) cannot enumerate or read staged secrets like
    ``terraform.tfvars.json`` while the request is in flight.

    When the source follows the conventional ``…/terraform/modules/<module-name>/``
    layout, the whole ``terraform/`` parent is staged so cross-module relative
    references (e.g. ``source = "../shared"``) resolve in the staged copy. For
    other layouts the leaf module is staged on its own.

    Runtime artifacts that may have leaked into the image
    (``.terraform/``, ``*.tfstate``, ``terraform.tfvars.json``, ``crash*.log``)
    are excluded so they cannot propagate into the new request workspace, where
    they would either pin a stale provider version, leak old secrets, or break
    state-locking. ``.terraform.lock.hcl`` is intentionally preserved as
    trusted source input.

    Any pre-existing staged tree under the request UUID is removed first so the
    "clean per-request workspace" contract holds even when a previous run's
    cleanup failed.
    """
    _validate_request_uuid(request_uuid)
    workspace_root = Path(os.environ.get("TERRAFORM_WORKSPACE_DIR", _DEFAULT_TERRAFORM_WORKSPACE_DIR))
    request_root = workspace_root / request_uuid
    if request_root.exists():
        shutil.rmtree(request_root, ignore_errors=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    ignore = shutil.ignore_patterns(*_TERRAFORM_RUNTIME_ARTIFACT_PATTERNS)

    if source_dir.parent.name == "modules":
        terraform_root = source_dir.parent.parent
        relative = source_dir.relative_to(terraform_root)
        logger.debug("Staging %s Terraform tree: %s -> %s", label, terraform_root, request_root)
        shutil.copytree(terraform_root, request_root, ignore=ignore)
        request_root.chmod(0o700)
        return request_root / relative

    staged = request_root / source_dir.name
    logger.debug("Staging %s Terraform module: %s -> %s", label, source_dir, staged)
    request_root.mkdir(parents=True, exist_ok=True)
    request_root.chmod(0o700)
    shutil.copytree(source_dir, staged, ignore=ignore)
    return staged


def _purge_tfvars(request_root: Path) -> None:
    """Delete every ``terraform.tfvars.json`` under the per-request workspace.

    Called from ``apply()`` / ``destroy()`` finally blocks BEFORE the broader
    workspace cleanup so the secret-bearing file is removed deterministically.
    A failure here MUST surface — silencing it would let a workspace-volume
    permission error leave secrets on disk while the apply/destroy path
    reports success.
    """
    if not request_root.exists():
        return
    for tfvars in request_root.rglob(_TFVARS_FILENAME):
        try:
            tfvars.unlink()
        except OSError as exc:
            raise RuntimeError(f"Failed to remove {tfvars} from staged workspace: {exc}") from exc


def _cleanup_workspace(staged_dir: Path) -> None:
    """Remove the per-request staged Terraform workspace tree.

    Walks up from ``staged_dir`` to the per-request root under
    ``${TERRAFORM_WORKSPACE_DIR}/<request_uuid>/`` and removes the entire tree
    so neither the leaf module nor any sibling-tree files (in the
    parent-staging case) survive.

    This is best-effort *disk hygiene only* — secret-bearing
    ``terraform.tfvars.json`` files MUST already have been removed by
    ``_purge_tfvars`` before this is called. Missing paths are ignored so
    cleanup is safe to call from a ``finally`` block without re-raising;
    rmtree failures are logged but do not raise, so a transient permission
    issue on the workspace volume cannot mask the actual apply/destroy
    outcome.
    """
    workspace_root = Path(os.environ.get("TERRAFORM_WORKSPACE_DIR", _DEFAULT_TERRAFORM_WORKSPACE_DIR))
    try:
        relative_parts = staged_dir.resolve().relative_to(workspace_root.resolve()).parts
    except ValueError:
        relative_parts = ()

    request_root = workspace_root / relative_parts[0] if relative_parts else staged_dir

    if not request_root.exists():
        return
    try:
        shutil.rmtree(request_root, ignore_errors=False)
    except OSError as exc:
        logger.warning("Failed to remove staged workspace %s: %s", request_root, exc)


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


def _build_init_args(state_key_prefix: str, request_uuid: str, label: str) -> list[str]:
    """Build the `terraform init` argument list for the active backend."""
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
        _TF_INPUT_FALSE,
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

    return init_args


def _run_init_in_staged_workspace(
    state_key_prefix: str,
    request_uuid: str,
    staged: Path,
    label: str,
) -> None:
    """Run ``terraform init`` inside an already-staged workspace.

    Internal helper for ``apply()`` / ``destroy()``. There is intentionally no
    public ``init_workspace`` entrypoint: the staged workspace is per-call and
    must be torn down before the call returns, so initialization on its own has
    no usable post-condition for an external caller.
    """
    init_args = _build_init_args(state_key_prefix, request_uuid, label)
    run_terraform(init_args, staged)
    logger.info("%s Terraform workspace initialized successfully", label)


def _write_tfvars(staged: Path, variables: dict[str, Any]) -> Path:
    """Write Terraform input variables to ``terraform.tfvars.json`` under ``staged``.

    The file is created with mode ``0o600`` so other local users on a multi-tenant
    CI host (where the fallback workspace lives under ``/tmp``) cannot read input
    variables that may carry credentials or other secrets while the request is in
    flight. Inside the production container the volume mount is already isolated
    from other containers in the Pod; this protects the local-dev / CI path too.
    """
    tfvars_path = staged / _TFVARS_FILENAME
    fd = os.open(tfvars_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(variables, f, indent=2)
    return tfvars_path


def _finalize_workspace(staged: Path) -> None:
    """Remove secrets first, then best-effort tree cleanup.

    Used by ``apply()`` / ``destroy()`` ``finally`` blocks. Order matters:
    ``_purge_tfvars`` must succeed (it raises on failure) so leftover
    secret material does not survive a failed rmtree.
    """
    workspace_root = Path(os.environ.get("TERRAFORM_WORKSPACE_DIR", _DEFAULT_TERRAFORM_WORKSPACE_DIR))
    try:
        relative_parts = staged.resolve().relative_to(workspace_root.resolve()).parts
    except ValueError:
        relative_parts = ()
    request_root = workspace_root / relative_parts[0] if relative_parts else staged
    _purge_tfvars(request_root)
    _cleanup_workspace(staged)


def apply(
    state_key_prefix: str,
    request_uuid: str,
    variables: dict[str, Any],
    working_dir: Path,
    label: str,
) -> dict[str, Any]:
    """Run terraform apply and return outputs.

    Stages a writable per-request workspace, runs init/apply/output from there, and
    removes the staged tree before returning so `terraform.tfvars.json` (which can
    carry secrets) does not persist on the workspace volume.
    """
    staged = _stage_workspace(working_dir, request_uuid, label)
    try:
        _run_init_in_staged_workspace(state_key_prefix, request_uuid, staged, label)

        tfvars_path = _write_tfvars(staged, variables)

        logger.info("Running terraform apply for %s...", label)
        result = run_terraform(
            [
                "apply",
                "-auto-approve",
                _TF_INPUT_FALSE,
                "-no-color",
                f"-var-file={tfvars_path}",
            ],
            staged,
        )
        logger.info("Terraform apply stdout:\n%s", result.stdout)

        logger.info("Retrieving Terraform outputs...")
        output_result = run_terraform(
            ["output", "-json", "-no-color"],
            staged,
        )

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
        return outputs
    finally:
        _finalize_workspace(staged)


def destroy(
    state_key_prefix: str,
    request_uuid: str,
    working_dir: Path,
    label: str,
    variables: dict[str, Any] | None = None,
) -> None:
    """Run terraform destroy.

    Stages a writable per-request workspace, runs init/destroy from there, and
    removes the staged tree before returning so `terraform.tfvars.json` does not
    persist on the workspace volume.
    """
    staged = _stage_workspace(working_dir, request_uuid, label)
    try:
        _run_init_in_staged_workspace(state_key_prefix, request_uuid, staged, label)

        logger.info("Running terraform destroy for %s...", label)
        destroy_args = [
            "destroy",
            "-auto-approve",
            _TF_INPUT_FALSE,
            "-no-color",
        ]

        if variables:
            tfvars_path = _write_tfvars(staged, variables)
            destroy_args.append(f"-var-file={tfvars_path}")

        result = run_terraform(destroy_args, staged)
        logger.info("Terraform destroy stdout:\n%s", result.stdout)
        logger.info("%s Terraform destroy completed successfully", label)
    finally:
        _finalize_workspace(staged)


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
