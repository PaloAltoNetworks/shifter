#!/usr/bin/env python3
"""Render per-instance AWS Terraform backend configs for CI and local deploys."""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))

import terraform_backend as tb  # noqa: E402

ALLOWED_ENVS = frozenset({"dev", "proof", "prod"})
_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def _default_instance_root() -> Path:
    explicit = os.environ.get("SHIFTER_INSTANCE_DIR", "").strip()
    if explicit:
        return Path(explicit)
    runner_temp = os.environ.get("RUNNER_TEMP", "").strip()
    if runner_temp:
        return Path(runner_temp) / "shifter-instance"
    return Path.home() / ".shifter" / "ci-render"


def validate_env(env: str) -> str:
    normalized = env.strip()
    if normalized not in ALLOWED_ENVS:
        allowed = ", ".join(sorted(ALLOWED_ENVS))
        raise ValueError(f"unsupported environment {env!r}; allowed: {allowed}")
    return normalized


def validate_bucket(bucket: str) -> str:
    normalized = bucket.strip()
    if not normalized or not _BUCKET_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid TF_INFRA_STATE_BUCKET value: {bucket!r}")
    return normalized


def append_github_env(path: Path, key: str, value: str) -> None:
    """Append a single key/value pair to a GitHub Actions env file safely."""
    if not key.isidentifier():
        raise ValueError(f"invalid GitHub env key: {key!r}")
    if "\n" in value or "\r" in value:
        delimiter = f"EOF_{uuid.uuid4().hex}"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def render_outputs(
    *,
    env: str,
    bucket: str,
    region: str,
    instance_dir: Path,
    stack: str,
) -> dict[str, str]:
    backend_dir = tb.resolve_instance_backend_dir(
        env=env,
        bucket=bucket,
        instance_dir=instance_dir,
    )
    tb.write_instance_backend_configs(
        backend_dir=backend_dir,
        env=env,
        bucket=bucket,
        region=region,
    )
    tb.write_portal_remote_state_tfvars(
        instance_dir=instance_dir,
        env=env,
        bucket=bucket,
        region=region,
    )

    outputs = {
        "SHIFTER_BACKEND_CONFIG_DIR": str(backend_dir),
        "SHIFTER_INSTANCE_DIR": str(instance_dir),
    }
    if stack:
        if stack == "core":
            stack_dir = f"environments/{env}"
        elif stack.startswith("global/"):
            stack_dir = stack
        else:
            stack_dir = f"environments/{env}/{stack}"
        outputs["SHIFTER_BACKEND_CONFIG_PATH"] = str(
            tb.backend_config_for_stack(backend_dir, stack_dir, env)
        )
        outputs["SHIFTER_PORTAL_REMOTE_STATE_TFVARS"] = str(
            instance_dir / "terraform-vars" / env / "portal" / "remote-state.auto.tfvars"
        )
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True)
    parser.add_argument("--bucket", default=os.environ.get("TF_INFRA_STATE_BUCKET", "").strip())
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-2").strip())
    parser.add_argument("--instance-dir", default="")
    parser.add_argument("--stack", default="", help="Optional stack id: core, portal, range, global/iam, ...")
    parser.add_argument(
        "--github-env",
        action="store_true",
        help="Append rendered paths to GITHUB_ENV instead of printing shell assignments",
    )
    args = parser.parse_args()

    try:
        env = validate_env(args.env)
        bucket = validate_bucket(args.bucket)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if not bucket:
        print("::error::TF_INFRA_STATE_BUCKET is required", file=sys.stderr)
        return 1

    instance_dir = Path(args.instance_dir) if args.instance_dir else _default_instance_root()
    try:
        outputs = render_outputs(
            env=env,
            bucket=bucket,
            region=args.region.strip() or "us-east-2",
            instance_dir=instance_dir,
            stack=args.stack.strip(),
        )
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if args.github_env:
        github_env_path = os.environ.get("GITHUB_ENV", "").strip()
        if not github_env_path:
            print("::error::--github-env requires GITHUB_ENV to be set", file=sys.stderr)
            return 1
        env_path = Path(github_env_path)
        for key, value in outputs.items():
            append_github_env(env_path, key, value)
        return 0

    for key, value in outputs.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
