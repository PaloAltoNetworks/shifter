#!/usr/bin/env python3
"""Lint SSM Run Command IAM statements in Terraform files.

The engine provisioner legitimately uses SSM Run Command to orchestrate range
guest setup (e.g. domain-controller promotion), but `ssm:SendCommand` and
`ec2:RebootInstances` must not be able to target every EC2 instance in the
account. A provisioner compromise must be contained to Shifter range guests.

Rules enforced on the `ssm_run_command` task-role policy:

- `ssm:SendCommand` must never use `Resource = "*"`.
- `ssm:SendCommand` statements that target an EC2 instance ARN must require the
  range-instance SSM resource tags (`ssm:resourceTag/shifter:system`,
  `ssm:resourceTag/shifter:environment`, `ssm:resourceTag/shifter:range_id`) so
  the call is scoped to range guests and denies portal / runner instances.
  Document-only `SendCommand` statements (the AWS-managed shell/PowerShell
  documents) carry no instance ARN and are exempt from the tag requirement.
- `ec2:RebootInstances` must never use `Resource = "*"` and must require the
  EC2 ownership tags (`ec2:ResourceTag/shifter:system`,
  `ec2:ResourceTag/shifter:environment`, `ec2:ResourceTag/ManagedBy`), mirroring
  the EC2 instance lifecycle statement.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

INSTANCE_ARN_SNIPPET = ":instance/"

REQUIRED_SEND_COMMAND_TAG_KEYS: tuple[str, ...] = (
    "ssm:resourceTag/shifter:system",
    "ssm:resourceTag/shifter:environment",
    "ssm:resourceTag/shifter:range_id",
)
REQUIRED_REBOOT_TAG_KEYS: tuple[str, ...] = (
    "ec2:ResourceTag/shifter:system",
    "ec2:ResourceTag/shifter:environment",
    "ec2:ResourceTag/ManagedBy",
)

_RESOURCE_RE = re.compile(r'^\s*resource\s+"aws_iam_role_policy"\s+"([^"]+)"\s*\{')
_ACTION_RE = re.compile(r'"((?:ssm|ec2):[^"]+)"')


@dataclass
class Violation:
    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.reason}"


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _extract_statement_blocks(lines: list[str]) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not re.match(r"^\s*\{\s*$", line):
            idx += 1
            continue

        start_idx = idx
        depth = _brace_delta(line)
        idx += 1
        while idx < len(lines) and depth > 0:
            depth += _brace_delta(lines[idx])
            idx += 1

        block = "\n".join(lines[start_idx:idx])
        if '"ssm:' in block or '"ec2:' in block:
            blocks.append((start_idx + 1, block))
    return blocks


def _extract_policy_body(lines: list[str], resource_name: str) -> tuple[int, list[str]] | None:
    in_resource = False
    resource_depth = 0
    resource_start = 0

    for idx, line in enumerate(lines):
        if not in_resource:
            match = _RESOURCE_RE.match(line)
            if match and match.group(1) == resource_name:
                in_resource = True
                resource_depth = _brace_delta(line)
                resource_start = idx
            continue

        resource_depth += _brace_delta(line)
        if resource_depth <= 0:
            return resource_start + 1, lines[resource_start : idx + 1]

    return None


def _actions(block: str) -> set[str]:
    return set(_ACTION_RE.findall(block))


def _send_command_violations(path: Path, line: int, block: str) -> list[Violation]:
    if "ssm:SendCommand" not in _actions(block):
        return []

    violations: list[Violation] = []
    if 'Resource = "*"' in block:
        violations.append(
            Violation(path, line, "ssm:SendCommand must not use Resource=*")
        )

    # Only instance-target statements need the range-tag conditions. Document-only
    # statements (no EC2 instance ARN) are authorized separately and carry no
    # instance tag context.
    if INSTANCE_ARN_SNIPPET in block:
        violations.extend(
            Violation(
                path,
                line,
                "ssm:SendCommand to EC2 instance targets must require "
                f"{tag_key}",
            )
            for tag_key in REQUIRED_SEND_COMMAND_TAG_KEYS
            if tag_key not in block
        )
    return violations


def _reboot_violations(path: Path, line: int, block: str) -> list[Violation]:
    if "ec2:RebootInstances" not in _actions(block):
        return []

    violations: list[Violation] = []
    if 'Resource = "*"' in block:
        violations.append(
            Violation(path, line, "ec2:RebootInstances must not use Resource=*")
        )
    violations.extend(
        Violation(
            path,
            line,
            f"ec2:RebootInstances must require {tag_key}",
        )
        for tag_key in REQUIRED_REBOOT_TAG_KEYS
        if tag_key not in block
    )
    return violations


def _check_statement(path: Path, line: int, block: str) -> list[Violation]:
    return [
        *_send_command_violations(path, line, block),
        *_reboot_violations(path, line, block),
    ]


def check_file(path: Path, resource_name: str = "ssm_run_command") -> list[Violation]:
    lines = path.read_text().splitlines()
    policy = _extract_policy_body(lines, resource_name)
    if policy is None:
        return []

    policy_start_line, policy_lines = policy
    violations: list[Violation] = []
    for relative_line, block in _extract_statement_blocks(policy_lines):
        line = policy_start_line + relative_line - 1
        violations.extend(_check_statement(path, line, block))
    return violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: check_tf_iam_ssm_scope.py FILE.tf [FILE.tf ...]",
            file=sys.stderr,
        )
        return 2

    violations: list[Violation] = []
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"{path}: file not found", file=sys.stderr)
            return 2
        if path.suffix == ".tf":
            violations.extend(check_file(path))

    if violations:
        print(
            "SSM Run Command IAM scope violations "
            f"({len(violations)} total):",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
