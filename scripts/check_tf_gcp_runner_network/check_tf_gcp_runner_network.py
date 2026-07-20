#!/usr/bin/env python3
"""Lint the GCP GitHub Actions runner network Terraform for isolation (ADR-008).

Issue #1546: the GCP-native self-hosted runner must live in a dedicated,
custom-mode VPC (never the project ``default`` network) and admit SSH only from
Google's IAP relay range, so the runner is private-only and reachable for
registration through IAP alone (ADR-008-R2/R4). This is the GCP analog of
``check_tf_runner_network.py`` (ADR-004-R20, AWS): that guard is AWS-specific
(it reads ``data "aws_vpcs" "default"`` and AWS preconditions) and deliberately
does not extend to GCP.

Division of labour: Checkov (``platform/terraform/.checkov.yaml``) already flags
an external IP on the instance and world-open SSH generically. This guard adds
the runner-specific invariants Checkov does not assert -- that the network is a
dedicated custom VPC and that SSH ingress is scoped to exactly the IAP range --
so the isolation cannot be silently weakened by editing the module.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

RUNNER_NETWORK_TF = "platform/terraform/gcp/modules/github-runner-network/main.tf"

# Google's fixed IAP TCP-forwarding relay range; SSH ingress must be scoped to it.
IAP_TCP_SOURCE_RANGE = "35.235.240.0/20"

# Matched against whitespace-stripped text so formatting changes cannot defeat
# the guard. A dedicated custom-mode VPC declares google_compute_network with
# auto_create_subnetworks = false; the default network never satisfies this.
_CUSTOM_NETWORK_RE = re.compile(r'resource"google_compute_network"')
_AUTO_SUBNET_FALSE_RE = re.compile(r"auto_create_subnetworks=false")
# A firewall that ALLOWS ingress from 0.0.0.0/0 is world-open. A DENY from
# 0.0.0.0/0 is the fail-closed default and is required, so the check is scoped
# per-firewall to blocks that carry an `allow {` clause. Egress uses
# destination_ranges (a NAT egress allow to 0.0.0.0/0 is fine), so only
# source_ranges (ingress) are inspected.
_ALLOW_CLAUSE_RE = re.compile(r"allow\s*\{")
_SOURCE_WORLD_OPEN_RE = re.compile(r"source_ranges\s*=\s*\[[^\]]*0\.0\.0\.0/0")


def _firewall_blocks(text: str) -> list[str]:
    """Split the file into per-``google_compute_firewall`` chunks (heuristic)."""
    parts = re.split(r'(?=resource\s+"google_compute_firewall")', text)
    return [p for p in parts if re.match(r'\s*resource\s+"google_compute_firewall"', p)]


@dataclass
class Violation:
    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.reason}"


def check_gcp_runner_network_guard(path: Path, text: str) -> list[Violation]:
    violations: list[Violation] = []
    stripped = re.sub(r"\s+", "", text)

    if not _CUSTOM_NETWORK_RE.search(stripped):
        violations.append(
            Violation(
                path,
                1,
                'runner network module must declare a dedicated google_compute_network '
                "(the default network is prohibited) (ADR-008, #1546)",
            )
        )
    elif not _AUTO_SUBNET_FALSE_RE.search(stripped):
        violations.append(
            Violation(
                path,
                1,
                "runner google_compute_network must set auto_create_subnetworks = false "
                "(custom-mode, non-default VPC) (ADR-008, #1546)",
            )
        )

    if IAP_TCP_SOURCE_RANGE not in text:
        violations.append(
            Violation(
                path,
                1,
                f"runner SSH firewall must scope ingress to the IAP range {IAP_TCP_SOURCE_RANGE} "
                "(no public or broad-CIDR SSH) (ADR-008-R2/R4, #1546)",
            )
        )

    for block in _firewall_blocks(text):
        if _ALLOW_CLAUSE_RE.search(block) and _SOURCE_WORLD_OPEN_RE.search(block):
            violations.append(
                Violation(
                    path,
                    1,
                    "runner firewall must not ALLOW ingress from 0.0.0.0/0 (source_ranges); "
                    "SSH is IAP-only (a deny-all from 0.0.0.0/0 is the required fail-closed "
                    "default) (ADR-008-R2/R4, #1546)",
                )
            )
            break

    return violations


def check_file(path: Path) -> list[Violation]:
    if path.suffix != ".tf":
        return []
    text = path.read_text(encoding="utf-8")
    return check_gcp_runner_network_guard(path, text)


def iter_target_files(repo_root: Path, argv: list[str]) -> list[Path]:
    if argv:
        return [Path(arg).resolve() for arg in argv]
    module = repo_root / RUNNER_NETWORK_TF
    return [module] if module.exists() else []


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
