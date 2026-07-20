#!/usr/bin/env python3
"""Lint provisioner GWLB and request-owned VPN NLB IAM statements.

The engine provisioner legitimately needs to create and manage Gateway Load
Balancer infrastructure for NGFW traffic steering, but mutable ELBv2 APIs
must not remain on wildcard statements that can target every load balancer,
target group, or listener in the account.

Three action families are pinned independently for both resource families:

- Existing-resource mutations (Delete / Modify / Register / Deregister /
  RemoveTags) must be scoped to GWLB or exact ``shifter-vpn-*`` ARNs and
  require Shifter ownership resource tags.
- Resource creation (Create*LoadBalancer / Create*TargetGroup / CreateListener)
  must use the resource type AWS authorizes (notably the parent NLB for
  CreateListener) and require Shifter ownership request tags.
- Tag-on-create (AddTags) must be scoped to the matching resource namespace and
  require both an elasticloadbalancing:CreateAction condition and Shifter
  ownership request tags.

The VPN runtime listener itself must send ``local.common_tags`` with its create
request. GWLB and VPN NLB resources may not share a mutable policy statement.

Describe APIs must stay in their own wildcard statement (AWS service
authorization requires Resource = "*" for the ELBv2 read APIs).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

MUTABLE_EXISTING_ELB_ACTIONS: set[str] = {
    "elasticloadbalancing:DeleteLoadBalancer",
    "elasticloadbalancing:DeleteTargetGroup",
    "elasticloadbalancing:DeleteListener",
    "elasticloadbalancing:ModifyLoadBalancerAttributes",
    "elasticloadbalancing:ModifyTargetGroup",
    "elasticloadbalancing:ModifyTargetGroupAttributes",
    "elasticloadbalancing:SetSecurityGroups",
    "elasticloadbalancing:RegisterTargets",
    "elasticloadbalancing:DeregisterTargets",
    "elasticloadbalancing:RemoveTags",
}
CREATE_ELB_ACTIONS: set[str] = {
    "elasticloadbalancing:CreateLoadBalancer",
    "elasticloadbalancing:CreateTargetGroup",
    "elasticloadbalancing:CreateListener",
}
TAG_ON_CREATE_ELB_ACTIONS: set[str] = {
    "elasticloadbalancing:AddTags",
}
ALL_MUTABLE_ELB_ACTIONS: set[str] = (
    MUTABLE_EXISTING_ELB_ACTIONS | CREATE_ELB_ACTIONS | TAG_ON_CREATE_ELB_ACTIONS
)

REQUIRED_RESOURCE_SNIPPETS: tuple[str, ...] = (
    "loadbalancer/gwy/",
    "listener/gwy/",
    "targetgroup/",
)
EXISTING_RESOURCE_TAG_KEYS: tuple[str, ...] = (
    "elasticloadbalancing:ResourceTag/shifter:system",
    "elasticloadbalancing:ResourceTag/shifter:environment",
    "elasticloadbalancing:ResourceTag/ManagedBy",
)
REQUEST_TAG_KEYS: tuple[str, ...] = (
    "aws:RequestTag/shifter:system",
    "aws:RequestTag/shifter:environment",
    "aws:RequestTag/ManagedBy",
)
CREATE_ACTION_CONDITION_KEY: str = "elasticloadbalancing:CreateAction"
VPN_LOAD_BALANCER_RESOURCE = "loadbalancer/net/shifter-vpn-*/*"
VPN_LISTENER_RESOURCE = "listener/net/shifter-vpn-*/*/*"
VPN_TARGET_GROUP_RESOURCE = "targetgroup/shifter-vpn-*/*"
VPN_LOAD_BALANCER_ARN = (
    "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:"
    + VPN_LOAD_BALANCER_RESOURCE
)
VPN_LISTENER_ARN = (
    "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:"
    + VPN_LISTENER_RESOURCE
)
VPN_TARGET_GROUP_ARN = (
    "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:"
    + VPN_TARGET_GROUP_RESOURCE
)
VPN_LOAD_BALANCER_ACTIONS: set[str] = {
    "elasticloadbalancing:DeleteLoadBalancer",
    "elasticloadbalancing:ModifyLoadBalancerAttributes",
    "elasticloadbalancing:SetSecurityGroups",
}
VPN_LISTENER_ACTIONS: set[str] = {"elasticloadbalancing:DeleteListener"}
VPN_TARGET_GROUP_ACTIONS: set[str] = {
    "elasticloadbalancing:DeleteTargetGroup",
    "elasticloadbalancing:ModifyTargetGroup",
    "elasticloadbalancing:ModifyTargetGroupAttributes",
    "elasticloadbalancing:RegisterTargets",
    "elasticloadbalancing:DeregisterTargets",
}

# Match both the inline (aws_iam_role_policy) and customer-managed (aws_iam_policy)
# forms: the gwlb policy was moved to a managed policy to keep the task role under
# AWS's inline-policy-size limit (issue #1749), and the same ELB scoping rules
# must apply regardless of the container. The check keys on the resource name.
_RESOURCE_RE = re.compile(r'^\s*resource\s+"aws_iam_(?:role_)?policy"\s+"([^"]+)"\s*\{')
_ACTION_RE = re.compile(r'"(elasticloadbalancing:[^"]+)"')
_VPN_LISTENER_RE = re.compile(r'^\s*resource\s+"aws_lb_listener"\s+"vpn"\s*\{')


@dataclass
class Violation:
    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.reason}"


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _extract_statement_blocks(lines: list[str]) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not re.match(r"^\s*\{\s*$", line):
            idx += 1
            continue

        start_idx = idx
        depth = _brace_delta(line)
        idx += 1
        while idx < len(lines) and depth > 0:
            depth += _brace_delta(lines[idx])
            idx += 1

        block = "\n".join(lines[start_idx:idx])
        if '"elasticloadbalancing:' in block:
            blocks.append((start_idx + 1, block))
    return blocks


def _extract_policy_body(
    lines: list[str], resource_name: str
) -> tuple[int, list[str]] | None:
    in_resource = False
    resource_depth = 0
    resource_start = 0

    for idx, line in enumerate(lines):
        if not in_resource:
            match = _RESOURCE_RE.match(line)
            if match and match.group(1) == resource_name:
                in_resource = True
                resource_depth = _brace_delta(line)
                resource_start = idx
            continue

        resource_depth += _brace_delta(line)
        if resource_depth <= 0:
            return resource_start + 1, lines[resource_start : idx + 1]

    return None


def _actions(block: str) -> set[str]:
    return set(_ACTION_RE.findall(block))


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


def _action_matches(actions: set[str], family: set[str]) -> list[str]:
    matches: set[str] = set()
    for action in actions:
        for member in family:
            if action == member or fnmatchcase(member, action):
                matches.add(action)
    return sorted(matches)


def _wildcard_action_violations(
    path: Path, line: int, mutable_actions: list[str]
) -> list[Violation]:
    wildcard_actions = [action for action in mutable_actions if "*" in action]
    if not wildcard_actions:
        return []
    return [
        Violation(
            path,
            line,
            "mutable ELBv2 actions must be enumerated, "
            f"not granted through wildcard action patterns ({', '.join(wildcard_actions)})",
        )
    ]


def _statement_scope_violations(
    path: Path, line: int, block: str, mutable_actions: list[str]
) -> list[Violation]:
    violations: list[Violation] = []
    if 'Resource = "*"' in block:
        violations.append(
            Violation(
                path,
                line,
                f"mutable ELBv2 actions must not use Resource=* ({', '.join(mutable_actions)})",
            )
        )
    if not all(snippet in block for snippet in REQUIRED_RESOURCE_SNIPPETS):
        violations.append(
            Violation(
                path,
                line,
                "mutable ELBv2 actions must be scoped to GWLB ELBv2 ARNs "
                "(loadbalancer/gwy/, listener/gwy/, targetgroup/)",
            )
        )
    return violations


def _required_keys_violations(
    path: Path,
    line: int,
    block: str,
    keys: tuple[str, ...],
    reason_template: str,
) -> list[Violation]:
    return [
        Violation(path, line, reason_template.format(key=key))
        for key in keys
        if key not in block
    ]


def _statement_mixing_violations(path: Path, line: int, block: str) -> list[Violation]:
    if "elasticloadbalancing:Describe" not in block:
        return []
    return [
        Violation(
            path,
            line,
            "Describe APIs must stay separate from mutable ELBv2 actions",
        )
    ]


def _check_statement(path: Path, line: int, block: str) -> list[Violation]:
    actions = _actions(block)
    mutable_actions = _action_matches(actions, ALL_MUTABLE_ELB_ACTIONS)
    if not mutable_actions:
        return []

    if "shifter-vpn-" in block:
        return _check_vpn_statement(path, line, block)

    violations: list[Violation] = []
    violations.extend(_wildcard_action_violations(path, line, mutable_actions))
    violations.extend(_statement_scope_violations(path, line, block, mutable_actions))
    violations.extend(_statement_mixing_violations(path, line, block))

    has_existing = bool(_action_matches(actions, MUTABLE_EXISTING_ELB_ACTIONS))
    has_create = bool(_action_matches(actions, CREATE_ELB_ACTIONS))
    has_tag_on_create = bool(_action_matches(actions, TAG_ON_CREATE_ELB_ACTIONS))

    if has_existing:
        violations.extend(
            _required_keys_violations(
                path,
                line,
                block,
                EXISTING_RESOURCE_TAG_KEYS,
                "mutable ELBv2 actions on existing resources must require {key}",
            )
        )
    if has_create:
        violations.extend(
            _required_keys_violations(
                path,
                line,
                block,
                REQUEST_TAG_KEYS,
                "ELBv2 create actions must require {key}",
            )
        )
    if has_tag_on_create:
        violations.extend(
            _required_keys_violations(
                path,
                line,
                block,
                REQUEST_TAG_KEYS,
                "ELBv2 AddTags must require {key}",
            )
        )
        if CREATE_ACTION_CONDITION_KEY not in block:
            violations.append(
                Violation(
                    path,
                    line,
                    f"ELBv2 AddTags must require {CREATE_ACTION_CONDITION_KEY} (creation-time-only tagging)",
                )
            )

    return violations


def _vpn_exact_values_violation(
    path: Path,
    line: int,
    block: str,
    *,
    key: str,
    expected: set[str],
    reason: str,
) -> list[Violation]:
    if _assignment_values(block, key) == expected:
        return []
    return [Violation(path, line, reason)]


def _vpn_condition_violations(
    path: Path,
    line: int,
    block: str,
    keys: tuple[str, ...],
    *,
    context: str,
) -> list[Violation]:
    expected = {
        "aws:RequestTag/shifter:system": {"shifter"},
        "aws:RequestTag/shifter:environment": {"var.environment"},
        "aws:RequestTag/ManagedBy": {"terraform"},
        "elasticloadbalancing:ResourceTag/shifter:system": {"shifter"},
        "elasticloadbalancing:ResourceTag/shifter:environment": {"var.environment"},
        "elasticloadbalancing:ResourceTag/ManagedBy": {"terraform"},
    }
    return [
        Violation(path, line, f"{context} must require the exact value for {key}")
        for key in keys
        if _assignment_values(block, key) != expected[key]
    ]


def _check_vpn_statement(
    path: Path,
    line: int,
    block: str,
) -> list[Violation]:
    """Validate action/resource-aware request-owned VPN NLB statements."""
    violations: list[Violation] = []
    violations.extend(_statement_mixing_violations(path, line, block))
    if "loadbalancer/gwy/" in block or "listener/gwy/" in block or "/app/" in block:
        violations.append(
            Violation(
                path,
                line,
                "ELBv2 statements must not mix GWLB and VPN NLB resource namespaces",
            )
        )

    action_values = _assignment_values(block, "Action") or set()
    allowed_actions = (
        MUTABLE_EXISTING_ELB_ACTIONS | CREATE_ELB_ACTIONS | TAG_ON_CREATE_ELB_ACTIONS
    )
    if not action_values or not action_values <= allowed_actions:
        violations.append(
            Violation(
                path,
                line,
                "VPN ELBv2 statements must contain only explicitly approved actions",
            )
        )

    create_actions = action_values & CREATE_ELB_ACTIONS
    existing_actions = action_values & MUTABLE_EXISTING_ELB_ACTIONS
    tag_actions = action_values & TAG_ON_CREATE_ELB_ACTIONS
    family_count = sum(
        bool(family) for family in (create_actions, existing_actions, tag_actions)
    )
    if family_count != 1:
        violations.append(
            Violation(
                path, line, "VPN ELBv2 action families must use separate statements"
            )
        )
        return violations

    if _assignment_values(block, "Effect") != {"Allow"}:
        violations.append(
            Violation(path, line, "VPN ELBv2 statements must use Effect=Allow")
        )

    if create_actions:
        if len(action_values) != 1:
            violations.append(
                Violation(
                    path, line, "VPN ELBv2 create actions must use separate statements"
                )
            )
        create_action = next(iter(create_actions))
        expected_resources = {
            "elasticloadbalancing:CreateLoadBalancer": {VPN_LOAD_BALANCER_ARN},
            "elasticloadbalancing:CreateListener": {VPN_LOAD_BALANCER_ARN},
            "elasticloadbalancing:CreateTargetGroup": {VPN_TARGET_GROUP_ARN},
        }[create_action]
        violations.extend(
            _vpn_exact_values_violation(
                path,
                line,
                block,
                key="Resource",
                expected=expected_resources,
                reason=(
                    "VPN CreateListener must authorize only its parent shifter-vpn NLB"
                    if create_action == "elasticloadbalancing:CreateListener"
                    else "VPN ELBv2 create action must target only its exact shifter-vpn namespace"
                ),
            )
        )
        violations.extend(
            _vpn_condition_violations(
                path,
                line,
                block,
                REQUEST_TAG_KEYS,
                context="VPN ELBv2 create action",
            )
        )
        if create_action == "elasticloadbalancing:CreateListener":
            violations.extend(
                _vpn_condition_violations(
                    path,
                    line,
                    block,
                    EXISTING_RESOURCE_TAG_KEYS,
                    context="VPN CreateListener parent NLB ownership",
                )
            )

    if existing_actions:
        expected_resources: set[str] = set()
        if existing_actions & VPN_LOAD_BALANCER_ACTIONS:
            expected_resources.add(VPN_LOAD_BALANCER_ARN)
        if existing_actions & VPN_LISTENER_ACTIONS:
            expected_resources.add(VPN_LISTENER_ARN)
        if existing_actions & VPN_TARGET_GROUP_ACTIONS:
            expected_resources.add(VPN_TARGET_GROUP_ARN)
        if "elasticloadbalancing:RemoveTags" in existing_actions:
            expected_resources.update(
                {VPN_LOAD_BALANCER_ARN, VPN_LISTENER_ARN, VPN_TARGET_GROUP_ARN}
            )
        violations.extend(
            _vpn_exact_values_violation(
                path,
                line,
                block,
                key="Resource",
                expected=expected_resources,
                reason="VPN existing-resource actions must target only their exact shifter-vpn namespaces",
            )
        )
        violations.extend(
            _vpn_condition_violations(
                path,
                line,
                block,
                EXISTING_RESOURCE_TAG_KEYS,
                context="VPN mutable ELBv2 action",
            )
        )

    if tag_actions:
        violations.extend(
            _vpn_exact_values_violation(
                path,
                line,
                block,
                key="Resource",
                expected={
                    VPN_LOAD_BALANCER_ARN,
                    VPN_LISTENER_ARN,
                    VPN_TARGET_GROUP_ARN,
                },
                reason="VPN AddTags must cover only the exact NLB, listener, and target-group namespaces",
            )
        )
        violations.extend(
            _vpn_exact_values_violation(
                path,
                line,
                block,
                key=CREATE_ACTION_CONDITION_KEY,
                expected={"CreateLoadBalancer", "CreateTargetGroup", "CreateListener"},
                reason=f"VPN ELBv2 AddTags must require the exact {CREATE_ACTION_CONDITION_KEY} allowlist",
            )
        )
        violations.extend(
            _vpn_condition_violations(
                path,
                line,
                block,
                REQUEST_TAG_KEYS,
                context="VPN ELBv2 AddTags",
            )
        )
    return violations


def _vpn_contract_violations(
    path: Path, policy_start_line: int, policy_lines: list[str]
) -> list[Violation]:
    vpn_actions: set[str] = set()
    for _line, block in _extract_statement_blocks(policy_lines):
        if "shifter-vpn-" in block:
            vpn_actions.update(_actions(block))
    missing = sorted(ALL_MUTABLE_ELB_ACTIONS - vpn_actions)
    if not missing:
        return []
    return [
        Violation(
            path,
            policy_start_line,
            "VPN ELBv2 policy contract is missing required actions: "
            + ", ".join(missing),
        )
    ]


def _check_vpn_listener_tags(path: Path, lines: list[str]) -> list[Violation]:
    for idx, line in enumerate(lines):
        if not _VPN_LISTENER_RE.match(line):
            continue
        depth = _brace_delta(line)
        end = idx + 1
        while end < len(lines) and depth > 0:
            depth += _brace_delta(lines[end])
            end += 1
        compact = re.sub(r"\s+", "", "\n".join(lines[idx:end]))
        if "tags=local.common_tags" in compact:
            return []
        return [
            Violation(
                path,
                idx + 1,
                "aws_lb_listener.vpn must send local.common_tags at creation time",
            )
        ]
    return [
        Violation(path, 1, "aws_lb_listener.vpn is required for VPN ELB scope checking")
    ]


def check_file(path: Path, resource_name: str = "gwlb") -> list[Violation]:
    lines = path.read_text().splitlines()
    if path.name == "vpn.tf":
        return _check_vpn_listener_tags(path, lines)
    policy = _extract_policy_body(lines, resource_name)
    if policy is None:
        return [Violation(path, 1, f"aws_iam_policy.{resource_name} is required")]

    policy_start_line, policy_lines = policy
    violations: list[Violation] = []
    for relative_line, block in _extract_statement_blocks(policy_lines):
        line = policy_start_line + relative_line - 1
        violations.extend(_check_statement(path, line, block))
    violations.extend(_vpn_contract_violations(path, policy_start_line, policy_lines))
    return violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: check_tf_iam_elb_scope.py FILE.tf [FILE.tf ...]",
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
            f"ELBv2 IAM scope violations ({len(violations)} total):",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
