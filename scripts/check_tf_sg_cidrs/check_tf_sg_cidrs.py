#!/usr/bin/env python3
"""Lint AWS security group ingress CIDR blocks in Terraform files.

Catches the failure mode that produced the polaris cross-range leak in
v3.93.x: a "shared SG" with `cidr_blocks = ["10.1.0.0/16"]` ingress let
range 1's kali container reach range 0's domain controller at L3, even
though each range was supposed to be isolated to its own /28 subnet.

Rules enforced (per file, per ingress rule, per CIDR):

    - Literal `0.0.0.0/0` in an ingress rule is rejected. Range/lab
      networks must not have public ingress.
    - Literal CIDRs broader than /24 (prefix < 24) are rejected for
      ingress. /24 or narrower is allowed; per-range deployments should
      be using a /28 anyway.
    - References to known-good variables (currently
      `var.portal_vpc_cidr`) are allowed regardless of the underlying
      CIDR width — the portal VPC is the only intentional broad source.
      Add new entries to ALLOWED_VAR_REFS below if a future trusted
      source needs the same exemption.
    - Egress rules are not checked. Egress 0.0.0.0/0 is the standard
      pattern for outbound NAT.

Scope:
    - aws_security_group { ingress { cidr_blocks = [...] } }
    - aws_security_group_rule { type = "ingress" cidr_blocks = [...] }

Usage:

    python3 scripts/check_tf_sg_cidrs/check_tf_sg_cidrs.py FILE.tf [FILE.tf ...]

Exit code 0 if every file passes, 1 if any rule is violated.
Designed to run from the pre-commit framework — pre-commit passes the
changed file paths as positional arguments.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from ipaddress import ip_network
from pathlib import Path

ALLOWED_VAR_REFS: set[str] = {
    "var.portal_vpc_cidr",
}

MAX_LITERAL_PREFIX_FOR_INGRESS = 24

_RESOURCE_RE = re.compile(
    r'^\s*resource\s+"(aws_security_group(?:_rule)?)"\s+"([^"]+)"\s*\{'
)
_INGRESS_BLOCK_RE = re.compile(r"^\s*ingress\s*\{")
_TYPE_INGRESS_RE = re.compile(r'^\s*type\s*=\s*"ingress"\s*$')
_CIDR_BLOCKS_RE = re.compile(r"^\s*cidr_blocks\s*=\s*\[(?P<items>[^\]]*)\]")


@dataclass
class Violation:
    file: Path
    line: int
    cidr: str
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.cidr}: {self.reason}"


def _parse_cidr_block_items(raw: str) -> list[str]:
    """Pull each comma-separated entry out of `cidr_blocks = [...]`.

    Items can be quoted CIDR literals or unquoted variable references.
    """
    items: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        items.append(part.strip('"'))
    return items


def _check_cidr(value: str) -> str | None:
    """Return None if the value is acceptable, else a reason string."""
    if value in ALLOWED_VAR_REFS:
        return None
    # Per-range scoped expressions: `each.value.cidr`, `each.key`, etc.
    # These are evaluated inside a for_each block so each iteration gets
    # a different value — the right thing for per-range isolation.
    if value.startswith("each."):
        return None
    # `local.X` references live in main.tf and are reviewed there. Trust
    # them so a refactor that hoists CIDR plumbing into a local doesn't
    # break the lint.
    if value.startswith("local."):
        return None
    if value.startswith("var."):
        return (
            f"unknown variable reference; add {value!r} to "
            "ALLOWED_VAR_REFS only after auditing what it expands to"
        )
    if value == "0.0.0.0/0":
        return "ingress from 0.0.0.0/0 is forbidden on lab/range networks"
    try:
        net = ip_network(value, strict=False)
    except ValueError as exc:
        return f"unparsable CIDR literal: {exc}"
    if net.prefixlen < MAX_LITERAL_PREFIX_FOR_INGRESS:
        return (
            f"CIDR /{net.prefixlen} is broader than /"
            f"{MAX_LITERAL_PREFIX_FOR_INGRESS}; scope ingress to a "
            "single subnet (use each.value.cidr or a per-range literal)"
        )
    return None


def check_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    text = path.read_text()
    lines = text.splitlines()

    in_resource: str | None = None
    resource_brace_depth = 0

    in_ingress = False
    ingress_brace_depth = 0
    in_inline_ingress_block = False
    is_security_group_rule_ingress = False

    for idx, raw in enumerate(lines, start=1):
        if in_resource is None:
            m = _RESOURCE_RE.match(raw)
            if m:
                in_resource = m.group(1)
                resource_brace_depth = raw.count("{") - raw.count("}")
                in_ingress = False
                is_security_group_rule_ingress = False
            continue

        resource_brace_depth += raw.count("{") - raw.count("}")
        if resource_brace_depth <= 0:
            in_resource = None
            in_ingress = False
            in_inline_ingress_block = False
            is_security_group_rule_ingress = False
            continue

        if in_resource == "aws_security_group_rule":
            if _TYPE_INGRESS_RE.match(raw):
                is_security_group_rule_ingress = True
            if is_security_group_rule_ingress:
                m = _CIDR_BLOCKS_RE.match(raw)
                if m:
                    for item in _parse_cidr_block_items(m.group("items")):
                        reason = _check_cidr(item)
                        if reason is not None:
                            violations.append(
                                Violation(path, idx, item, reason)
                            )
            continue

        # aws_security_group: only check inside `ingress { ... }` inline blocks.
        if not in_inline_ingress_block and _INGRESS_BLOCK_RE.match(raw):
            in_inline_ingress_block = True
            ingress_brace_depth = raw.count("{") - raw.count("}")
            continue

        if in_inline_ingress_block:
            ingress_brace_depth += raw.count("{") - raw.count("}")
            m = _CIDR_BLOCKS_RE.match(raw)
            if m:
                for item in _parse_cidr_block_items(m.group("items")):
                    reason = _check_cidr(item)
                    if reason is not None:
                        violations.append(Violation(path, idx, item, reason))
            if ingress_brace_depth <= 0:
                in_inline_ingress_block = False

    return violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: check_tf_sg_cidrs.py FILE.tf [FILE.tf ...]",
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
            "Security group ingress CIDR violations "
            f"({len(all_violations)} total):",
            file=sys.stderr,
        )
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nFix: scope ingress to per-range CIDRs "
            "(use each.value.cidr inside a for_each module) or add "
            "the variable to ALLOWED_VAR_REFS in this script after "
            "auditing it.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
