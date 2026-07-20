#!/usr/bin/env python3
"""Ensure Checkov Terraform invocation parity between pre-commit and CI.

ADR-004-R11 requires one canonical policy at platform/terraform/.checkov.yaml
and blocking (non-soft-fail) execution. Issue #147: inline module skips only
apply when Checkov loads module sources; CI already sets
download_external_modules while pre-commit must match.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

EXPECTED_CONFIG = "platform/terraform/.checkov.yaml"
EXPECTED_DIRECTORY = "platform/terraform/"


def _parse_precommit_checkov_args(precommit_text: str) -> list[str]:
    """Return flattened checkov hook args from .pre-commit-config.yaml."""
    in_checkov_hook = False
    in_args = False
    args: list[str] = []

    for line in precommit_text.splitlines():
        stripped = line.strip()
        if re.match(r"-\s+id:\s+checkov\s*$", stripped):
            in_checkov_hook = True
            in_args = False
            continue
        if not in_checkov_hook:
            continue
        if re.match(r"-\s+id:\s+", stripped):
            break
        if stripped.startswith("args:"):
            in_args = True
            bracket = stripped.split("[", 1)
            if len(bracket) == 2 and bracket[1].strip().endswith("]"):
                inner = bracket[1].rsplit("]", 1)[0]
                args.extend(_split_args(inner))
                in_args = False
            continue
        if in_args:
            if stripped.startswith("[") and stripped.endswith("]"):
                args.extend(_split_args(stripped[1:-1]))
                in_args = False
            elif stripped.endswith("]"):
                args.extend(_split_args(stripped.rstrip("]")))
                in_args = False

    return args


def _split_args(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _precommit_download_external_modules(args: list[str]) -> bool:
    for idx, token in enumerate(args):
        if token in ("--download-external-modules", "download-external-modules"):
            if idx + 1 < len(args) and args[idx + 1].lower() == "false":
                return False
            return True
    return False


def _precommit_soft_fail_enabled(args: list[str]) -> bool:
    for idx, token in enumerate(args):
        if token in ("--soft-fail", "soft-fail", "--soft_fail", "soft_fail"):
            if idx + 1 >= len(args):
                return True
            value = args[idx + 1].lower()
            if value in ("false", "0", "no"):
                return False
            return True
    return False


def _parse_ci_checkov_step(workflow_text: str) -> dict[str, str]:
    """Parse the security-iac Checkov action inputs from _quality.yml."""
    lines = workflow_text.splitlines()
    in_security_iac = False
    in_checkov_step = False
    inputs: dict[str, str] = {}

    for line in lines:
        if re.match(r"^  security-iac:\s*$", line):
            in_security_iac = True
            in_checkov_step = False
            continue
        if in_security_iac and re.match(r"^  [a-z][\w-]*:\s*$", line):
            if not line.strip().startswith("security-iac"):
                in_security_iac = False
                in_checkov_step = False
        if not in_security_iac:
            continue
        if "Checkov IaC Security" in line:
            in_checkov_step = True
            continue
        if in_checkov_step and line.strip().startswith("- name:") and "Checkov IaC Security" not in line:
            in_checkov_step = False
        if not in_checkov_step:
            continue
        match = re.match(r"\s+(\w+):\s*(.+)\s*$", line)
        if match:
            inputs[match.group(1)] = match.group(2).strip()

    return inputs


def check_repo(repo_root: Path) -> list[str]:
    violations: list[str] = []

    precommit_path = repo_root / ".pre-commit-config.yaml"
    workflow_path = repo_root / ".github" / "workflows" / "_quality.yml"

    if not precommit_path.is_file():
        return ["missing .pre-commit-config.yaml"]
    if not workflow_path.is_file():
        return ["missing .github/workflows/_quality.yml"]

    precommit_args = _parse_precommit_checkov_args(precommit_path.read_text(encoding="utf-8"))
    ci_inputs = _parse_ci_checkov_step(workflow_path.read_text(encoding="utf-8"))

    config_tokens = [t for t in precommit_args if "checkov.yaml" in t]
    if EXPECTED_CONFIG not in config_tokens:
        violations.append(
            f"pre-commit checkov must use config-file {EXPECTED_CONFIG!r}, got args {precommit_args!r}"
        )

    directory_tokens = [t for t in precommit_args if t.endswith("platform/terraform/")]
    if EXPECTED_DIRECTORY not in directory_tokens:
        violations.append(
            f"pre-commit checkov must scan directory {EXPECTED_DIRECTORY!r}, got args {precommit_args!r}"
        )

    if not _precommit_download_external_modules(precommit_args):
        violations.append(
            "pre-commit checkov args must include --download-external-modules "
            "(issue #147 / ADR-004-R11 CI parity)"
        )

    if _precommit_soft_fail_enabled(precommit_args):
        violations.append(
            "pre-commit checkov args must not include --soft-fail "
            "(ADR-004-R11 blocking gate; parity with CI soft_fail: false)"
        )

    if ci_inputs.get("config_file") != EXPECTED_CONFIG:
        violations.append(
            f"CI Checkov config_file must be {EXPECTED_CONFIG!r}, got {ci_inputs.get('config_file')!r}"
        )
    if ci_inputs.get("directory") != EXPECTED_DIRECTORY:
        violations.append(
            f"CI Checkov directory must be {EXPECTED_DIRECTORY!r}, got {ci_inputs.get('directory')!r}"
        )
    if ci_inputs.get("download_external_modules") != "true":
        violations.append(
            "CI Checkov download_external_modules must be true "
            f"(got {ci_inputs.get('download_external_modules')!r})"
        )
    if ci_inputs.get("soft_fail") != "false":
        violations.append(
            f"CI Checkov soft_fail must be false (got {ci_inputs.get('soft_fail')!r})"
        )

    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    violations = check_repo(repo_root)
    if violations:
        for item in violations:
            print(item)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
