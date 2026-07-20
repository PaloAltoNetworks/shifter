"""Shared Terraform runner helpers.

Provides common functions used by both terraform_runner.py (NGFW) and
range_terraform_runner.py (Range). Each caller passes a state key prefix
and label to distinguish its state path and log messages.

Backends:
- AWS uses the S3 backend with object keys like
  ``{prefix}/{request_uuid}/terraform.tfstate`` and DynamoDB locking.
- GCP uses the GCS backend with object keys like
  ``{prefix}/{request_uuid}/default.tfstate`` and no external lock table.

Split across private submodules by responsibility and re-exported here so
callers keep using ``from terraform_base import X`` / ``terraform_base.<name>``
exactly as before the split:

- ``_backend``: backend type / bucket / state-key resolution and state
  existence checks (``TerraformBackendConfig``, ``get_backend_type``,
  ``get_state_bucket``, ``get_locks_table``, ``get_state_key``,
  ``get_backend_config``, ``has_terraform_state``).
- ``_workspace``: per-request workspace staging, secret purging, cleanup, and
  ``terraform init`` argument building (``_stage_workspace``,
  ``_purge_tfvars``, ``_cleanup_workspace``, ``_write_tfvars``,
  ``_finalize_workspace``, ``_build_init_args``,
  ``_run_init_in_staged_workspace``).
- ``_run``: running Terraform commands and the ``apply`` / ``destroy`` /
  ``cleanup_state`` entry points.

Three collaborator names below (``resolve_cloud_provider``,
``get_object_storage``, ``_DEFAULT_TERRAFORM_WORKSPACE_DIR``) are re-exported
here — not just imported by the submodule that uses them — because the test
suite patches them at ``terraform_base.<name>``. Submodule functions call back
into this package at call time (``import terraform_base as _tb;
_tb.<name>``) so those patches take effect, mirroring the ``range_ops`` and
``components.network`` splits.
"""

from cloud import get_object_storage
from config import resolve_cloud_provider

from ._backend import (
    TerraformBackendConfig,
    _get_provider,
    _parse_backend_url,
    get_backend_config,
    get_backend_type,
    get_locks_table,
    get_state_bucket,
    get_state_key,
    has_terraform_state,
)
from ._run import apply, cleanup_state, destroy, run_terraform
from ._workspace import (
    _CONTAINER_TERRAFORM_WORKSPACE_DIR,
    _DEFAULT_TERRAFORM_WORKSPACE_DIR,
    _build_init_args,
    _cleanup_workspace,
    _finalize_workspace,
    _purge_tfvars,
    _request_workspace_root,
    _run_init_in_staged_workspace,
    _stage_workspace,
    _validate_request_uuid,
    _write_tfvars,
)

__all__ = [
    "_CONTAINER_TERRAFORM_WORKSPACE_DIR",
    "_DEFAULT_TERRAFORM_WORKSPACE_DIR",
    "TerraformBackendConfig",
    "_build_init_args",
    "_cleanup_workspace",
    "_finalize_workspace",
    "_get_provider",
    "_parse_backend_url",
    "_purge_tfvars",
    "_request_workspace_root",
    "_run_init_in_staged_workspace",
    "_stage_workspace",
    "_validate_request_uuid",
    "_write_tfvars",
    "apply",
    "cleanup_state",
    "destroy",
    "get_backend_config",
    "get_backend_type",
    "get_locks_table",
    "get_object_storage",
    "get_state_bucket",
    "get_state_key",
    "has_terraform_state",
    "resolve_cloud_provider",
    "run_terraform",
]
