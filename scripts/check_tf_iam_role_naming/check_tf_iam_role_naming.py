#!/usr/bin/env python3
"""Lint IAM role and instance profile naming in Terraform modules.

Deploy-managed IAM resources must use the iam_name_prefix seam so role names
land in the shifter-* namespace without renaming unrelated infrastructure.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GITHUB_OIDC_CANONICAL_PATH = Path("platform/terraform/global/iam/github-oidc.tf")
ENGINE_PROVISIONER_IAM_CANONICAL_PATH = Path(
    "platform/terraform/modules/engine-provisioner/iam.tf"
)

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
NAME_ATTR_RE = re.compile(r"^\s*name\s*=\s*(.+)$")
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

# Base-image-pipeline role (#1656). The packer.yml base `build` job assumes a
# dedicated least-privilege role instead of the broad deploy role. Its OIDC trust
# MUST pin the exact protected-branch subjects (never repo:...:*), and its inline
# policy MUST scope iam:PassRole to the EXACT env range role passed to EC2 - never
# shifter-*, *-range-instance, or any other wildcard - so the fresh-boot verifier
# cannot pass a more-privileged profile (ADR-004-R22). These checks run only when
# the role / inline policy is present, so deploy-only github-oidc.tf fixtures are
# unaffected.
IMAGE_ROLE_RE = re.compile(
    r'^\s*resource\s+"aws_iam_role"\s+"github_actions_image"\s*\{'
)
IMAGE_POLICY_RE = re.compile(
    r'^\s*resource\s+"aws_iam_role_policy"\s+"image_pipeline"\s*\{'
)
IMAGE_TRUST_REQUIRED_SUBS: tuple[str, ...] = (
    "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/dev",
    "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main",
)
IMAGE_TRUST_WILDCARD_SUB = "repo:${var.github_org}/${var.github_repo}:*"
IMAGE_PASSROLE_EXACT_RESOURCE = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-range-range-instance"
IMAGE_PASSROLE_FORBIDDEN_WILDCARDS: tuple[str, ...] = (
    "role/shifter-*",
    "role/${var.environment}-*",
    "role/*",
    "*-range-instance",
)

CI_BOUNDARY_RE = re.compile(
    r'^\s*resource\s+"aws_iam_policy"\s+"ci_role_permissions_boundary"\s*\{'
)
VPN_GATEWAY_IDENTITY_POLICY_RE = re.compile(
    r'^\s*resource\s+"aws_iam_role_policy"\s+"vpn_gateway_role_management"\s*\{'
)
VPN_GATEWAY_ROLE_RESOURCE = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
VPN_GATEWAY_PROFILE_RESOURCE = (
    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:"
    "instance-profile/shifter-${var.environment}-*-vpn-gateway"
)
VPN_GATEWAY_IDENTITY_ROLE_RESOURCE = (
    "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
)
VPN_GATEWAY_IDENTITY_PROFILE_RESOURCE = "arn:aws:iam::${local.account_id}:instance-profile/shifter-${var.environment}-*-vpn-gateway"
VPN_GATEWAY_BOUNDARY_NOT_RESOURCES: set[str] = {
    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-*-polaris-agent",
    VPN_GATEWAY_ROLE_RESOURCE,
    VPN_GATEWAY_PROFILE_RESOURCE,
}
VPN_GATEWAY_TAMPER_ACTIONS: set[str] = {
    "iam:PutRolePermissionsBoundary",
    "iam:DeleteRolePermissionsBoundary",
}
VPN_GATEWAY_ROLE_ACTIONS: set[str] = {
    "iam:DeleteRole",
    "iam:PutRolePolicy",
    "iam:DeleteRolePolicy",
    "iam:TagRole",
    "iam:UntagRole",
    "iam:GetRole",
    "iam:GetRolePolicy",
    "iam:ListRolePolicies",
    "iam:ListAttachedRolePolicies",
    "iam:ListInstanceProfilesForRole",
    "iam:ListRoleTags",
}
VPN_GATEWAY_PROFILE_ACTIONS: set[str] = {
    "iam:CreateInstanceProfile",
    "iam:DeleteInstanceProfile",
    "iam:AddRoleToInstanceProfile",
    "iam:RemoveRoleFromInstanceProfile",
    "iam:GetInstanceProfile",
    "iam:TagInstanceProfile",
    "iam:UntagInstanceProfile",
}


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
                    f'github-oidc managed policy "{match.group(1)}" is '
                    f"{len(stripped)} chars (limit {OIDC_POLICY_DOC_LIMIT}); "
                    "compact or split the category to stay under the AWS "
                    "managed-policy document size limit (#254)",
                )
            )
        idx += 1
    return violations


def _find_named_resource_block(
    lines: list[str], header_re: re.Pattern[str]
) -> list[str] | None:
    idx = 0
    while idx < len(lines):
        if header_re.match(lines[idx]):
            _, block_lines = _extract_resource_block(lines, idx)
            return block_lines
        idx += 1
    return None


def _required_resource_block(
    path: Path,
    lines: list[str],
    header_re: re.Pattern[str],
    *,
    canonical_path: Path,
    resource_label: str,
    repo_root: Path,
) -> tuple[list[str] | None, list[Violation]]:
    """Find a resource, failing closed only on its canonical repository path."""
    block = _find_named_resource_block(lines, header_re)
    if block is not None or path.resolve() != (repo_root / canonical_path).resolve():
        return block, []
    return None, [
        Violation(
            path, 1, f"{resource_label} is required on its canonical repository path"
        )
    ]


def _strip_hcl_comments(text: str) -> str:
    """Drop `#` line comments so guardrail matching never keys on prose.

    github-oidc.tf uses `#` comments (terraform fmt normalizes to them); a
    comment mentioning a forbidden wildcard (e.g. an explanatory
    "not *-range-instance") must not trip the checks below, which match trust /
    policy content only. `#` never appears inside the ARNs, actions, or OIDC
    subjects the checks inspect, so this is a safe, precise strip (`//` / `/* */`
    stripping is intentionally avoided - `instance/*` contains a literal `/*`).
    """
    return "\n".join(re.sub(r"#.*$", "", line) for line in text.splitlines())


def _find_statement_block(block: list[str], sid: str) -> str | None:
    """Return the jsonencode statement containing an exact Sid."""
    idx = 0
    while idx < len(block):
        if not re.match(r"^\s*\{\s*$", block[idx]):
            idx += 1
            continue
        end_idx, statement_lines = _extract_resource_block(block, idx)
        statement = _strip_hcl_comments("\n".join(statement_lines))
        if re.search(rf'\bSid\s*=\s*"{re.escape(sid)}"', statement):
            return statement
        idx = max(end_idx, idx + 1)
    return None


def _assignment_values(block: str, key: str) -> set[str] | None:
    """Return the scalar/list values assigned to an exact HCL attribute key."""
    key_re = re.compile(rf'^\s*(?:"{re.escape(key)}"|{re.escape(key)})\s*=\s*(.*)$')
    lines = block.splitlines()
    for idx, line in enumerate(lines):
        match = key_re.match(line)
        if not match:
            continue

        expression = match.group(1).strip()
        if expression.startswith("["):
            depth = expression.count("[") - expression.count("]")
            while depth > 0 and idx + 1 < len(lines):
                idx += 1
                next_line = lines[idx]
                expression += "\n" + next_line
                depth += next_line.count("[") - next_line.count("]")

        quoted = set(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', expression))
        if quoted:
            return quoted
        scalar = expression.rstrip(",").strip()
        return {scalar} if scalar else set()
    return None


def _exact_values_violation(
    path: Path,
    statement: str | None,
    key: str,
    expected: set[str],
    reason: str,
) -> list[Violation]:
    if statement is not None and _assignment_values(statement, key) == expected:
        return []
    return [Violation(path, 1, reason)]


def check_github_oidc_vpn_gateway_boundary(
    path: Path,
    lines: list[str],
    *,
    repo_root: Path = REPO_ROOT,
) -> list[Violation]:
    """Pin exact VPN gateway delegation in the shared CI boundary (#1755)."""
    block, violations = _required_resource_block(
        path,
        lines,
        CI_BOUNDARY_RE,
        canonical_path=GITHUB_OIDC_CANONICAL_PATH,
        resource_label="VPN gateway boundary aws_iam_policy.ci_role_permissions_boundary",
        repo_root=repo_root,
    )
    if block is None:
        return violations

    escalation = _find_statement_block(block, "DenyIamEscalation")
    violations.extend(
        _exact_values_violation(
            path,
            escalation,
            "NotResource",
            VPN_GATEWAY_BOUNDARY_NOT_RESOURCES,
            "VPN gateway boundary delegation must carve out only the exact approved "
            "role and instance-profile namespaces",
        )
    )

    tamper = _find_statement_block(block, "DenyVpnGatewayBoundaryTamper")
    tamper_valid = tamper is not None and all(
        (
            _assignment_values(tamper, "Effect") == {"Deny"},
            _assignment_values(tamper, "Action") == VPN_GATEWAY_TAMPER_ACTIONS,
            _assignment_values(tamper, "Resource") == {VPN_GATEWAY_ROLE_RESOURCE},
        )
    )
    if not tamper_valid:
        violations.append(
            Violation(
                path,
                1,
                "VPN gateway boundary tamper deny must contain only the approved boundary "
                "actions on the exact gateway role namespace",
            )
        )
    return violations


def check_vpn_gateway_identity_policy(
    path: Path,
    lines: list[str],
    *,
    repo_root: Path = REPO_ROOT,
) -> list[Violation]:
    """Pin the provisioner identity-policy half of VPN IAM delegation."""
    block, violations = _required_resource_block(
        path,
        lines,
        VPN_GATEWAY_IDENTITY_POLICY_RE,
        canonical_path=ENGINE_PROVISIONER_IAM_CANONICAL_PATH,
        resource_label="VPN gateway identity aws_iam_role_policy.vpn_gateway_role_management",
        repo_root=repo_root,
    )
    if block is None:
        return violations

    block_text = _strip_hcl_comments("\n".join(block))
    if (
        "iam:PutRolePermissionsBoundary" in block_text
        or "iam:DeleteRolePermissionsBoundary" in block_text
    ):
        violations.append(
            Violation(
                path,
                1,
                "VPN gateway identity policy must not mutate or remove permissions boundaries",
            )
        )

    create = _find_statement_block(block, "CreateVpnGatewayRoleWithBoundary")
    if create is None or not all(
        (
            _assignment_values(create, "Effect") == {"Allow"},
            _assignment_values(create, "Action") == {"iam:CreateRole"},
            _assignment_values(create, "Resource")
            == {VPN_GATEWAY_IDENTITY_ROLE_RESOURCE},
            _assignment_values(create, "iam:PermissionsBoundary")
            == {"var.permissions_boundary_arn"},
        )
    ):
        violations.append(
            Violation(
                path,
                1,
                "VPN gateway identity policy CreateRole must target the exact role namespace "
                "and require the installation permissions boundary",
            )
        )

    manage_role = _find_statement_block(block, "ManageVpnGatewayRole")
    if manage_role is None or not all(
        (
            _assignment_values(manage_role, "Effect") == {"Allow"},
            _assignment_values(manage_role, "Action") == VPN_GATEWAY_ROLE_ACTIONS,
            _assignment_values(manage_role, "Resource")
            == {VPN_GATEWAY_IDENTITY_ROLE_RESOURCE},
        )
    ):
        violations.append(
            Violation(
                path,
                1,
                "VPN gateway identity policy role management must contain only the "
                "approved actions on the exact role namespace",
            )
        )

    managed = _find_statement_block(block, "UseOnlySsmCorePolicy")
    if managed is None or not all(
        (
            _assignment_values(managed, "Effect") == {"Allow"},
            _assignment_values(managed, "Action")
            == {"iam:AttachRolePolicy", "iam:DetachRolePolicy"},
            _assignment_values(managed, "Resource")
            == {VPN_GATEWAY_IDENTITY_ROLE_RESOURCE},
            _assignment_values(managed, "iam:PolicyARN")
            == {"arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"},
        )
    ):
        violations.append(
            Violation(
                path,
                1,
                "VPN gateway identity policy managed-policy operations must be limited to "
                "AmazonSSMManagedInstanceCore on the exact role namespace",
            )
        )

    instance_profile = _find_statement_block(block, "ManageVpnGatewayInstanceProfile")
    if instance_profile is None or not all(
        (
            _assignment_values(instance_profile, "Effect") == {"Allow"},
            _assignment_values(instance_profile, "Action")
            == VPN_GATEWAY_PROFILE_ACTIONS,
            _assignment_values(instance_profile, "Resource")
            == {VPN_GATEWAY_IDENTITY_PROFILE_RESOURCE},
        )
    ):
        violations.append(
            Violation(
                path,
                1,
                "VPN gateway identity policy must manage only the exact instance-profile namespace",
            )
        )

    passrole = _find_statement_block(block, "PassVpnGatewayRoleOnlyToEc2")
    if passrole is None or not all(
        (
            _assignment_values(passrole, "Effect") == {"Allow"},
            _assignment_values(passrole, "Action") == {"iam:PassRole"},
            _assignment_values(passrole, "Resource")
            == {VPN_GATEWAY_IDENTITY_ROLE_RESOURCE},
            _assignment_values(passrole, "iam:PassedToService")
            == {"ec2.amazonaws.com"},
        )
    ):
        violations.append(
            Violation(
                path,
                1,
                "VPN gateway identity policy PassRole must target the exact role namespace "
                "and require ec2.amazonaws.com",
            )
        )
    return violations


def check_github_oidc_image_role_trust(path: Path, lines: list[str]) -> list[Violation]:
    """Base-image role OIDC trust must pin exact protected subjects (#1656).

    No-op when the github_actions_image role is absent, so deploy-only fixtures
    are unaffected; when present, a repo:...:* wildcard sub or a missing exact
    protected-branch subject fails closed.
    """
    block = _find_named_resource_block(lines, IMAGE_ROLE_RE)
    if block is None:
        return []
    compact = re.sub(r"\s+", "", _strip_hcl_comments("\n".join(block)))
    violations: list[Violation] = []
    if IMAGE_TRUST_WILDCARD_SUB.replace(" ", "") in compact:
        violations.append(
            Violation(
                path,
                1,
                "image-pipeline role OIDC trust must pin exact protected-branch "
                "subjects, not a repo:...:* wildcard (ADR-004-R22, #1656)",
            )
        )
    for sub in IMAGE_TRUST_REQUIRED_SUBS:
        if sub.replace(" ", "") not in compact:
            violations.append(
                Violation(
                    path,
                    1,
                    f"image-pipeline role OIDC trust must include exact subject {sub} (ADR-004-R22, #1656)",
                )
            )
    return violations


def check_github_oidc_image_passrole_scope(
    path: Path, lines: list[str]
) -> list[Violation]:
    """Base-image policy iam:PassRole must target the exact range role (#1656).

    No-op when the image_pipeline inline policy is absent; when present, the
    PassRole must name exactly shifter-${var.environment}-range-range-instance,
    carry the ec2.amazonaws.com service condition, and use no wildcard resource.
    """
    block = _find_named_resource_block(lines, IMAGE_POLICY_RE)
    if block is None:
        return []
    text = _strip_hcl_comments("\n".join(block))
    compact = re.sub(r"\s+", "", text)
    violations: list[Violation] = []
    if "iam:PassRole" not in text:
        violations.append(
            Violation(
                path,
                1,
                "image-pipeline policy must grant iam:PassRole scoped to the exact range role (ADR-004-R22, #1656)",
            )
        )
        return violations
    if IMAGE_PASSROLE_EXACT_RESOURCE.replace(" ", "") not in compact:
        violations.append(
            Violation(
                path,
                1,
                "image-pipeline iam:PassRole must target exactly "
                "role/shifter-${var.environment}-range-range-instance "
                "(ADR-004-R22, #1656)",
            )
        )
    for forbidden in IMAGE_PASSROLE_FORBIDDEN_WILDCARDS:
        if forbidden.replace(" ", "") in compact:
            violations.append(
                Violation(
                    path,
                    1,
                    f"image-pipeline iam:PassRole must not use wildcard resource '{forbidden}' (ADR-004-R22, #1656)",
                )
            )
    if "ec2.amazonaws.com" not in compact:
        violations.append(
            Violation(
                path,
                1,
                "image-pipeline iam:PassRole must be conditioned on "
                "iam:PassedToService = ec2.amazonaws.com (ADR-004-R22, #1656)",
            )
        )
    return violations


def check_file(path: Path, *, repo_root: Path = REPO_ROOT) -> list[Violation]:
    if path.suffix != ".tf":
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    violations = check_iam_resource_names(path, lines)
    violations.extend(
        check_vpn_gateway_identity_policy(path, lines, repo_root=repo_root)
    )
    if path.name == "github-oidc.tf":
        violations.extend(check_github_oidc_iam_scoped(path, text))
        violations.extend(check_github_oidc_attachment_cap(path, lines))
        violations.extend(check_github_oidc_policy_doc_size(path, lines))
        violations.extend(check_github_oidc_image_role_trust(path, lines))
        violations.extend(check_github_oidc_image_passrole_scope(path, lines))
        violations.extend(
            check_github_oidc_vpn_gateway_boundary(path, lines, repo_root=repo_root)
        )
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
    repo_root = REPO_ROOT
    violations: list[Violation] = []
    for path in iter_target_files(repo_root, args):
        if not path.is_file():
            continue
        violations.extend(check_file(path, repo_root=repo_root))
    if violations:
        for violation in violations:
            print(violation)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
