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
    - `var.portal_vpc_cidr` is a generally trusted control-plane source.
      The ADR-039-R10 public VPN source is allowed only on the audited
      `range/vpn.tf` `vpn_nlb` UDP/1194 ingress tuple.
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
_VPN_PUBLIC_CLIENT_REF = "var.vpn_public_client_cidr"
_VPN_EXCEPTION_PATH = "shifter/engine/provisioner/terraform/modules/range/vpn.tf"

MAX_LITERAL_PREFIX_FOR_INGRESS = 24

_RESOURCE_RE = re.compile(
    r'^\s*resource\s+"(aws_security_group(?:_rule)?)"\s+"([^"]+)"\s*\{'
)
_INGRESS_BLOCK_RE = re.compile(r"^\s*ingress\s*\{")
_TYPE_INGRESS_RE = re.compile(r'^\s*type\s*=\s*"ingress"\s*$')
_CIDR_BLOCKS_RE = re.compile(r"^\s*cidr_blocks\s*=\s*\[(?P<items>[^\]]*)\]")
_INGRESS_ATTRIBUTE_RE = re.compile(r'^\s*(from_port|to_port|protocol)\s*=\s*"?([^"\s]+)"?\s*$')


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


def _check_cidr(value: str, *, allow_public_vpn: bool = False) -> str | None:
    """Return None if the value is acceptable, else a reason string."""
    if value in ALLOWED_VAR_REFS:
        return None
    if value == _VPN_PUBLIC_CLIENT_REF and allow_public_vpn:
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


def _collect_cidr_violations_on_line(
    path: Path,
    idx: int,
    raw: str,
    *,
    allow_public_vpn: bool = False,
) -> list[Violation]:
    """Return any CIDR-block violations found on a single ingress line."""
    out: list[Violation] = []
    m = _CIDR_BLOCKS_RE.match(raw)
    if not m:
        return out
    for item in _parse_cidr_block_items(m.group("items")):
        reason = _check_cidr(item, allow_public_vpn=allow_public_vpn)
        if reason is not None:
            out.append(Violation(path, idx, item, reason))
    return out


class _ParserState:
    """Mutable per-file scan state for `check_file`'s line walker."""

    def __init__(self) -> None:
        self.in_resource: str | None = None
        self.resource_name: str | None = None
        self.resource_brace_depth = 0
        self.in_inline_ingress_block = False
        self.ingress_brace_depth = 0
        self.is_security_group_rule_ingress = False
        self.inline_ingress_attributes: dict[str, str] = {}
        self.inline_ingress_cidrs: list[tuple[int, str]] = []

    def reset_resource(self) -> None:
        self.in_resource = None
        self.resource_name = None
        self.in_inline_ingress_block = False
        self.is_security_group_rule_ingress = False
        self.inline_ingress_attributes = {}
        self.inline_ingress_cidrs = []


def _enter_resource_if_match(state: _ParserState, raw: str) -> bool:
    """If `raw` opens a new resource block, record it. Return True iff so."""
    m = _RESOURCE_RE.match(raw)
    if not m:
        return False
    state.in_resource = m.group(1)
    state.resource_name = m.group(2)
    state.resource_brace_depth = raw.count("{") - raw.count("}")
    state.is_security_group_rule_ingress = False
    return True


def _vpn_tuple_is_audited(path: Path, state: _ParserState) -> bool:
    """Return whether the current inline rule is the exact ADR-039-R10 edge."""
    attrs = state.inline_ingress_attributes
    return (
        path.as_posix().endswith(_VPN_EXCEPTION_PATH)
        and state.in_resource == "aws_security_group"
        and state.resource_name == "vpn_nlb"
        and attrs.get("protocol") == "udp"
        and attrs.get("from_port") == "1194"
        and attrs.get("to_port") == "1194"
    )


def _flush_inline_ingress(path: Path, state: _ParserState) -> list[Violation]:
    """Evaluate CIDRs after the whole inline rule tuple has been observed."""
    allow_public_vpn = _vpn_tuple_is_audited(path, state)
    violations: list[Violation] = []
    for line, value in state.inline_ingress_cidrs:
        reason = _check_cidr(value, allow_public_vpn=allow_public_vpn)
        if reason is not None:
            violations.append(Violation(path, line, value, reason))
    state.inline_ingress_attributes = {}
    state.inline_ingress_cidrs = []
    return violations


def check_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    text = path.read_text()
    state = _ParserState()

    for idx, raw in enumerate(text.splitlines(), start=1):
        if state.in_resource is None:
            _enter_resource_if_match(state, raw)
            continue

        state.resource_brace_depth += raw.count("{") - raw.count("}")
        if state.resource_brace_depth <= 0:
            state.reset_resource()
            continue

        if state.in_resource == "aws_security_group_rule":
            if _TYPE_INGRESS_RE.match(raw):
                state.is_security_group_rule_ingress = True
            if state.is_security_group_rule_ingress:
                violations.extend(_collect_cidr_violations_on_line(path, idx, raw))
            continue

        # aws_security_group: only check inside `ingress { ... }` inline blocks.
        if not state.in_inline_ingress_block and _INGRESS_BLOCK_RE.match(raw):
            state.in_inline_ingress_block = True
            state.ingress_brace_depth = raw.count("{") - raw.count("}")
            state.inline_ingress_attributes = {}
            state.inline_ingress_cidrs = []
            continue

        if state.in_inline_ingress_block:
            state.ingress_brace_depth += raw.count("{") - raw.count("}")
            attribute = _INGRESS_ATTRIBUTE_RE.match(raw)
            if attribute:
                state.inline_ingress_attributes[attribute.group(1)] = attribute.group(2)
            cidrs = _CIDR_BLOCKS_RE.match(raw)
            if cidrs:
                state.inline_ingress_cidrs.extend(
                    (idx, item) for item in _parse_cidr_block_items(cidrs.group("items"))
                )
            if state.ingress_brace_depth <= 0:
                violations.extend(_flush_inline_ingress(path, state))
                state.in_inline_ingress_block = False

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
