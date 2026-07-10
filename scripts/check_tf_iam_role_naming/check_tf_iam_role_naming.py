#!/usr/bin/env python3
"""Lint IAM role and instance profile naming in Terraform modules.

Deploy-managed IAM resources must use the iam_name_prefix seam so role names
land in the shifter-* namespace without renaming unrelated infrastructure.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

IAM_MODULE_GLOBS: tuple[str, ...] = (
    "platform/terraform/modules/portal/ec2/*.tf",
    "platform/terraform/modules/portal/vpc/*.tf",
    "platform/terraform/modules/portal/cognito/*.tf",
    "platform/terraform/modules/portal/rds/*.tf",
    "platform/terraform/modules/portal/ctfd/*.tf",
    "platform/terraform/modules/range/vpc/*.tf",
    "platform/terraform/modules/engine-provisioner/*.tf",
    "platform/terraform/modules/guacamole/*.tf",
    "platform/terraform/modules/log-aggregation/*.tf",
)

IAM_RESOURCE_RE = re.compile(
    r'^\s*resource\s+"(aws_iam_role|aws_iam_instance_profile)"\s+"([^"]+)"\s*\{'
)
NAME_ATTR_RE = re.compile(r'^\s*name\s*=\s*(.+)$')
LEGACY_PREFIX_RE = re.compile(r"\$\{var\.name_prefix\}")
IAM_PREFIX_OK_RE = re.compile(r"iam_name_prefix")
LEGACY_OIDC_PATTERN_RE = re.compile(
    r"role/(dev-portal-\*|prod-portal-\*|dev-range-\*|prod-range-\*)"
)
ATTACH_ALLOWLIST_POLICIES: tuple[str, ...] = (
    "AmazonSSMManagedInstanceCore",
    "AmazonECSTaskExecutionRolePolicy",
    "AWSLambdaBasicExecutionRole",
    "AmazonRDSEnhancedMonitoringRole",
)
ATTACHMENT_RESOURCE_RE = re.compile(
    r'^\s*resource\s+"aws_iam_role_policy_attachment"\s+"([^"]+)"\s*\{'
)
# AWS caps a role at 10 managed-policy attachments. Consolidating the OIDC
# deploy role by AWS category (#254) keeps it well under that hard limit with
# headroom for future domains. The cap fails the build before the role drifts
# back toward the limit; adding a service should extend an existing category
# policy, not a new attachment.
OIDC_ATTACHMENT_CAP = 6

IAM_POLICY_RESOURCE_RE = re.compile(r'^\s*resource\s+"aws_iam_policy"\s+"([^"]+)"\s*\{')
# AWS caps a customer-managed policy document at 6,144 characters (whitespace
# excluded). The OIDC deploy role consolidates many AWS services into 5 category
# policies (#254), so a category can grow toward that ceiling as services are
# added. This guard fails the build before a category exceeds the limit and the
# deploy hits LimitExceeded at apply time. It measures the whitespace-stripped
# HCL of each policy block, which is a conservative over-estimate of the rendered
# JSON because the `${...account_id}`/`${...aws_region}` interpolations are
# longer than the values they render to.
OIDC_POLICY_DOC_LIMIT = 6144


@dataclass
class Violation:
    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.reason}"


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _extract_resource_block(lines: list[str], start_idx: int) -> tuple[int, list[str]]:
    depth = _brace_delta(lines[start_idx])
    idx = start_idx + 1
    while idx < len(lines) and depth > 0:
        depth += _brace_delta(lines[idx])
        idx += 1
    return idx, lines[start_idx:idx]


def check_iam_resource_names(path: Path, lines: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    idx = 0
    while idx < len(lines):
        match = IAM_RESOURCE_RE.match(lines[idx])
        if not match:
            idx += 1
            continue

        _, block_lines = _extract_resource_block(lines, idx)
        for offset, line in enumerate(block_lines):
            name_match = NAME_ATTR_RE.match(line)
            if not name_match:
                continue
            value = name_match.group(1)
            line_no = idx + offset + 1
            if LEGACY_PREFIX_RE.search(value) and not IAM_PREFIX_OK_RE.search(value):
                violations.append(
                    Violation(
                        path,
                        line_no,
                        "IAM resource name must use iam_name_prefix/local.iam_name_prefix, not var.name_prefix alone",
                    )
                )
        idx += 1
    return violations


def check_github_oidc_iam_scoped(path: Path, text: str) -> list[Violation]:
    violations: list[Violation] = []
    if LEGACY_OIDC_PATTERN_RE.search(text):
        violations.append(
            Violation(
                path,
                1,
                "github-oidc iam_scoped must not retain legacy dev-portal/prod-portal/dev-range role patterns",
            )
        )
    if "iam:AttachRolePolicy" in text and "iam:PolicyArn" not in text:
        violations.append(
            Violation(
                path,
                1,
                "github-oidc iam_scoped must constrain iam:AttachRolePolicy with iam:PolicyArn allowlist",
            )
        )
    for policy in ATTACH_ALLOWLIST_POLICIES:
        if policy not in text:
            violations.append(
                Violation(
                    path,
                    1,
                    f"github-oidc iam_scoped allowlist must include {policy}",
                )
            )
    if "role/shifter-*" not in text.replace(" ", ""):
        violations.append(
            Violation(
                path,
                1,
                "github-oidc iam_scoped must scope deploy-managed roles to role/shifter-*",
            )
        )
    return violations


def check_github_oidc_attachment_cap(path: Path, lines: list[str]) -> list[Violation]:
    attachment_lines = [
        idx for idx, line in enumerate(lines) if ATTACHMENT_RESOURCE_RE.match(line)
    ]
    if len(attachment_lines) > OIDC_ATTACHMENT_CAP:
        return [
            Violation(
                path,
                attachment_lines[OIDC_ATTACHMENT_CAP] + 1,
                f"github-oidc role must attach at most {OIDC_ATTACHMENT_CAP} "
                f"managed policies (found {len(attachment_lines)}); consolidate by "
                "AWS category to keep headroom under the AWS 10-policy limit (#254)",
            )
        ]
    return []


def check_github_oidc_policy_doc_size(path: Path, lines: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    idx = 0
    while idx < len(lines):
        match = IAM_POLICY_RESOURCE_RE.match(lines[idx])
        if not match:
            idx += 1
            continue
        _, block_lines = _extract_resource_block(lines, idx)
        stripped = re.sub(r"\s+", "", "".join(block_lines))
        if len(stripped) > OIDC_POLICY_DOC_LIMIT:
            violations.append(
                Violation(
                    path,
                    idx + 1,
                    f"github-oidc managed policy \"{match.group(1)}\" is "
                    f"{len(stripped)} chars (limit {OIDC_POLICY_DOC_LIMIT}); "
                    "compact or split the category to stay under the AWS "
                    "managed-policy document size limit (#254)",
                )
            )
        idx += 1
    return violations


def check_file(path: Path) -> list[Violation]:
    if path.suffix != ".tf":
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    violations = check_iam_resource_names(path, lines)
    if path.name == "github-oidc.tf":
        violations.extend(check_github_oidc_iam_scoped(path, text))
        violations.extend(check_github_oidc_attachment_cap(path, lines))
        violations.extend(check_github_oidc_policy_doc_size(path, lines))
    return violations


def iter_target_files(repo_root: Path, argv: list[str]) -> list[Path]:
    if argv:
        return [Path(arg).resolve() for arg in argv]

    files: list[Path] = []
    for pattern in IAM_MODULE_GLOBS:
        files.extend(sorted(repo_root.glob(pattern)))
    oidc = repo_root / "platform/terraform/global/iam/github-oidc.tf"
    if oidc.exists():
        files.append(oidc)
    return sorted(set(files))


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
