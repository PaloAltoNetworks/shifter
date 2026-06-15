#!/usr/bin/env python3
"""AWS portal deploy topology checks used by the platform workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


Runner = Callable[..., subprocess.CompletedProcess[str]]


class PortalDeployError(RuntimeError):
    """Raised when the portal deploy topology is inconsistent."""


@dataclass(frozen=True)
class TerraformTopology:
    enable_autoscaling: bool
    ec2_instance_id: str
    asg_name: str


@dataclass(frozen=True)
class ResolvedTopology:
    mode: str
    enable_autoscaling: bool
    instance_id: str = ""
    asg_name: str = ""

    @property
    def enable_autoscaling_output(self) -> str:
        return "true" if self.enable_autoscaling else "false"


def _run(
    command: list[str],
    *,
    cwd: str | None = None,
    runner: Runner = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _terraform_output_value(outputs: dict[str, object], name: str) -> object:
    entry = outputs.get(name)
    if not isinstance(entry, dict) or "value" not in entry:
        raise PortalDeployError(f"Terraform output {name!r} is required")
    return entry["value"]


def parse_terraform_outputs(raw_json: str) -> TerraformTopology:
    try:
        outputs = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise PortalDeployError("terraform output -json returned invalid JSON") from exc
    if not isinstance(outputs, dict):
        raise PortalDeployError("terraform output -json must return an object")

    enable_autoscaling = _terraform_output_value(outputs, "enable_autoscaling")
    if not isinstance(enable_autoscaling, bool):
        raise PortalDeployError("Terraform output 'enable_autoscaling' must be a boolean")

    ec2_instance_id = _terraform_output_value(outputs, "ec2_instance_id")
    asg_name = _terraform_output_value(outputs, "asg_name")
    return TerraformTopology(
        enable_autoscaling=enable_autoscaling,
        ec2_instance_id=str(ec2_instance_id or ""),
        asg_name=str(asg_name or ""),
    )


def parse_text_ids(stdout: str) -> list[str]:
    return [item for item in stdout.split() if item and item != "None"]


def resolve_topology(
    topology: TerraformTopology,
    *,
    running_instance_ids: list[str],
    asg_exists: bool,
) -> ResolvedTopology:
    if topology.enable_autoscaling:
        if topology.ec2_instance_id:
            raise PortalDeployError(
                "Terraform reports ASG mode but ec2_instance_id is populated; "
                "refusing to choose a deploy path"
            )
        if not topology.asg_name:
            raise PortalDeployError(
                "Terraform reports ASG mode but asg_name is empty; refusing to deploy"
            )
        if not asg_exists:
            raise PortalDeployError(
                f"Terraform reports ASG mode but ASG {topology.asg_name!r} was not found"
            )
        return ResolvedTopology(
            mode="asg",
            enable_autoscaling=True,
            asg_name=topology.asg_name,
        )

    if topology.asg_name:
        raise PortalDeployError(
            "Terraform reports single-instance mode but asg_name is populated; "
            "refusing to choose a deploy path"
        )
    if not topology.ec2_instance_id:
        raise PortalDeployError(
            "Terraform reports single-instance mode but ec2_instance_id is empty; refusing to deploy"
        )
    if len(running_instance_ids) != 1:
        raise PortalDeployError(
            f"Single-instance deploy requires exactly one running instance tagged for "
            f"the portal; found {len(running_instance_ids)}"
        )
    observed_instance_id = running_instance_ids[0]
    if observed_instance_id != topology.ec2_instance_id:
        raise PortalDeployError(
            f"Tagged running instance {observed_instance_id!r} does not match Terraform "
            f"ec2_instance_id {topology.ec2_instance_id!r}"
        )
    return ResolvedTopology(
        mode="single",
        enable_autoscaling=False,
        instance_id=topology.ec2_instance_id,
    )


def _running_instance_ids(instance_tag: str, *, runner: Runner) -> list[str]:
    result = _run(
        [
            "aws",
            "ec2",
            "describe-instances",
            "--filters",
            f"Name=tag:Name,Values={instance_tag}",
            "Name=instance-state-name,Values=running",
            "--query",
            "Reservations[].Instances[].InstanceId",
            "--output",
            "text",
        ],
        runner=runner,
    )
    return parse_text_ids(result.stdout)


def _asg_exists(asg_name: str, *, runner: Runner) -> bool:
    result = _run(
        [
            "aws",
            "autoscaling",
            "describe-auto-scaling-groups",
            "--auto-scaling-group-names",
            asg_name,
            "--query",
            "length(AutoScalingGroups)",
            "--output",
            "text",
        ],
        runner=runner,
    )
    return result.stdout.strip() == "1"


def _write_github_output(output_path: str, topology: ResolvedTopology) -> None:
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"enable_autoscaling={topology.enable_autoscaling_output}\n")
        handle.write(f"instance_id={topology.instance_id}\n")
        handle.write(f"asg_name={topology.asg_name}\n")


def resolve_topology_from_commands(
    *,
    terraform_dir: str,
    backend_config: str,
    instance_tag: str,
    github_output: str,
    runner: Runner = subprocess.run,
) -> ResolvedTopology:
    _run(
        ["terraform", "init", f"-backend-config={backend_config}"],
        cwd=terraform_dir,
        runner=runner,
    )
    terraform_outputs = _run(
        ["terraform", "output", "-json"],
        cwd=terraform_dir,
        runner=runner,
    )
    topology = parse_terraform_outputs(terraform_outputs.stdout)
    running_instance_ids = (
        _running_instance_ids(instance_tag, runner=runner)
        if not topology.enable_autoscaling
        else []
    )
    asg_exists = (
        _asg_exists(topology.asg_name, runner=runner)
        if topology.enable_autoscaling
        else False
    )
    resolved = resolve_topology(
        topology,
        running_instance_ids=running_instance_ids,
        asg_exists=asg_exists,
    )
    _write_github_output(github_output, resolved)
    return resolved


def _in_service_asg_instance_ids(asg_name: str, *, runner: Runner) -> list[str]:
    result = _run(
        [
            "aws",
            "autoscaling",
            "describe-auto-scaling-groups",
            "--auto-scaling-group-names",
            asg_name,
            "--query",
            "AutoScalingGroups[0].Instances[?LifecycleState=='InService'].InstanceId",
            "--output",
            "text",
        ],
        runner=runner,
    )
    return parse_text_ids(result.stdout)


def _image_check_script(image_digest: str) -> str:
    quoted_digest = shlex.quote(image_digest)
    return "\n".join(
        [
            "set -euo pipefail",
            f"EXPECTED_IMAGE_DIGEST={quoted_digest}",
            "IMAGE=$(docker inspect --format '{{.Config.Image}}' portal)",
            'case "$IMAGE" in',
            '  *"@${EXPECTED_IMAGE_DIGEST}") echo "portal image digest verified: ${IMAGE}" ;;',
            '  *) echo "Expected portal image digest ${EXPECTED_IMAGE_DIGEST}, found ${IMAGE}" >&2; exit 1 ;;',
            "esac",
        ]
    )


def verify_asg_image_digest(
    *,
    asg_name: str,
    image_digest: str,
    runner: Runner = subprocess.run,
) -> list[str]:
    if not asg_name:
        raise PortalDeployError("ASG image verification requires a non-empty ASG name")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise PortalDeployError("ASG image verification requires a sha256 image digest")

    instance_ids = _in_service_asg_instance_ids(asg_name, runner=runner)
    if not instance_ids:
        raise PortalDeployError(f"No in-service instances found in ASG {asg_name!r}")

    parameters = "commands=" + json.dumps([_image_check_script(image_digest)])
    send_command = _run(
        [
            "aws",
            "ssm",
            "send-command",
            "--document-name",
            "AWS-RunShellScript",
            "--instance-ids",
            *instance_ids,
            "--parameters",
            parameters,
            "--timeout-seconds",
            "120",
            "--query",
            "Command.CommandId",
            "--output",
            "text",
        ],
        runner=runner,
    )
    command_id = send_command.stdout.strip()
    if not command_id or command_id == "None":
        raise PortalDeployError("SSM did not return a command id for ASG image verification")

    for instance_id in instance_ids:
        _run(
            [
                "aws",
                "ssm",
                "wait",
                "command-executed",
                "--command-id",
                command_id,
                "--instance-id",
                instance_id,
            ],
            runner=runner,
        )
        status = _run(
            [
                "aws",
                "ssm",
                "get-command-invocation",
                "--command-id",
                command_id,
                "--instance-id",
                instance_id,
                "--query",
                "Status",
                "--output",
                "text",
            ],
            runner=runner,
        ).stdout.strip()
        if status != "Success":
            raise PortalDeployError(
                f"ASG image verification failed on {instance_id}: SSM status {status}"
            )
    return instance_ids


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser("resolve-topology")
    resolve_parser.add_argument("--terraform-dir", required=True)
    resolve_parser.add_argument("--backend-config", required=True)
    resolve_parser.add_argument("--instance-tag", required=True)
    resolve_parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT", ""),
    )

    verify_parser = subparsers.add_parser("verify-asg-image")
    verify_parser.add_argument("--asg-name", required=True)
    verify_parser.add_argument("--image-digest", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "resolve-topology":
            resolved = resolve_topology_from_commands(
                terraform_dir=args.terraform_dir,
                backend_config=args.backend_config,
                instance_tag=args.instance_tag,
                github_output=args.github_output,
            )
            print(f"Resolved portal deploy mode: {resolved.mode}")
        elif args.command == "verify-asg-image":
            instance_ids = verify_asg_image_digest(
                asg_name=args.asg_name,
                image_digest=args.image_digest,
            )
            print(f"Verified portal image digest on {len(instance_ids)} ASG instance(s)")
        return 0
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        print(f"::error::Command failed: {exc.cmd[0]} {stderr}", file=sys.stderr)
        return 1
    except PortalDeployError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
