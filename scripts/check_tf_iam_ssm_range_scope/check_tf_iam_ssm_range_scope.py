#!/usr/bin/env python3
"""Lint SSM Parameter Store IAM scope on range *guest instance* roles.

The range instance role (``aws_iam_role.range_instance``) is shared by every
range guest (Victim, Kali, DC). Granting it SSM Parameter Store access on a
Resource that wildcards across the environment or range segment lets any range
guest read or modify every other range's (and every other environment's)
credential namespace -- the cross-tenant exposure in issue #1178.

Range guests do not use their instance role for Parameter Store at all today:
all SSM access is brokered by the provisioner via Run Command (``{{ssm-secure:
<name>}}`` substitution and provisioner-side ``ssm:GetParameter``), so any such
grant on the guest role is both over-broad and unnecessary.

This checker rejects, on policies attached to a range-instance role, SSM
parameter grants whose Resource crosses the range boundary:

  - ``parameter/shifter/*/range/...``     (environment wildcard)
  - ``parameter/shifter/<env>/range/*``   (range wildcard not bound to a
                                           concrete ``${var.range_id}``)

A correctly range-scoped grant
(``parameter/shifter/<env>/range/${var.range_id}/*``) passes, and the
provisioner orchestrator role's env-scoped grant in
``engine-provisioner/iam.tf`` is not inspected because it is not attached to a
range-instance role.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Concrete SSM Parameter Store actions. Wildcard actions (``ssm:*``,
# ``ssm:Get*``, or a full ``*``) that cover any of these are also treated as
# parameter grants by ``_action_grants_ssm_parameter``.
_SSM_PARAMETER_ACTIONS: frozenset[str] = frozenset(
    {
        "ssm:putparameter",
        "ssm:getparameter",
        "ssm:getparameters",
        "ssm:getparametersbypath",
        "ssm:getparameterhistory",
        "ssm:deleteparameter",
        "ssm:deleteparameters",
        "ssm:labelparameterversion",
    }
)

# Default role-name substring that identifies a range *guest* instance role.
DEFAULT_ROLE_SUBSTRING = "range_instance"

_RESOURCE_RE = re.compile(r'^\s*resource\s+"(aws_iam_role_policy|aws_iam_policy)"\s+"([^"]+)"\s*\{')
_ACTION_FIELD_RE = re.compile(r'Action\s*=\s*(\[[^\]]*\]|"[^"]*")', re.DOTALL)
_RESOURCE_FIELD_RE = re.compile(r'Resource\s*=\s*(\[[^\]]*\]|"[^"]*")', re.DOTALL)
_QUOTED_RE = re.compile(r'"([^"]*)"')
_ENV_WILDCARD_RE = re.compile(r"parameter/shifter/\*/range")
_RANGE_SEGMENT_RE = re.compile(r"parameter/shifter/[^/\"]+/range/([^\"]*)")


@dataclass
class Violation:
    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.reason}"


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _extract_resource_blocks(lines: list[str]) -> list[tuple[int, str, str]]:
    """Return (start_line, resource_name, block_text) for each IAM policy resource."""
    blocks: list[tuple[int, str, str]] = []
    idx = 0
    while idx < len(lines):
        match = _RESOURCE_RE.match(lines[idx])
        if not match:
            idx += 1
            continue

        start_idx = idx
        depth = _brace_delta(lines[idx])
        idx += 1
        while idx < len(lines) and depth > 0:
            depth += _brace_delta(lines[idx])
            idx += 1

        block = "\n".join(lines[start_idx:idx])
        blocks.append((start_idx + 1, match.group(2), block))
    return blocks


def _extract_statement_blocks(block_lines: list[str]) -> list[tuple[int, str]]:
    """Return (relative_line, statement_text) for IAM statement brace blocks.

    Any block carrying an ``Action`` field is an IAM statement candidate;
    ``_statement_violations`` then decides whether it grants SSM parameter
    access. Filtering on a literal ``"ssm:`` token here would fail open on
    full-wildcard statements (``Action = "*"``).
    """
    statements: list[tuple[int, str]] = []
    idx = 0
    while idx < len(block_lines):
        if not re.match(r"^\s*\{\s*$", block_lines[idx]):
            idx += 1
            continue

        start_idx = idx
        depth = _brace_delta(block_lines[idx])
        idx += 1
        while idx < len(block_lines) and depth > 0:
            depth += _brace_delta(block_lines[idx])
            idx += 1

        statement = "\n".join(block_lines[start_idx:idx])
        if "Action" in statement:
            statements.append((start_idx + 1, statement))
    return statements


def _field_tokens(statement: str, field_re: re.Pattern[str]) -> list[str]:
    match = field_re.search(statement)
    if match is None:
        return []
    return _QUOTED_RE.findall(match.group(1))


def _action_grants_ssm_parameter(action: str) -> bool:
    action = action.lower()
    if action == "*":
        # A full wildcard action covers every SSM parameter action.
        return True
    if action in _SSM_PARAMETER_ACTIONS:
        return True
    if action == "ssm:*":
        return True
    if action.startswith("ssm:") and action.endswith("*"):
        stem = action[len("ssm:") : -1]
        return any(
            param[len("ssm:") :].startswith(stem) for param in _SSM_PARAMETER_ACTIONS
        )
    return False


def _statement_grants_ssm_parameter(actions: list[str]) -> bool:
    return any(_action_grants_ssm_parameter(action) for action in actions)


def _resource_arn_violations(path: Path, line: int, arn: str) -> list[Violation]:
    violations: list[Violation] = []
    if _ENV_WILDCARD_RE.search(arn):
        violations.append(
            Violation(
                path,
                line,
                "SSM parameter grant on the range instance role must not "
                "wildcard the environment segment "
                "(parameter/shifter/*/range/...)",
            )
        )
    segment = _RANGE_SEGMENT_RE.search(arn)
    if segment is not None:
        after_range = segment.group(1)
        bound_to_range = "range_id" in arn
        if not bound_to_range and (after_range == "" or after_range.startswith("*")):
            violations.append(
                Violation(
                    path,
                    line,
                    "SSM parameter grant on the range instance role must be "
                    "bound to a concrete range id (${var.range_id}); "
                    "parameter/shifter/<env>/range/* crosses every range",
                )
            )
    return violations


def _statement_violations(path: Path, line: int, statement: str) -> list[Violation]:
    actions = _field_tokens(statement, _ACTION_FIELD_RE)
    if not _statement_grants_ssm_parameter(actions):
        return []
    violations: list[Violation] = []
    for resource in _field_tokens(statement, _RESOURCE_FIELD_RE):
        if resource == "*":
            violations.append(
                Violation(
                    path,
                    line,
                    "SSM parameter grant on the range instance role must not "
                    "use Resource=*; it covers every environment and range",
                )
            )
            continue
        violations.extend(_resource_arn_violations(path, line, resource))
    return violations


def check_file(path: Path, role_substring: str = DEFAULT_ROLE_SUBSTRING) -> list[Violation]:
    lines = path.read_text().splitlines()
    violations: list[Violation] = []
    for block_start, _name, block in _extract_resource_blocks(lines):
        if role_substring not in block:
            continue
        block_lines = block.splitlines()
        for relative_line, statement in _extract_statement_blocks(block_lines):
            line = block_start + relative_line - 1
            violations.extend(_statement_violations(path, line, statement))
    return violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: check_tf_iam_ssm_range_scope.py FILE.tf [FILE.tf ...]",
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
            "Range-instance SSM parameter IAM scope violations "
            f"({len(violations)} total):",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
