#!/usr/bin/env python3
"""Lint kms:Decrypt grants for the portal Secrets Manager CMK.

ECS resolves task-definition `secrets = [...]` before container start
using the **execution role**, so any role whose runtime path includes
reading a Secrets Manager value encrypted with the portal CMK must hold
`kms:Decrypt` on that CMK, scoped through Secrets Manager. Without it,
the task aborts with `AccessDeniedException: Access to KMS is not
allowed` and the container never starts. The matching failure on the
**portal EC2 role** silently empties the runtime env var if
`entrypoint.sh::fetch_runtime_secret` swallows the python subshell's
exit code (issue #52).

Enforcement model (intentionally narrow):

* The checker is invoked per file. For every `aws_iam_role` defined in
  the file whose attached `aws_iam_role_policy` blocks grant
  `secretsmanager:GetSecretValue`, require an attached
  `aws_iam_role_policy` block that contains a `kms:Decrypt` statement
  with Resource set to one of the portal-CMK var names
  (`var.secrets_manager_kms_key_arn` or `var.secrets_kms_key_arn`) or
  `"*"`, AND the same policy block carries a
  `Condition.StringEquals` (or `StringLike`) on `"kms:ViaService"`
  matching `secretsmanager.<…>.amazonaws.com`.
* Independently, any `aws_iam_role_policy` block that grants
  `kms:Decrypt` on `Resource="*"` MUST include a `kms:ViaService`
  condition pinning to some service — unconditioned wildcard
  `kms:Decrypt` is too broad.

Scope deliberately omits: cross-file aggregation, action-wildcard
matching (`kms:*` / `secretsmanager:Get*` / `*`), list-form Resource
(`Resource = ["*"]`), and singleton `Statement = {...}` form. None of
those shapes appear in the three currently-scoped target files; adding
them would expand the parser's complexity and historically introduced
bugs of its own (see issue #52 cycle-4 / cycle-5 codex review history
on the issue thread). The repo can revisit when a target module adopts
one of those shapes.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

PORTAL_CMK_VAR_NAMES = ("secrets_manager_kms_key_arn", "secrets_kms_key_arn")
REQUIRED_VIA_SERVICE_PREFIX = "secretsmanager."
REQUIRED_VIA_SERVICE_SUFFIX = ".amazonaws.com"

_AWS_IAM_ROLE_RE = re.compile(r'^\s*resource\s+"aws_iam_role"\s+"([^"]+)"\s*\{')
_AWS_IAM_ROLE_POLICY_RE = re.compile(
    r'^\s*resource\s+"aws_iam_role_policy"\s+"([^"]+)"\s*\{'
)
_ROLE_ATTACH_RE = re.compile(
    r'role\s*=\s*aws_iam_role\.([A-Za-z0-9_]+)\.(?:id|name)'
)

# Exact `var.<NAME>` token match for the portal CMK var names.
# Substring matching would incorrectly accept `var.engine_secrets_kms_key_arn`
# (the engine Pulumi-state CMK) because `secrets_kms_key_arn` is a substring.
_PORTAL_CMK_VAR_RE = re.compile(
    r"\bvar\.(?:"
    + "|".join(re.escape(name) for name in PORTAL_CMK_VAR_NAMES)
    + r")\b"
)

_RESOURCE_WILDCARD_RE = re.compile(r'Resource\s*=\s*"\*"')
_VIA_SERVICE_SECRETSMANAGER_RE = re.compile(
    r'"kms:ViaService"\s*=\s*"'
    + re.escape(REQUIRED_VIA_SERVICE_PREFIX)
    + r'[^"]*'
    + re.escape(REQUIRED_VIA_SERVICE_SUFFIX)
    + r'"'
)
_VIA_SERVICE_ANY_RE = re.compile(r'"kms:ViaService"\s*=\s*"')


@dataclass
class Violation:
    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.reason}"


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _extract_resource_blocks(
    lines: list[str], header_re: re.Pattern[str]
) -> list[tuple[str, int, str]]:
    """Return (resource_name, 1-indexed start line, full block text) for
    each top-level resource matching `header_re`."""
    blocks: list[tuple[str, int, str]] = []
    idx = 0
    while idx < len(lines):
        match = header_re.match(lines[idx])
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
        blocks.append((name, start_line, "\n".join(block_lines)))
    return blocks


def _attached_role(policy_body: str) -> str | None:
    match = _ROLE_ATTACH_RE.search(policy_body)
    return match.group(1) if match else None


def _extract_named_block(text: str, name: str) -> str | None:
    """Return the inner text of `<name> = { ... }`, or None if absent.
    Brace-balanced so nested blocks don't confuse the matcher. Used to
    scope the ViaService search to StringEquals/StringLike condition
    operators specifically — a `kms:ViaService` value in
    `StringNotEquals` does not pin the call to that service and must
    not satisfy the grant check."""
    match = re.search(r"\b" + re.escape(name) + r"\s*=\s*\{", text)
    if not match:
        return None
    cursor = match.end()
    depth = 1
    while cursor < len(text):
        ch = text[cursor]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[match.end() : cursor]
        cursor += 1
    return None


def _has_secretsmanager_via_service(policy_body: str) -> bool:
    """True iff the policy's Condition has StringEquals (or StringLike)
    `"kms:ViaService"` matching `secretsmanager.<…>.amazonaws.com`."""
    return _has_via_service_matching(policy_body, _VIA_SERVICE_SECRETSMANAGER_RE)


def _has_any_via_service(policy_body: str) -> bool:
    """True iff the policy's Condition has StringEquals (or StringLike)
    on `"kms:ViaService"` keyed to any service. Used by the shape
    check; the existence check requires specifically secretsmanager."""
    return _has_via_service_matching(policy_body, _VIA_SERVICE_ANY_RE)


def _has_via_service_matching(
    policy_body: str, value_re: re.Pattern[str]
) -> bool:
    condition = _extract_named_block(policy_body, "Condition")
    if condition is None:
        return False
    for op in ("StringEquals", "StringLike"):
        op_block = _extract_named_block(condition, op)
        if op_block is None:
            continue
        if value_re.search(op_block):
            return True
    return False


def _policy_grants_action(policy_body: str, action: str) -> bool:
    return f'"{action}"' in policy_body


def _policy_resource_is_portal_cmk_var(policy_body: str) -> bool:
    return _PORTAL_CMK_VAR_RE.search(policy_body) is not None


def _policy_resource_is_wildcard(policy_body: str) -> bool:
    return _RESOURCE_WILDCARD_RE.search(policy_body) is not None


def _policy_satisfies_portal_cmk_grant(policy_body: str) -> bool:
    """True iff this policy block grants kms:Decrypt with Resource scoped
    to the portal CMK (var or wildcard) AND a secretsmanager ViaService
    condition."""
    return (
        _policy_grants_action(policy_body, "kms:Decrypt")
        and (
            _policy_resource_is_portal_cmk_var(policy_body)
            or _policy_resource_is_wildcard(policy_body)
        )
        and _has_secretsmanager_via_service(policy_body)
    )


def check_file(path: Path) -> list[Violation]:
    lines = path.read_text().splitlines()

    role_blocks = _extract_resource_blocks(lines, _AWS_IAM_ROLE_RE)
    if not role_blocks:
        return []

    policy_blocks = _extract_resource_blocks(lines, _AWS_IAM_ROLE_POLICY_RE)
    violations: list[Violation] = []

    # role_name -> list of (policy_name, policy_body)
    role_to_policies: dict[str, list[tuple[str, str]]] = {}
    for policy_name, policy_line, policy_body in policy_blocks:
        role = _attached_role(policy_body)
        if role is not None:
            role_to_policies.setdefault(role, []).append((policy_name, policy_body))

        # Shape check: a policy granting kms:Decrypt on Resource="*"
        # must carry a kms:ViaService condition pinning to some service.
        # A grant scoped to a specific KMS key ARN (e.g. the engine
        # Pulumi-state CMK) without a condition is fine — the key's
        # resource ARN is the boundary.
        if (
            _policy_grants_action(policy_body, "kms:Decrypt")
            and _policy_resource_is_wildcard(policy_body)
            and not _has_any_via_service(policy_body)
        ):
            violations.append(
                Violation(
                    path,
                    policy_line,
                    f"aws_iam_role_policy.{policy_name} grants kms:Decrypt "
                    'on Resource="*" but has no StringEquals/StringLike '
                    '"kms:ViaService" condition — unconditioned wildcard '
                    "kms:Decrypt is too broad",
                )
            )

    # Existence check: every role whose attached policies grant
    # secretsmanager:GetSecretValue must also have at least one
    # attached policy satisfying the portal-CMK kms:Decrypt grant
    # shape.
    for role_name, role_line, _role_block in role_blocks:
        policies = role_to_policies.get(role_name, [])
        reads_secrets = any(
            _policy_grants_action(body, "secretsmanager:GetSecretValue")
            for (_name, body) in policies
        )
        if not reads_secrets:
            continue

        has_grant = any(
            _policy_satisfies_portal_cmk_grant(body) for (_name, body) in policies
        )
        if not has_grant:
            violations.append(
                Violation(
                    path,
                    role_line,
                    f"role aws_iam_role.{role_name} has an attached "
                    "secretsmanager:GetSecretValue grant but no attached "
                    "aws_iam_role_policy satisfies the portal Secrets "
                    "Manager kms:Decrypt grant. Add a policy with Action "
                    "containing kms:Decrypt, Resource set to "
                    f"var.{PORTAL_CMK_VAR_NAMES[0]} or "
                    f'var.{PORTAL_CMK_VAR_NAMES[1]} (preferred) or "*", '
                    "and Condition StringEquals (or StringLike) "
                    "kms:ViaService = "
                    f'"{REQUIRED_VIA_SERVICE_PREFIX}<region>'
                    f'{REQUIRED_VIA_SERVICE_SUFFIX}". Without this grant, '
                    "ECS task secrets injection and runtime "
                    "fetch_runtime_secret calls fail with "
                    '"Access to KMS is not allowed".',
                )
            )

    return violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: check_tf_kms_secrets_grant.py FILE.tf [FILE.tf ...]",
            file=sys.stderr,
        )
        return 2

    violations: list[Violation] = []
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"{path}: file not found", file=sys.stderr)
            return 2
        if path.suffix == ".tf":
            violations.extend(check_file(path))

    if violations:
        print(
            "Secrets Manager kms:Decrypt grant violations "
            f"({len(violations)} total):",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
