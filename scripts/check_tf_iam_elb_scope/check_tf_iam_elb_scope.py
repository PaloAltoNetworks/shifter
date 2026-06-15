#!/usr/bin/env python3
"""Lint ELBv2 (Gateway Load Balancer) IAM statements in Terraform files.

The engine provisioner legitimately needs to create and manage Gateway Load
Balancer infrastructure for NGFW traffic steering, but mutable ELBv2 APIs
must not remain on wildcard statements that can target every load balancer,
target group, or listener in the account.

Three action families are pinned independently:

- Existing-resource mutations (Delete / Modify / Register / Deregister /
  RemoveTags) must be scoped to GWLB ARNs and require Shifter ownership
  resource tags.
- Resource creation (Create*LoadBalancer / Create*TargetGroup / CreateListener)
  must be scoped to GWLB ARNs and require Shifter ownership request tags.
- Tag-on-create (AddTags) must be scoped to GWLB ARNs and require both an
  elasticloadbalancing:CreateAction condition and Shifter ownership request
  tags.

Describe APIs must stay in their own wildcard statement (AWS service
authorization requires Resource = "*" for the ELBv2 read APIs).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

MUTABLE_EXISTING_ELB_ACTIONS: set[str] = {
    "elasticloadbalancing:DeleteLoadBalancer",
    "elasticloadbalancing:DeleteTargetGroup",
    "elasticloadbalancing:DeleteListener",
    "elasticloadbalancing:ModifyLoadBalancerAttributes",
    "elasticloadbalancing:ModifyTargetGroup",
    "elasticloadbalancing:ModifyTargetGroupAttributes",
    "elasticloadbalancing:RegisterTargets",
    "elasticloadbalancing:DeregisterTargets",
    "elasticloadbalancing:RemoveTags",
}
CREATE_ELB_ACTIONS: set[str] = {
    "elasticloadbalancing:CreateLoadBalancer",
    "elasticloadbalancing:CreateTargetGroup",
    "elasticloadbalancing:CreateListener",
}
TAG_ON_CREATE_ELB_ACTIONS: set[str] = {
    "elasticloadbalancing:AddTags",
}
ALL_MUTABLE_ELB_ACTIONS: set[str] = (
    MUTABLE_EXISTING_ELB_ACTIONS | CREATE_ELB_ACTIONS | TAG_ON_CREATE_ELB_ACTIONS
)

REQUIRED_RESOURCE_SNIPPETS: tuple[str, ...] = (
    "loadbalancer/gwy/",
    "listener/gwy/",
    "targetgroup/",
)
EXISTING_RESOURCE_TAG_KEYS: tuple[str, ...] = (
    "elasticloadbalancing:ResourceTag/shifter:system",
    "elasticloadbalancing:ResourceTag/shifter:environment",
    "elasticloadbalancing:ResourceTag/ManagedBy",
)
REQUEST_TAG_KEYS: tuple[str, ...] = (
    "aws:RequestTag/shifter:system",
    "aws:RequestTag/shifter:environment",
    "aws:RequestTag/ManagedBy",
)
CREATE_ACTION_CONDITION_KEY: str = "elasticloadbalancing:CreateAction"

_RESOURCE_RE = re.compile(r'^\s*resource\s+"aws_iam_role_policy"\s+"([^"]+)"\s*\{')
_ACTION_RE = re.compile(r'"(elasticloadbalancing:[^"]+)"')


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
        if '"elasticloadbalancing:' in block:
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


def _action_matches(actions: set[str], family: set[str]) -> list[str]:
    matches: set[str] = set()
    for action in actions:
        for member in family:
            if action == member or fnmatchcase(member, action):
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
            "mutable ELBv2 actions must be enumerated, "
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
                "mutable ELBv2 actions must not use Resource=* "
                f"({', '.join(mutable_actions)})",
            )
        )
    if not all(snippet in block for snippet in REQUIRED_RESOURCE_SNIPPETS):
        violations.append(
            Violation(
                path,
                line,
                "mutable ELBv2 actions must be scoped to GWLB ELBv2 ARNs "
                "(loadbalancer/gwy/, listener/gwy/, targetgroup/)",
            )
        )
    return violations


def _required_keys_violations(
    path: Path,
    line: int,
    block: str,
    keys: tuple[str, ...],
    reason_template: str,
) -> list[Violation]:
    return [
        Violation(path, line, reason_template.format(key=key))
        for key in keys
        if key not in block
    ]


def _statement_mixing_violations(path: Path, line: int, block: str) -> list[Violation]:
    if "elasticloadbalancing:Describe" not in block:
        return []
    return [
        Violation(
            path,
            line,
            "Describe APIs must stay separate from mutable ELBv2 actions",
        )
    ]


def _check_statement(path: Path, line: int, block: str) -> list[Violation]:
    actions = _actions(block)
    mutable_actions = _action_matches(actions, ALL_MUTABLE_ELB_ACTIONS)
    if not mutable_actions:
        return []

    violations: list[Violation] = []
    violations.extend(_wildcard_action_violations(path, line, mutable_actions))
    violations.extend(_statement_scope_violations(path, line, block, mutable_actions))
    violations.extend(_statement_mixing_violations(path, line, block))

    has_existing = bool(_action_matches(actions, MUTABLE_EXISTING_ELB_ACTIONS))
    has_create = bool(_action_matches(actions, CREATE_ELB_ACTIONS))
    has_tag_on_create = bool(_action_matches(actions, TAG_ON_CREATE_ELB_ACTIONS))

    if has_existing:
        violations.extend(
            _required_keys_violations(
                path,
                line,
                block,
                EXISTING_RESOURCE_TAG_KEYS,
                "mutable ELBv2 actions on existing resources must require {key}",
            )
        )
    if has_create:
        violations.extend(
            _required_keys_violations(
                path,
                line,
                block,
                REQUEST_TAG_KEYS,
                "ELBv2 create actions must require {key}",
            )
        )
    if has_tag_on_create:
        violations.extend(
            _required_keys_violations(
                path,
                line,
                block,
                REQUEST_TAG_KEYS,
                "ELBv2 AddTags must require {key}",
            )
        )
        if CREATE_ACTION_CONDITION_KEY not in block:
            violations.append(
                Violation(
                    path,
                    line,
                    "ELBv2 AddTags must require "
                    f"{CREATE_ACTION_CONDITION_KEY} (creation-time-only tagging)",
                )
            )

    return violations


def check_file(path: Path, resource_name: str = "gwlb") -> list[Violation]:
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
            "usage: check_tf_iam_elb_scope.py FILE.tf [FILE.tf ...]",
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
            "ELBv2 IAM scope violations "
            f"({len(violations)} total):",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
