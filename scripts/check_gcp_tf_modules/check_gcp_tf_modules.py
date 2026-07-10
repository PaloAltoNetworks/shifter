#!/usr/bin/env python3
"""Verify GCP platform-core Terraform decomposition layout.

Ensures required submodule directories exist and that
platform/terraform/gcp/modules/platform-core/main.tf is a composition
facade: module blocks plus VPC peering only (no other direct google_*
resources).

Usage:

    python3 scripts/check_gcp_tf_modules/check_gcp_tf_modules.py

Exit code 0 when layout and facade contract pass, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GCP_MODULES = REPO_ROOT / "platform" / "terraform" / "gcp" / "modules"
PLATFORM_CORE_MAIN = GCP_MODULES / "platform-core" / "main.tf"

REQUIRED_SUBMODULE_DIRS = [
    "project-services",
    "portal/vpc",
    "range/vpc",
    "portal/artifact-registry",
    "portal/gcs",
    "portal/ingress",
    "portal/messaging",
    "portal/identity-platform",
    "portal/cloud-sql",
    "portal/redis",
    "portal/secrets",
    "portal/gke",
    "portal/iam",
]

REQUIRED_MODULE_SOURCES = [
    "../project-services",
    "../portal/vpc",
    "../range/vpc",
    "../portal/gcs",
    "../portal/artifact-registry",
    "../portal/ingress",
    "../portal/messaging",
    "../portal/identity-platform",
    "../portal/cloud-sql",
    "../portal/redis",
    "../portal/secrets",
    "../portal/iam",
    "../portal/gke",
]

_MODULE_BLOCK_RE = re.compile(r'^\s*module\s+"[^"]+"\s*\{', re.MULTILINE)
_RESOURCE_RE = re.compile(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', re.MULTILINE)

ALLOWED_DIRECT_RESOURCES = {
    ("google_compute_network_peering", "platform_to_range"),
    ("google_compute_network_peering", "range_to_platform"),
}


@dataclass
class Violation:
    message: str

    def __str__(self) -> str:
        return self.message


def check_required_submodule_dirs() -> list[Violation]:
    violations: list[Violation] = []
    for rel in REQUIRED_SUBMODULE_DIRS:
        path = GCP_MODULES / rel
        if not path.is_dir():
            violations.append(Violation(f"missing required submodule directory: {path}"))
        elif not (path / "main.tf").is_file():
            violations.append(Violation(f"missing main.tf in submodule: {path}"))
    return violations


def check_platform_core_facade() -> list[Violation]:
    violations: list[Violation] = []
    if not PLATFORM_CORE_MAIN.is_file():
        return [Violation(f"missing platform-core facade: {PLATFORM_CORE_MAIN}")]

    text = PLATFORM_CORE_MAIN.read_text()

    if not _MODULE_BLOCK_RE.search(text):
        violations.append(
            Violation(f"{PLATFORM_CORE_MAIN}: expected at least one module block")
        )

    for source in REQUIRED_MODULE_SOURCES:
        if f'source = "{source}"' not in text:
            violations.append(
                Violation(
                    f"{PLATFORM_CORE_MAIN}: missing module block with source = {source!r}"
                )
            )

    for match in _RESOURCE_RE.finditer(text):
        resource_type = match.group(1)
        resource_name = match.group(2)
        if (resource_type, resource_name) not in ALLOWED_DIRECT_RESOURCES:
            violations.append(
                Violation(
                    f"{PLATFORM_CORE_MAIN}: disallowed direct resource "
                    f"{resource_type}.{resource_name}; move it into a submodule"
                )
            )

    return violations


def check_gcp_tf_modules() -> list[Violation]:
    violations: list[Violation] = []
    violations.extend(check_required_submodule_dirs())
    violations.extend(check_platform_core_facade())
    return violations


def main() -> int:
    violations = check_gcp_tf_modules()
    if violations:
        print(f"GCP Terraform module layout violations ({len(violations)} total):", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
