#!/usr/bin/env python3
"""Lint the GitHub Actions runner Terraform for default-VPC network isolation.

ADR-004-R20 / issue #1222: the self-hosted deploy runner must never be placed in
the account default VPC, where a range's ``private_dns_enabled`` interface VPC
endpoints can hijack the runner's AWS API resolution (the ~107-minute CI wedge
behind #1220). The runner stack enforces this with a fail-closed Terraform
``lifecycle.precondition``; this guard asserts that enforcement is present so it
cannot be silently removed.

The precondition may carry an explicit ``var.allow_default_vpc`` opt-in escape
hatch (ADR-004-R20): the guard stays fail-closed by default and only permits the
account default VPC when an operator deliberately enables it. This checker
asserts the default-VPC check and the subnet-membership check are still present
(against the resolved ``local.runner_vpc_id``); it does not object to the opt-in
prefix, which is the documented, non-silent way to accept default-VPC placement.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

RUNNER_MAIN_TF = "platform/terraform/global/github-runner/main.tf"

# The default-VPC data source the precondition reads.
DEFAULT_VPCS_DATA_RE = re.compile(r'data\s+"aws_vpcs"\s+"default"\s*\{')
# The two fail-closed preconditions, matched against whitespace-stripped text so
# formatting changes do not defeat the guard. The resolved runner VPC is
# ``local.runner_vpc_id`` (explicit var.vpc_id, else the auto-resolved default VPC
# when opted in); the historical form referenced ``var.vpc_id`` directly, so both
# are accepted:
#   1. the resolved runner VPC must not be the account default VPC, and
#   2. the runner subnet must belong to the resolved runner VPC (so a default-VPC
#      subnet cannot sneak in behind a non-default VPC).
_RUNNER_VPC_REF = r"(?:local\.runner_vpc_id|var\.vpc_id)"
DEFAULT_VPC_PRECONDITION_RE = re.compile(
    r"!contains\(data\.aws_vpcs\.default\.ids," + _RUNNER_VPC_REF + r"\)"
)
SUBNET_MEMBERSHIP_PRECONDITION_RE = re.compile(
    r"data\.aws_subnet\.runner\.vpc_id==" + _RUNNER_VPC_REF
)


@dataclass
class Violation:
    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.reason}"


def check_runner_network_guard(path: Path, text: str) -> list[Violation]:
    violations: list[Violation] = []
    stripped = re.sub(r"\s+", "", text)
    if not DEFAULT_VPCS_DATA_RE.search(text):
        violations.append(
            Violation(
                path,
                1,
                'runner stack must declare data "aws_vpcs" "default" to resolve '
                "the account default VPC for the network-isolation guard "
                "(ADR-004-R20, #1222)",
            )
        )
    if not DEFAULT_VPC_PRECONDITION_RE.search(stripped):
        violations.append(
            Violation(
                path,
                1,
                "runner stack must fail closed on default-VPC placement via a "
                "precondition asserting "
                "!contains(data.aws_vpcs.default.ids, var.vpc_id) "
                "(ADR-004-R20, #1222)",
            )
        )
    if not SUBNET_MEMBERSHIP_PRECONDITION_RE.search(stripped):
        violations.append(
            Violation(
                path,
                1,
                "runner stack must fail closed when the subnet does not belong "
                "to var.vpc_id via a precondition asserting "
                "data.aws_subnet.runner.vpc_id == var.vpc_id (ADR-004-R20, #1222)",
            )
        )
    return violations


def check_file(path: Path) -> list[Violation]:
    if path.suffix != ".tf":
        return []
    text = path.read_text(encoding="utf-8")
    return check_runner_network_guard(path, text)


def iter_target_files(repo_root: Path, argv: list[str]) -> list[Path]:
    if argv:
        return [Path(arg).resolve() for arg in argv]
    runner = repo_root / RUNNER_MAIN_TF
    return [runner] if runner.exists() else []


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    repo_root = Path(__file__).resolve().parents[2]
    violations: list[Violation] = []
    for path in iter_target_files(repo_root, args):
        if not path.is_file():
            continue
        violations.extend(check_file(path))
    if violations:
        for violation in violations:
            print(violation)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
