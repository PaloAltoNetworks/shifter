#!/usr/bin/env python3
"""Lint RDS instance IAM auth and CA certificate settings in Terraform.

This complements Checkov for the two first-party RDS instances under
`platform/terraform`: Checkov enforces IAM database authentication, while
its current modern-CA check passes when `ca_cert_identifier` is absent.

Rules enforced for every `aws_db_instance` resource in the supplied files:

    - `iam_database_authentication_enabled` must be the literal `true`.
    - `ca_cert_identifier` must be explicitly set to a non-empty,
      non-null expression.

Usage:

    python3 scripts/check_tf_rds_security/check_tf_rds_security.py FILE.tf [FILE.tf ...]

Exit code 0 if every file passes, 1 if any RDS instance violates a rule.
Designed to run from pre-commit and CI against the portal and Guacamole
RDS module files.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

_DB_INSTANCE_RE = re.compile(r'^\s*resource\s+"aws_db_instance"\s+"([^"]+)"\s*\{')
_ASSIGNMENT_RE = re.compile(r"^\s*(?P<key>[A-Za-z0-9_]+)\s*=\s*(?P<value>.+?)\s*$")


@dataclass
class Violation:
    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.reason}"


@dataclass
class _ResourceBlock:
    name: str
    start_line: int
    text: str


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _strip_inline_comment(value: str) -> str:
    """Remove simple Terraform inline comments from an assignment value."""
    for marker in (" #", " //"):
        index = value.find(marker)
        if index != -1:
            value = value[:index]
    return value.strip()


def _extract_db_instance_blocks(path: Path) -> list[_ResourceBlock]:
    lines = path.read_text().splitlines()
    blocks: list[_ResourceBlock] = []
    idx = 0

    while idx < len(lines):
        match = _DB_INSTANCE_RE.match(lines[idx])
        if not match:
            idx += 1
            continue

        name = match.group(1)
        start_line = idx + 1
        depth = _brace_delta(lines[idx])
        block_lines = [lines[idx]]
        idx += 1
        while idx < len(lines) and depth > 0:
            depth += _brace_delta(lines[idx])
            block_lines.append(lines[idx])
            idx += 1
        blocks.append(_ResourceBlock(name, start_line, "\n".join(block_lines)))

    return blocks


def _top_level_assignments(block: _ResourceBlock) -> dict[str, tuple[int, str]]:
    assignments: dict[str, tuple[int, str]] = {}
    depth = 0

    for offset, raw in enumerate(block.text.splitlines(), start=0):
        if offset == 0:
            depth += _brace_delta(raw)
            continue

        if depth == 1:
            match = _ASSIGNMENT_RE.match(raw)
            if match:
                assignments[match.group("key")] = (
                    block.start_line + offset,
                    _strip_inline_comment(match.group("value")),
                )

        depth += _brace_delta(raw)

    return assignments


def _check_block(path: Path, block: _ResourceBlock) -> list[Violation]:
    assignments = _top_level_assignments(block)
    violations: list[Violation] = []

    iam_auth = assignments.get("iam_database_authentication_enabled")
    if iam_auth is None:
        violations.append(
            Violation(
                path,
                block.start_line,
                "missing iam_database_authentication_enabled = true",
            )
        )
    elif iam_auth[1] != "true":
        violations.append(
            Violation(
                path,
                iam_auth[0],
                "iam_database_authentication_enabled must be literal true",
            )
        )

    ca_cert = assignments.get("ca_cert_identifier")
    if ca_cert is None:
        violations.append(Violation(path, block.start_line, "missing ca_cert_identifier"))
    elif ca_cert[1] in {'""', "null"}:
        violations.append(
            Violation(path, ca_cert[0], "ca_cert_identifier must not be empty or null")
        )

    return violations


def check_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    for block in _extract_db_instance_blocks(path):
        violations.extend(_check_block(path, block))
    return violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: check_tf_rds_security.py FILE.tf [FILE.tf ...]",
            file=sys.stderr,
        )
        return 2

    all_violations: list[Violation] = []
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"{path}: file not found", file=sys.stderr)
            return 2
        if path.suffix != ".tf":
            continue
        all_violations.extend(check_file(path))

    if all_violations:
        print(
            "RDS instance security violations "
            f"({len(all_violations)} total):",
            file=sys.stderr,
        )
        for violation in all_violations:
            print(f"  {violation}", file=sys.stderr)
        print(
            "\nFix: set iam_database_authentication_enabled = true and "
            "ca_cert_identifier to an explicit non-empty CA identifier "
            "expression on every aws_db_instance.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
