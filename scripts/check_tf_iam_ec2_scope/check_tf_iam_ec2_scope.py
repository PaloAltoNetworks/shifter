#!/usr/bin/env python3
"""Lint EC2 instance lifecycle IAM statements in Terraform files.

The engine provisioner legitimately needs to create and manage EC2 range
instances, but mutable instance lifecycle APIs must not remain in wildcard
statements that can target every EC2 instance in the account.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

MUTABLE_INSTANCE_ACTIONS: set[str] = {
    "ec2:ModifyInstanceAttribute",
    "ec2:ModifyInstanceMetadataOptions",
    "ec2:StartInstances",
    "ec2:StopInstances",
    "ec2:TerminateInstances",
}

REQUIRED_RESOURCE_SNIPPET = (
    'arn:aws:ec2:${local.region}:${local.account_id}:instance/*'
)
REQUIRED_TAG_KEYS: tuple[str, ...] = (
    "ec2:ResourceTag/shifter:system",
    "ec2:ResourceTag/shifter:environment",
    "ec2:ResourceTag/ManagedBy",
)

_RESOURCE_RE = re.compile(r'^\s*resource\s+"aws_iam_role_policy"\s+"([^"]+)"\s*\{')
_ACTION_RE = re.compile(r'"(ec2:[^"]+)"')


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
        if '"ec2:' in block:
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


def _mutable_instance_action_matches(actions: set[str]) -> list[str]:
    matches: set[str] = set()
    for action in actions:
        for mutable_action in MUTABLE_INSTANCE_ACTIONS:
            if action == mutable_action or fnmatchcase(mutable_action, action):
                matches.add(action)
    return sorted(matches)


def _wildcard_action_violations(
    path: Path, line: int, mutable_actions: list[str]
) -> list[Violation]:
    wildcard_actions = [action for action in mutable_actions if "*" in action]
    if not wildcard_actions:
        return []
    return [
        Violation(
            path,
            line,
            "mutable EC2 instance lifecycle actions must be enumerated, "
            f"not granted through wildcard action patterns ({', '.join(wildcard_actions)})",
        )
    ]


def _statement_scope_violations(
    path: Path, line: int, block: str, mutable_actions: list[str]
) -> list[Violation]:
    violations: list[Violation] = []
    if 'Resource = "*"' in block:
        violations.append(
            Violation(
                path,
                line,
                "mutable EC2 instance lifecycle actions must not use Resource=* "
                f"({', '.join(mutable_actions)})",
            )
        )
    if REQUIRED_RESOURCE_SNIPPET not in block:
        violations.append(
            Violation(
                path,
                line,
                "mutable EC2 instance lifecycle actions must be scoped to EC2 "
                "instance ARNs",
            )
        )
    return violations


def _required_tag_violations(path: Path, line: int, block: str) -> list[Violation]:
    return [
        Violation(
            path,
            line,
            f"mutable EC2 instance lifecycle actions must require {tag_key}",
        )
        for tag_key in REQUIRED_TAG_KEYS
        if tag_key not in block
    ]


def _statement_mixing_violations(path: Path, line: int, block: str) -> list[Violation]:
    if "ec2:Describe*" not in block:
        return []
    return [
        Violation(
            path,
            line,
            "Describe APIs must stay separate from mutable lifecycle actions",
        )
    ]


def _check_statement(path: Path, line: int, block: str) -> list[Violation]:
    mutable_actions = _mutable_instance_action_matches(_actions(block))
    if not mutable_actions:
        return []

    return [
        *_wildcard_action_violations(path, line, mutable_actions),
        *_statement_scope_violations(path, line, block, mutable_actions),
        *_required_tag_violations(path, line, block),
        *_statement_mixing_violations(path, line, block),
    ]


def check_file(path: Path, resource_name: str = "ec2_provisioning") -> list[Violation]:
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
            "usage: check_tf_iam_ec2_scope.py FILE.tf [FILE.tf ...]",
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
            "EC2 instance lifecycle IAM scope violations "
            f"({len(violations)} total):",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
