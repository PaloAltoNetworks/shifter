#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from common import load_event_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Overwrite workshop box flag files across provisioned Shifter ranges via SSM."
    )
    parser.add_argument("range_ids", nargs="*", help="One or more Shifter range IDs.")
    parser.add_argument(
        "--range-id-file",
        help="Optional file containing one range ID per line.",
    )
    parser.add_argument(
        "--event-file",
        help="Path to the workshop event JSON. Defaults to scripts/ctfd-workshop/agentic_workshop.json.",
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE"),
        help="AWS CLI profile. Defaults to AWS_PROFILE.",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "us-east-2"),
        help="AWS region. Defaults to AWS_REGION or us-east-2.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=5,
        help="Polling interval while waiting for SSM command completion.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Per-command timeout while waiting for SSM completion.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without calling AWS.",
    )
    return parser.parse_args()


def aws_base_command(profile: str | None, region: str) -> list[str]:
    command = ["aws"]
    if profile:
        command.extend(["--profile", profile])
    command.extend(["--region", region])
    return command


def aws_json(
    args: list[str],
    *,
    profile: str | None,
    region: str,
) -> dict[str, Any]:
    command = aws_base_command(profile, region) + args
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = result.stdout.strip()
    return json.loads(stdout) if stdout else {}


def collect_range_ids(args: argparse.Namespace) -> list[str]:
    range_ids = list(args.range_ids)
    if args.range_id_file:
        with Path(args.range_id_file).open("r", encoding="utf-8") as handle:
            range_ids.extend(
                line.strip()
                for line in handle
                if line.strip() and not line.lstrip().startswith("#")
            )
    unique = []
    seen = set()
    for range_id in range_ids:
        if range_id not in seen:
            unique.append(range_id)
            seen.add(range_id)
    if not unique:
        raise SystemExit("provide at least one range ID or --range-id-file")
    return unique


def describe_range_instances(range_id: str, *, profile: str | None, region: str) -> dict[str, dict[str, Any]]:
    response = aws_json(
        [
            "ec2",
            "describe-instances",
            "--filters",
            f"Name=tag:shifter:range_id,Values={range_id}",
            "Name=instance-state-name,Values=running",
        ],
        profile=profile,
        region=region,
    )

    instances: dict[str, dict[str, Any]] = {}
    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
            name = tags.get("Name") or tags.get("shifter:name")
            if name:
                instances[name] = instance
    return instances


def send_ssm_command(
    *,
    instance_id: str,
    document_name: str,
    commands: list[str],
    profile: str | None,
    region: str,
) -> str:
    response = aws_json(
        [
            "ssm",
            "send-command",
            "--instance-ids",
            instance_id,
            "--document-name",
            document_name,
            "--parameters",
            json.dumps({"commands": commands}),
        ],
        profile=profile,
        region=region,
    )
    return response["Command"]["CommandId"]


def wait_for_command(
    *,
    command_id: str,
    instance_id: str,
    poll_seconds: int,
    timeout_seconds: int,
    profile: str | None,
    region: str,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        invocation = aws_json(
            [
                "ssm",
                "get-command-invocation",
                "--command-id",
                command_id,
                "--instance-id",
                instance_id,
            ],
            profile=profile,
            region=region,
        )
        status = invocation.get("Status")
        if status == "Success":
            return
        if status in {"Cancelled", "Cancelling", "TimedOut", "Failed"}:
            raise RuntimeError(
                f"SSM command failed for {instance_id}: {status}\n"
                f"stdout:\n{invocation.get('StandardOutputContent', '')}\n"
                f"stderr:\n{invocation.get('StandardErrorContent', '')}"
            )
        time.sleep(poll_seconds)
    raise RuntimeError(f"timed out waiting for SSM command {command_id} on {instance_id}")


def linux_commands(box: dict[str, Any]) -> list[str]:
    user = box["user"]
    root = box["root"]
    return [
        "set -euo pipefail",
        f"printf '%s' {shlex.quote(user['flag'])} | sudo tee {shlex.quote(user['path'])} >/dev/null",
        f"sudo chown {shlex.quote(user['owner'])} {shlex.quote(user['path'])}",
        f"sudo chmod {shlex.quote(user['mode'])} {shlex.quote(user['path'])}",
        f"printf '%s' {shlex.quote(root['flag'])} | sudo tee {shlex.quote(root['path'])} >/dev/null",
        f"sudo chown {shlex.quote(root['owner'])} {shlex.quote(root['path'])}",
        f"sudo chmod {shlex.quote(root['mode'])} {shlex.quote(root['path'])}",
        f"sudo grep -Fxq -- {shlex.quote(user['flag'])} {shlex.quote(user['path'])}",
        f"sudo grep -Fxq -- {shlex.quote(root['flag'])} {shlex.quote(root['path'])}",
    ]


def windows_commands(box: dict[str, Any]) -> list[str]:
    user = box["user"]
    root = box["root"]
    return [
        f"$userPath = '{user['path']}'",
        f"$userFlag = '{user['flag']}'",
        f"$rootPath = '{root['path']}'",
        f"$rootFlag = '{root['flag']}'",
        "Set-Content -Path $userPath -Value $userFlag -Encoding ascii -NoNewline",
        "Set-Content -Path $rootPath -Value $rootFlag -Encoding ascii -NoNewline",
        "if ((Get-Content -Path $userPath -Raw) -ne $userFlag) { throw 'user flag verification failed' }",
        "if ((Get-Content -Path $rootPath -Raw) -ne $rootFlag) { throw 'root flag verification failed' }",
    ]


def main() -> int:
    args = parse_args()
    range_ids = collect_range_ids(args)
    event = load_event_config(args.event_file)

    for range_id in range_ids:
        print(f"sync range: {range_id}")
        instances = describe_range_instances(range_id, profile=args.profile, region=args.region)

        for box in event["boxes"]:
            instance = instances.get(box["instance_name"])
            if not instance:
                raise RuntimeError(
                    f"range {range_id} is missing instance {box['instance_name']}"
                )

            instance_id = instance["InstanceId"]
            document_name = (
                "AWS-RunShellScript" if box["os_type"] == "linux" else "AWS-RunPowerShellScript"
            )
            commands = linux_commands(box) if box["os_type"] == "linux" else windows_commands(box)
            print(f"  {box['instance_name']} -> {instance_id} ({document_name})")

            if args.dry_run:
                for command in commands:
                    print(f"    {command}")
                continue

            command_id = send_ssm_command(
                instance_id=instance_id,
                document_name=document_name,
                commands=commands,
                profile=args.profile,
                region=args.region,
            )
            wait_for_command(
                command_id=command_id,
                instance_id=instance_id,
                poll_seconds=args.poll_seconds,
                timeout_seconds=args.timeout_seconds,
                profile=args.profile,
                region=args.region,
            )

    print("flag sync complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
