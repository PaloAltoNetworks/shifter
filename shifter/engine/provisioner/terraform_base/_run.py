"""Running Terraform commands, and the ``apply`` / ``destroy`` / ``cleanup_state`` entry points."""

import contextlib
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from ._backend import _AWS_BACKEND, get_backend_config
from ._workspace import (
    _TF_INPUT_FALSE,
    _finalize_workspace,
    _run_init_in_staged_workspace,
    _stage_workspace,
    _write_tfvars,
)

logger = logging.getLogger(__name__)


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

        # Late-bound call to ``terraform_base.run_terraform`` so a test patch
        # applied at the package level (``@patch("terraform_base.run_terraform")``)
        # takes effect here — ``apply()`` shares this module with ``run_terraform``'s
        # definition, so a bare call would bypass a patch applied at the package.
        import terraform_base as _tb

        logger.info("Running terraform apply for %s...", label)
        result = _tb.run_terraform(
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
        output_result = _tb.run_terraform(
            ["output", "-json", "-no-color"],
            staged,
        )

        try:
            raw_outputs = json.loads(output_result.stdout)
        except json.JSONDecodeError as e:
            logger.exception("Failed to parse Terraform output: %s", output_result.stdout[:500])
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

        # Late-bound call to ``terraform_base.run_terraform`` so a test patch
        # applied at the package level takes effect here too.
        import terraform_base as _tb

        result = _tb.run_terraform(destroy_args, staged)
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

    # Late-bound call to ``terraform_base.get_object_storage`` so a test patch
    # applied at the package level (``@patch("terraform_base.get_object_storage")``)
    # takes effect here.
    import terraform_base as _tb

    storage = _tb.get_object_storage()

    try:
        storage.delete_object(bucket=backend.bucket, key=backend.state_object_key)
    except Exception as e:
        logger.warning("Failed to delete state file: %s", e)

    if backend.backend_type == _AWS_BACKEND:
        lock_key = f"{backend.state_object_key}.tflock"
        with contextlib.suppress(Exception):
            storage.delete_object(bucket=backend.bucket, key=lock_key)

    logger.info("%s Terraform state cleanup completed", label)
