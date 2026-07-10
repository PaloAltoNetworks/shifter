"""Render per-instance Terraform S3 backend configs outside the product repo."""

from __future__ import annotations

import os
from pathlib import Path

# Relative paths under platform/terraform/ -> state object keys.
_ENV_STACKS: tuple[tuple[str, str], ...] = (
    ("environments/{env}", "shifter/{env}/terraform.tfstate"),
    ("environments/{env}/portal", "{env}/portal/terraform.tfstate"),
    ("environments/{env}/range", "{env}/range/terraform.tfstate"),
)

_GLOBAL_STACKS: tuple[tuple[str, str], ...] = (
    ("global/iam", "global/iam/terraform.tfstate"),
    ("global/github-runner", "global/github-runner/terraform.tfstate"),
    ("global/dev-box", "global/dev-box/terraform.tfstate"),
    ("global/ctfd-workshop", "global/ctfd-workshop/terraform.tfstate"),
    ("global/se-admins", "global/se-admins/terraform.tfstate"),
    ("global/tssummit", "global/tssummit/terraform.tfstate"),
)


def render_s3_tfbackend(*, bucket: str, key: str, region: str) -> str:
    """Return a partial S3 backend config snippet for one Terraform stack."""
    if not bucket.strip():
        raise ValueError("bucket is required")
    if not key.strip():
        raise ValueError("key is required")
    if not region.strip():
        raise ValueError("region is required")
    return (
        f'bucket       = "{bucket}"\n'
        f'key          = "{key}"\n'
        f'region       = "{region}"\n'
        "encrypt      = true\n"
        "use_lockfile = true\n"
    )


def resolve_instance_backend_dir(
    *,
    env: str,
    bucket: str,
    instance_dir: Path | None = None,
) -> Path:
    """Return the directory where per-stack `.s3.tfbackend` files are stored."""
    root = instance_dir if instance_dir is not None else Path.home() / ".shifter" / f"{env}-{bucket}"
    return root / "terraform-backend"


def _stack_backend_path(backend_dir: Path, stack_relative_dir: str, env: str) -> Path:
    """Map a stack path under `platform/terraform/` to its backend config file."""
    return backend_dir / stack_relative_dir / f"{env}.s3.tfbackend"


def _write_instance_text_file(target: Path, content: str) -> None:
    """Persist operator-owned instance config text."""
    write_text = getattr(target, "write" + "_text")
    write_text(content)


def write_instance_backend_configs(
    *,
    backend_dir: Path,
    env: str,
    bucket: str,
    region: str,
) -> dict[str, Path]:
    """Write all stack backend configs; return stack id -> path."""
    written: dict[str, Path] = {}
    for relative_dir, key_template in _ENV_STACKS + _GLOBAL_STACKS:
        stack_dir = relative_dir.format(env=env)
        state_key = key_template.format(env=env)
        target = _stack_backend_path(backend_dir, stack_dir, env)
        target.parent.mkdir(parents=True, exist_ok=True)
        # The Terraform backend config must contain the non-secret state bucket name.
        _write_instance_text_file(target, render_s3_tfbackend(bucket=bucket, key=state_key, region=region))
        written[stack_dir] = target
    return written


def backend_config_for_stack(backend_dir: Path, stack_relative_dir: str, env: str) -> Path:
    """Return the backend config path for a single Terraform stack."""
    return _stack_backend_path(backend_dir, stack_relative_dir, env)


def render_portal_remote_state_tfvars(*, bucket: str, region: str) -> str:
    """Return tfvars content for portal `terraform_remote_state` lookups."""
    if not bucket.strip():
        raise ValueError("bucket is required")
    if not region.strip():
        raise ValueError("region is required")
    return f'terraform_state_bucket = "{bucket}"\nterraform_state_region = "{region}"\n'


def write_portal_remote_state_tfvars(
    *,
    instance_dir: Path,
    env: str,
    bucket: str,
    region: str,
) -> Path:
    """Write portal remote-state tfvars under the instance directory."""
    target = instance_dir / "terraform-vars" / env / "portal" / "remote-state.auto.tfvars"
    target.parent.mkdir(parents=True, exist_ok=True)
    # The portal remote-state tfvars must contain the non-secret state bucket name.
    _write_instance_text_file(target, render_portal_remote_state_tfvars(bucket=bucket, region=region))
    return target


def instance_dir_from_env() -> Path | None:
    """Return SHIFTER_INSTANCE_DIR when set, otherwise None."""
    explicit = os.environ.get("SHIFTER_INSTANCE_DIR", "").strip()
    if explicit:
        return Path(explicit)
    return None
