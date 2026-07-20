"""Per-request Terraform workspace staging, secret cleanup, and init-arg building.

Terraform writes ``.terraform/``, ``.terraform.lock.hcl``, and
``terraform.tfvars.json`` next to a module's ``*.tf`` files. When ``/app`` is
mounted read-only, ``apply()`` / ``destroy()`` stage a writable copy of the
module under ``${TERRAFORM_WORKSPACE_DIR}/<request_uuid>/`` and run Terraform
from there. This module owns staging that per-request workspace, purging
secrets from it, tearing it down, and building the backend-specific
``terraform init`` argument list.
"""

import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ._backend import _AWS_BACKEND, get_backend_config, get_locks_table

logger = logging.getLogger(__name__)

_TF_INPUT_FALSE = "-input=false"

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


def _request_workspace_root(workspace_root: Path, request_uuid: str) -> Path:
    """Build the per-request workspace path and confirm it stays within the workspace root.

    `request_uuid` is already format-validated by `_validate_request_uuid`, but this
    re-checks the *constructed path* (after `resolve()` collapses any symlink/`..`)
    so the directory we create, copy into, and later rmtree can never escape the
    workspace root.
    """
    base = workspace_root.resolve()
    request_root = (workspace_root / request_uuid).resolve()
    if request_root != base and not request_root.is_relative_to(base):
        raise ValueError(f"request workspace path escapes the workspace root: {request_root}")
    return request_root


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
    # Late-bound read of ``terraform_base._DEFAULT_TERRAFORM_WORKSPACE_DIR`` so a
    # test patch applied at the package level
    # (``monkeypatch.setattr("terraform_base._DEFAULT_TERRAFORM_WORKSPACE_DIR", ...)``)
    # takes effect here.
    import terraform_base as _tb

    workspace_root = Path(os.environ.get("TERRAFORM_WORKSPACE_DIR", _tb._DEFAULT_TERRAFORM_WORKSPACE_DIR))
    request_root = _request_workspace_root(workspace_root, request_uuid)
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

    Called from ``apply()`` / ``destroy()`` ``finally`` blocks BEFORE the broader
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
    # Late-bound read of ``terraform_base._DEFAULT_TERRAFORM_WORKSPACE_DIR`` so a
    # test patch applied at the package level takes effect here too.
    import terraform_base as _tb

    workspace_root = Path(os.environ.get("TERRAFORM_WORKSPACE_DIR", _tb._DEFAULT_TERRAFORM_WORKSPACE_DIR))
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
    # Late-bound call to ``terraform_base.run_terraform`` so a test patch
    # applied at the package level (``@patch("terraform_base.run_terraform")``)
    # takes effect here — ``run_terraform`` is defined in a sibling submodule.
    import terraform_base as _tb

    _tb.run_terraform(init_args, staged)
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
    # Late-bound read of ``terraform_base._DEFAULT_TERRAFORM_WORKSPACE_DIR`` so a
    # test patch applied at the package level takes effect here too.
    import terraform_base as _tb

    workspace_root = Path(os.environ.get("TERRAFORM_WORKSPACE_DIR", _tb._DEFAULT_TERRAFORM_WORKSPACE_DIR))
    try:
        relative_parts = staged.resolve().relative_to(workspace_root.resolve()).parts
    except ValueError:
        relative_parts = ()
    request_root = workspace_root / relative_parts[0] if relative_parts else staged
    _purge_tfvars(request_root)
    _cleanup_workspace(staged)
