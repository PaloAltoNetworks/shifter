#!/usr/bin/env python3
"""Lint the ingress sources of the portal target-service security groups.

Closes the #911 NET-2 / #933 segmentation regression: the portal east-west
inspection path routes ALB->target traffic through an AWS Network Firewall
endpoint, and AWS documents that security-group *referencing* does not work
through a routed middlebox (the flow is split into source->middlebox and
middlebox->destination, so the destination's SG-reference resolution fails):

    https://aws.amazon.com/blogs/networking-and-content-delivery/deployment-models-for-aws-network-firewall-with-vpc-routing-enhancements/
    https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html#security-group-referencing

The documented workaround is CIDR-based ingress. The original fix
(`Fix ALB inspection target ingress`) scoped that CIDR to the whole
`module.vpc.public_subnet_cidrs`, where the standalone CTFd instance and the
NAT also live, so CTFd gained direct L4 reach to Django:8000 and the
Guacamole token API:8080, bypassing the ALB/WAF/`/admin` deny.

This checker enforces the durable invariant that fixes that:

    Every `aws_security_group_rule` ingress whose `security_group_id` is a
    portal target-service SG (the Django EC2 SG or the Guacamole client SG)
    MUST source either from a security-group reference
    (`source_security_group_id`, the preferred posture on the
    inspection-off path) OR from the ALB-only subnet CIDR contract
    (`module.vpc.alb_ingress_subnet_cidrs`).

    The whole-public-tier output (`module.vpc.public_subnet_cidrs`), the
    CTFd public-workload tier (`module.vpc.public_workload_subnet_cidrs`),
    or any other CIDR source is rejected, because those tiers contain (or
    may contain) workloads other than the ALB.

Scope:
    - aws_security_group_rule { type = "ingress" security_group_id = <target> }
      where <target> is one of TARGET_SG_REFS.
    - Other security groups (range modules, internal portal module rules,
      Redis/RDS, etc.) are out of scope here; range/provisioner SGs are
      owned by scripts/check_tf_sg_cidrs.

Usage:

    python3 scripts/check_portal_target_sg_sources/check_portal_target_sg_sources.py FILE.tf [FILE.tf ...]

Exit code 0 if every file passes, 1 if any rule is violated. Designed to run
from the pre-commit framework, which passes the changed file paths as
positional arguments.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Env-root references to the portal target-service security groups whose L4
# allow list is the failing-or-passing control for CTFd reachability.
TARGET_SG_REFS: set[str] = {
    "module.ec2.security_group_id",
    "module.guacamole.guacamole_client_security_group_id",
}

# The only CIDR source a portal target SG may admit. This is the ALB-only
# subnet contract exposed by the portal VPC module; it deliberately excludes
# the CTFd public-workload tier.
ALLOWED_CIDR_SOURCES: set[str] = {
    "module.vpc.alb_ingress_subnet_cidrs",
}

_RESOURCE_RE = re.compile(r'^\s*resource\s+"aws_security_group_rule"\s+"([^"]+)"\s*\{')
# These match against the whole (multi-line) resource block with re.MULTILINE.
_TYPE_INGRESS_RE = re.compile(r'^\s*type\s*=\s*"ingress"\s*$', re.MULTILINE)
_SECURITY_GROUP_ID_RE = re.compile(r"^\s*security_group_id\s*=\s*(?P<val>.+?)\s*$", re.MULTILINE)
_SOURCE_SG_RE = re.compile(r"^\s*source_security_group_id\s*=", re.MULTILINE)
# Matches `cidr_blocks =` and consumes trailing whitespace (incl. newlines)
# so the right-hand side starts at the next non-space character.
_CIDR_BLOCKS_RHS_RE = re.compile(r"cidr_blocks\s*=\s*")


@dataclass
class Violation:
    file: Path
    rule_name: str
    source: str
    reason: str

    def __str__(self) -> str:
        return f"{self.file}: {self.rule_name}: {self.source}: {self.reason}"


def _parse_cidr_sources(raw: str) -> list[str]:
    """Split the inside of a `cidr_blocks` right-hand side into sources.

    Items may be comma- and/or newline-separated (multiline lists), quoted
    CIDR literals, or unquoted references. Trailing inline comments are
    stripped.
    """
    sources: list[str] = []
    for part in re.split(r"[,\n]", raw):
        part = part.split("#", 1)[0].strip().strip('"').strip()
        if part:
            sources.append(part)
    return sources


def _extract_cidr_sources(text: str) -> tuple[bool, list[str] | None]:
    """Return (cidr_blocks_present, sources).

    Handles a bracketed list (single- or multi-line) and a bare list-typed
    reference. `sources` is None when `cidr_blocks` is present but cannot be
    parsed (e.g. an unclosed bracket or an empty right-hand side) — the
    caller fails closed in that case rather than silently passing.
    """
    m = _CIDR_BLOCKS_RHS_RE.search(text)
    if not m:
        return (False, [])
    rest = text[m.end() :]
    if rest.startswith("["):
        close = rest.find("]")
        if close == -1:
            return (True, None)  # unclosed bracket -> unparseable
        return (True, _parse_cidr_sources(rest[1:close]))
    line = rest.split("\n", 1)[0].strip()
    if not line:
        return (True, None)  # nothing after `cidr_blocks =` -> unparseable
    return (True, _parse_cidr_sources(line))


_REASON = (
    "portal target-service SG ingress must source from a security-group "
    "reference or module.vpc.alb_ingress_subnet_cidrs (the ALB-only contract); "
    "this source admits workloads other than the ALB (e.g. CTFd) directly to "
    "8000/8080"
)


def _check_block(path: Path, rule_name: str, lines: list[str]) -> list[Violation]:
    """Evaluate a single aws_security_group_rule block."""
    text = "\n".join(lines)

    if not _TYPE_INGRESS_RE.search(text):
        return []
    sg_match = _SECURITY_GROUP_ID_RE.search(text)
    target_sg = sg_match.group("val").strip() if sg_match else None
    if target_sg not in TARGET_SG_REFS:
        return []
    # SG-to-SG referencing is always acceptable (the inspection-off path).
    if _SOURCE_SG_RE.search(text):
        return []

    present, sources = _extract_cidr_sources(text)
    if not present:
        return []
    # Fail closed: a target-service ingress with an unparseable cidr_blocks
    # must not pass silently — that is exactly how a widening would hide.
    if sources is None:
        return [Violation(path, rule_name, "<unparseable cidr_blocks>", _REASON)]

    return [
        Violation(path, rule_name, source, _REASON)
        for source in sources
        if source not in ALLOWED_CIDR_SOURCES
    ]


def check_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    lines = path.read_text().splitlines()

    rule_name: str | None = None
    block: list[str] = []
    depth = 0

    for raw in lines:
        if rule_name is None:
            m = _RESOURCE_RE.match(raw)
            if m:
                rule_name = m.group(1)
                block = []
                depth = raw.count("{") - raw.count("}")
            continue

        depth += raw.count("{") - raw.count("}")
        if depth <= 0:
            violations.extend(_check_block(path, rule_name, block))
            rule_name = None
            block = []
            continue
        block.append(raw)

    return violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: check_portal_target_sg_sources.py FILE.tf [FILE.tf ...]",
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
            "Portal target-service SG ingress source violations "
            f"({len(all_violations)} total):",
            file=sys.stderr,
        )
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nFix: source Django (module.ec2) and Guacamole client "
            "(module.guacamole) ingress from a security-group reference or "
            "module.vpc.alb_ingress_subnet_cidrs. Do not use the whole public "
            "tier or the CTFd public-workload tier as a target-service ingress "
            "source (see #933).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
