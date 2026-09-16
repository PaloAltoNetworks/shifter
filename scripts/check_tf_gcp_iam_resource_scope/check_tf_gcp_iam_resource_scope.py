#!/usr/bin/env python3
"""Reject project-scoped Secret Manager / Cloud Storage grants on GCP workloads.

ADR-008-R7 (docs/architecture/gcp-workload-resource-iam-preflight-1517.md): the
four GCP application workload identities -- ``portal``, ``workers``,
``ctf-scheduler``, and ``provisioner`` -- must not receive project-level Secret
Manager payload/admin roles or Cloud Storage object-admin roles. Static runtime
access is bound on each named secret or bucket instead. Dynamic range secrets
use the completed #1586/#2083 boundary: create-only permission in one
deployment-scoped project, condition-scoped lifecycle permission, and a narrow
participant-read condition for the portal.

The guard fails closed on every shape that attaches a forbidden role to a
workload identity at project scope:

* a literal ``google_project_iam_member`` / ``google_project_iam_binding`` whose
  ``role`` is a forbidden predefined role and whose member is a workload SA;
* the ``for_each`` construction that iterates a ``local`` role map (the forbidden
  role is read out of the map, so renaming the resource does not bypass it);
* an authoritative ``google_project_iam_policy`` binding block;
* a project-scoped ``google_project_iam_custom_role`` whose ``permissions`` grant
  equivalent access outside the exact validated dynamic-secret boundary.

Legitimate different principals (the range-Vertex SA, the GKE node SA, and
CI/bootstrap identities) are not workload identities and are not matched.

The ``range_host`` / ``range_host_pool`` identities are handled separately (#1644):
they are attached to participant-controllable range guests, so ANY project-level
Cloud Storage role (including read-only ``objectViewer``) is rejected on them --
via the same direct-member, inline ``for_each`` role list, local-map,
policy-binding, and custom-role shapes -- while their logging/monitoring writes
are left alone. Host artifacts reach these guests through short-lived signed URLs.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

WORKLOAD_KEYS = frozenset({"portal", "workers", "ctf-scheduler", "provisioner"})

FORBIDDEN_SECRET_ROLES = frozenset(
    {
        "roles/secretmanager.admin",
        "roles/secretmanager.secretAccessor",
        "roles/secretmanager.secretVersionManager",
    }
)
FORBIDDEN_STORAGE_ROLES = frozenset(
    {
        "roles/storage.admin",
        "roles/storage.objectAdmin",
        "roles/storage.objectCreator",
        "roles/storage.objectUser",
    }
)
FORBIDDEN_ROLES = FORBIDDEN_SECRET_ROLES | FORBIDDEN_STORAGE_ROLES

# Custom-role permissions that grant equivalent secret payload/lifecycle,
# object-mutation, or service-account IAM-admin access. A project-scoped custom
# role bound to a workload SA is a violation if it carries any of these (or a
# matching wildcard). The service-account permissions close ADR-008-R7's
# gateway-identity escalation: project-level setIamPolicy/create/delete let a
# workload seize any service account (GCP cannot resource-name-scope
# setIamPolicy), so the OpenVPN gateway uses a pre-provisioned per-SA pool
# instead of a dynamic-creation custom role.
FORBIDDEN_CUSTOM_PERMISSIONS = frozenset(
    {
        "secretmanager.versions.access",
        "secretmanager.secrets.setIamPolicy",
        "secretmanager.secrets.create",
        "secretmanager.secrets.delete",
        "secretmanager.versions.add",
        "secretmanager.versions.destroy",
        "storage.objects.create",
        "storage.objects.delete",
        "storage.objects.update",
        "storage.objects.setIamPolicy",
        "iam.serviceAccounts.create",
        "iam.serviceAccounts.delete",
        "iam.serviceAccounts.setIamPolicy",
        "iam.serviceAccounts.actAs",
    }
)
_FORBIDDEN_PERMISSION_WILDCARD_PREFIXES = ("secretmanager.", "storage.objects.")

# Range-host principals (#1644). ``range_host`` and the ``range_host_pool`` members
# are the service accounts attached to participant-controllable POLARIS/GCE range
# guests. They are NOT application workloads, but a participant with root on a
# guest can mint the attached SA token from the metadata server, so they must
# never hold a project-level Cloud Storage role: a project (or shared-bucket)
# storage grant crosses the range/tenant boundary and exposes other tenants'
# objects and Terraform state. Host artifacts are delivered as short-lived signed
# URLs instead. Their only legitimate project roles are logging/monitoring writes.
_RANGE_HOST_MEMBER_RE = re.compile(r"google_service_account\.range_host(?:_pool)?\b")


_ALLOWED_DYNAMIC_BINDINGS = frozenset(
    {
        "portal_dynamic_secret_accessor",
        "portal_legacy_dynamic_secret_accessor",
        "provisioner_dynamic_secret_create",
        "provisioner_dynamic_secret_lifecycle",
        "provisioner_legacy_dynamic_secret_lifecycle",
    }
)

_DYNAMIC_LIFECYCLE_PERMISSIONS = frozenset(
    {
        "secretmanager.secrets.delete",
        "secretmanager.secrets.get",
        "secretmanager.secrets.getIamPolicy",
        "secretmanager.secrets.setIamPolicy",
        "secretmanager.secrets.update",
        "secretmanager.versions.access",
        "secretmanager.versions.add",
    }
)

_IAM_CONDITION_LOGICAL_OPERATOR_LIMIT = 12
_LOGICAL_OPERATOR_RE = re.compile(r"&&|\|\||!(?!=)")

_DYNAMIC_CONDITION_LOCALS = {
    "dynamic_secret_project_is_dedicated": "var.dynamic_secret_project_id != var.project_id",
    "canonical_secret_prefix": (
        '"projects/${data.google_project.dynamic_secrets.number}/secrets/'
        'shifter-${var.environment}-dynamic-"'
    ),
    "canonical_participant_secret_prefix": (
        '"${local.canonical_secret_prefix}participant-"'
    ),
    "legacy_secret_prefixes": """[
        "projects/${data.google_project.platform.number}/secrets/shifter-range-",
        "projects/${data.google_project.platform.number}/secrets/shifter-${var.environment}-range-",
        "projects/${data.google_project.platform.number}/secrets/shifter-${var.environment}-ngfw-user-",
    ]""",
    "legacy_secret_name_condition": """join(" || ", [
        for prefix in local.legacy_secret_prefixes :
        "resource.name.startsWith('${prefix}')"
    ])""",
    "legacy_raes_directory_name_condition": (
        "\"resource.name.extract('projects/${data.google_project.platform.number}/secrets/"
        "shifter-range-{range_scope}-raes-domain-') == ''\""
    ),
    "legacy_secret_version_id": "\"resource.name.extract('/secrets/{secret_id}/versions/')\"",
    "legacy_participant_secret_condition": """join(" || ", [
        "(resource.name.startsWith('${local.legacy_secret_prefixes[0]}') && (${local.legacy_secret_version_id}.endsWith('-participant-ssh') || ${local.legacy_secret_version_id}.endsWith('-rdp-password') || ${local.legacy_secret_version_id}.endsWith('-profile') || ((${local.legacy_raes_directory_name_condition}) && (${local.legacy_secret_version_id}.endsWith('-account-password') || ${local.legacy_secret_version_id}.endsWith('-account-publickey')))))",
        "(resource.name.startsWith('${local.legacy_secret_prefixes[1]}') && (${local.legacy_secret_version_id}.endsWith('-ssh') || ${local.legacy_secret_version_id}.endsWith('-rdp-password')))",
        "(resource.name.startsWith('${local.legacy_secret_prefixes[2]}') && ${local.legacy_secret_version_id}.endsWith('-ssh'))",
    ])""",
    "dynamic_lifecycle_condition": """local.dynamic_secret_project_is_dedicated ? (
        "resource.name.startsWith('${local.canonical_secret_prefix}')"
    ) : (
        "(${local.legacy_secret_name_condition})"
    )""",
    "portal_dynamic_read_condition": """local.dynamic_secret_project_is_dedicated ? (
        "resource.name.startsWith('${local.canonical_participant_secret_prefix}')"
    ) : (
        "(${local.legacy_participant_secret_condition})"
    )""",
}

_PROJECT_IAM_MEMBER_RE = re.compile(
    r'^\s*resource\s+"google_project_iam_(?:member|binding)"\s+"([^"]+)"\s*\{'
)
_CUSTOM_ROLE_RE = re.compile(
    r'^\s*resource\s+"google_project_iam_custom_role"\s+"([^"]+)"\s*\{'
)
_WORKLOAD_MEMBER_RE = re.compile(
    r'google_service_account\.workload\[\s*"([\w-]+)"\s*\]'
)
_LITERAL_ROLE_RE = re.compile(r'\brole\s*=\s*"(roles/[^"]+)"')
_FOR_EACH_LOCAL_MAP_RE = re.compile(r"for\s+\w+\s*,\s*\w+\s+in\s+local\.(\w+)\b")
_CUSTOM_ROLE_REF_RE = re.compile(
    r"\brole\s*=\s*google_project_iam_custom_role\.(\w+)\.(?:id|name)"
)


@dataclass
class Violation:
    """A forbidden project-scoped grant found on a workload identity."""

    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        """Render as ``path:line: reason`` for CLI output."""
        return f"{self.file}:{self.line}: {self.reason}"


def _brace_delta(line: str) -> int:
    """Return the net change in brace depth contributed by ``line``."""
    return line.count("{") - line.count("}")


def _extract_resource_blocks(
    lines: list[str], header_re: re.Pattern[str]
) -> list[tuple[str, int, str]]:
    """Return ``(name, 1-indexed start line, block text)`` per matching resource."""
    blocks: list[tuple[str, int, str]] = []
    idx = 0
    while idx < len(lines):
        match = header_re.match(lines[idx])
        if not match:
            idx += 1
            continue
        start_line = idx + 1
        depth = _brace_delta(lines[idx])
        body = [lines[idx]]
        idx += 1
        while idx < len(lines) and depth > 0:
            depth += _brace_delta(lines[idx])
            body.append(lines[idx])
            idx += 1
        blocks.append((match.group(1), start_line, "\n".join(body)))
    return blocks


def _extract_named_block(text: str, name: str) -> str | None:
    """Return the brace-balanced inner text of ``<name> = { ... }`` or None."""
    match = re.search(r"(?:^|\W)" + re.escape(name) + r"\s*=\s*\{", text)
    if not match:
        return None
    cursor = match.end()
    depth = 1
    while cursor < len(text):
        if text[cursor] == "{":
            depth += 1
        elif text[cursor] == "}":
            depth -= 1
            if depth == 0:
                return text[match.end() : cursor]
        cursor += 1
    return None


def _permission_is_forbidden(permission: str) -> bool:
    """True if a custom-role permission grants forbidden secret/object access."""
    if permission in FORBIDDEN_CUSTOM_PERMISSIONS:
        return True
    if permission.endswith("*"):
        stem = permission.rstrip("*")
        return any(stem.startswith(p) for p in _FORBIDDEN_PERMISSION_WILDCARD_PREFIXES)
    return False


def _residual_violation(
    path: Path, line: int, workload: str, role: str, shape: str
) -> Violation | None:
    """Return a violation for a generic project-scoped forbidden grant."""
    return Violation(
        path,
        line,
        f"{shape} grants project-level {role} to the {workload} workload "
        "identity. Bind static access on the named resource or use the exact "
        "validated dynamic-secret boundary (ADR-008-R7/#2083).",
    )


def _binds_workload_identity(body: str) -> bool:
    """True if a resource block binds a member to a workload service account."""
    return bool(_WORKLOAD_MEMBER_RE.search(body)) or "workload[each" in body


def _violations_for_workload_roles(
    path: Path, line: int, workload: str, roles: list[str], shape: str
) -> list[Violation]:
    """Return residual-filtered violations for one workload's forbidden roles."""
    out: list[Violation] = []
    for role in roles:
        if role not in FORBIDDEN_ROLES:
            continue
        found = _residual_violation(path, line, workload, role, shape)
        if found is not None:
            out.append(found)
    return out


def _check_map_driven_members(
    path: Path, lines: list[str], locals_text: str
) -> list[Violation]:
    """Flag forbidden roles reached through a ``for_each`` over a local role map."""
    violations: list[Violation] = []
    for _name, line, body in _extract_resource_blocks(lines, _PROJECT_IAM_MEMBER_RE):
        map_match = _FOR_EACH_LOCAL_MAP_RE.search(body)
        if not _binds_workload_identity(body) or not map_match:
            continue
        role_map = _parse_role_map(locals_text, map_match.group(1))
        for workload, roles in role_map.items():
            if workload in WORKLOAD_KEYS:
                violations.extend(
                    _violations_for_workload_roles(
                        path, line, workload, roles, "local role map"
                    )
                )
    return violations


def _parse_role_map(locals_text: str, map_name: str) -> dict[str, list[str]]:
    """Parse ``<map_name> = { key = toset([...]) ... }`` into key -> role strings."""
    body = _extract_named_block(locals_text, map_name)
    if body is None:
        return {}
    result: dict[str, list[str]] = {}
    entry_re = re.compile(r'(?:^|\n)\s*("?[\w-]+"?)\s*=\s*(?:toset\()?\[')
    for match in entry_re.finditer(body):
        key = match.group(1).strip('"')
        roles = _collect_roles_after(body, match.end())
        if roles:
            result.setdefault(key, []).extend(roles)
    return result


def _collect_roles_after(text: str, start: int) -> list[str]:
    """Return ``roles/...`` strings inside the bracket opened just before ``start``."""
    depth = 1
    cursor = start
    while cursor < len(text) and depth > 0:
        if text[cursor] == "[":
            depth += 1
        elif text[cursor] == "]":
            depth -= 1
        cursor += 1
    segment = text[start:cursor]
    return re.findall(r'"(roles/[^"]+)"', segment)


def _literal_string_list_assignment(body: str, key: str) -> set[str] | None:
    """Return every literal in one ``key = [...]`` assignment, or None."""
    match = re.search(
        rf"^\s*{re.escape(key)}\s*=\s*\[",
        body,
        flags=re.MULTILINE,
    )
    if match is None:
        return None
    depth = 1
    cursor = match.end()
    while cursor < len(body) and depth > 0:
        if body[cursor] == "[":
            depth += 1
        elif body[cursor] == "]":
            depth -= 1
        cursor += 1
    if depth != 0:
        return None
    return set(re.findall(r'"([^"]+)"', body[match.end() : cursor - 1]))


def _check_literal_members(path: Path, lines: list[str]) -> list[Violation]:
    """Flag literal member/binding resources granting a forbidden role to a workload."""
    violations: list[Violation] = []
    for name, line, body in _extract_resource_blocks(lines, _PROJECT_IAM_MEMBER_RE):
        if name in _ALLOWED_DYNAMIC_BINDINGS:
            continue
        role_match = _LITERAL_ROLE_RE.search(body)
        if not role_match or role_match.group(1) not in FORBIDDEN_ROLES:
            continue
        role = role_match.group(1)
        for workload in sorted(set(_WORKLOAD_MEMBER_RE.findall(body))):
            if workload not in WORKLOAD_KEYS:
                continue
            found = _residual_violation(path, line, workload, role, "resource")
            if found is not None:
                violations.append(found)
    return violations


def _check_policy_bindings(path: Path, text: str) -> list[Violation]:
    """Flag authoritative ``binding { role, members }`` policy grants on workloads.

    Covers the ``data "google_iam_policy"`` / ``google_project_iam_policy`` shape
    wherever the ``binding`` sub-block appears in the file.
    """
    violations: list[Violation] = []
    for binding_match in re.finditer(r"(?:^|\n)\s*binding\s*\{", text):
        block = _extract_brace_block(text, binding_match.end())
        role_match = re.search(r'role\s*=\s*"(roles/[^"]+)"', block)
        if not role_match or role_match.group(1) not in FORBIDDEN_ROLES:
            continue
        role = role_match.group(1)
        line = text.count("\n", 0, binding_match.start()) + 1
        for workload in sorted(set(_WORKLOAD_MEMBER_RE.findall(block))):
            if workload not in WORKLOAD_KEYS:
                continue
            found = _residual_violation(path, line, workload, role, "policy binding")
            if found is not None:
                violations.append(found)
    return violations


def _extract_brace_block(text: str, start: int) -> str:
    """Return the brace-balanced text following an opening brace at ``start``."""
    depth = 1
    cursor = start
    while cursor < len(text) and depth > 0:
        if text[cursor] == "{":
            depth += 1
        elif text[cursor] == "}":
            depth -= 1
        cursor += 1
    return text[start:cursor]


def _forbidden_custom_roles(lines: list[str]) -> set[str]:
    """Return local names of custom roles whose permissions are forbidden."""
    forbidden: set[str] = set()
    for name, _line, body in _extract_resource_blocks(lines, _CUSTOM_ROLE_RE):
        for permission in re.findall(r'"([\w.*]+)"', body):
            if _permission_is_forbidden(permission):
                forbidden.add(name)
                break
    return forbidden


def _check_custom_role_bindings(path: Path, lines: list[str]) -> list[Violation]:
    """Flag workload bindings of a project-scoped custom role with forbidden perms."""
    forbidden_roles = _forbidden_custom_roles(lines)
    if not forbidden_roles:
        return []
    violations: list[Violation] = []
    for name, line, body in _extract_resource_blocks(lines, _PROJECT_IAM_MEMBER_RE):
        if name in _ALLOWED_DYNAMIC_BINDINGS:
            continue
        ref_match = _CUSTOM_ROLE_REF_RE.search(body)
        if not ref_match or ref_match.group(1) not in forbidden_roles:
            continue
        for workload in sorted(set(_WORKLOAD_MEMBER_RE.findall(body))):
            if workload in WORKLOAD_KEYS:
                violations.append(
                    Violation(
                        path,
                        line,
                        f"custom role {ref_match.group(1)} grants forbidden "
                        f"secret/object permissions to the {workload} workload "
                        "identity at project scope (ADR-008-R7).",
                    )
                )
    return violations


def _collect_locals_text(files: dict[Path, list[str]]) -> str:
    """Concatenate the locals blocks across the file set.

    Sharing locals means a role map declared in one file is resolved for a
    ``for_each`` resource that consumes it in a sibling file, so a grant cannot
    hide by splitting the map and its consumer across files.
    """
    blocks: list[str] = []
    for lines in files.values():
        blocks.extend(
            body
            for _n, _l, body in _extract_resource_blocks(
                lines, re.compile(r"^(locals)\s*\{")
            )
        )
    return "\n".join(blocks)


def _is_range_host_forbidden_role(role: str) -> bool:
    """True for any project-level Cloud Storage role on a range-host identity.

    Range hosts hold zero legitimate project storage access (#1644), so every
    ``roles/storage.*`` role -- including the read-only ``objectViewer`` that the
    workload set deliberately permits per named bucket -- is forbidden here.
    """
    return role.startswith("roles/storage.")


def _resource_granted_roles(body: str) -> list[str]:
    """Return the role strings a project_iam_member/binding block grants directly.

    Covers a literal ``role = "roles/..."`` and the inline
    ``for_each = toset([...roles...])`` / ``for_each = [...]`` shape whose
    ``role = each.value`` iterates role strings directly -- the shape the
    range-host grant uses, which neither the literal nor the local-map workload
    check inspects. Local-map-driven roles are resolved separately.
    """
    roles: list[str] = []
    literal = _LITERAL_ROLE_RE.search(body)
    if literal:
        roles.append(literal.group(1))
    if re.search(r"\brole\s*=\s*each\.value\b", body):
        for_each = re.search(r"for_each\s*=\s*(?:toset\(\s*)?\[", body)
        if for_each:
            roles.extend(_collect_roles_after(body, for_each.end()))
    return roles


def _check_range_host_members(
    path: Path, lines: list[str], locals_text: str
) -> list[Violation]:
    """Flag project-level storage roles bound to a range-host identity (#1644)."""
    violations: list[Violation] = []
    for _name, line, body in _extract_resource_blocks(lines, _PROJECT_IAM_MEMBER_RE):
        if not _RANGE_HOST_MEMBER_RE.search(body):
            continue
        roles = list(_resource_granted_roles(body))
        map_match = _FOR_EACH_LOCAL_MAP_RE.search(body)
        if map_match:
            for mapped in _parse_role_map(locals_text, map_match.group(1)).values():
                roles.extend(mapped)
        for role in sorted({r for r in roles if _is_range_host_forbidden_role(r)}):
            violations.append(
                Violation(
                    path,
                    line,
                    f"resource grants project-level {role} to a range-host "
                    "identity. Range guests are participant-reachable; deliver the "
                    "artifact via a short-lived signed URL and keep the SA free of "
                    "project storage roles (#1644).",
                )
            )
    return violations


def _check_range_host_policy_bindings(path: Path, text: str) -> list[Violation]:
    """Flag authoritative policy bindings granting storage to a range-host identity."""
    violations: list[Violation] = []
    for binding_match in re.finditer(r"(?:^|\n)\s*binding\s*\{", text):
        block = _extract_brace_block(text, binding_match.end())
        role_match = re.search(r'role\s*=\s*"(roles/[^"]+)"', block)
        if not role_match or not _is_range_host_forbidden_role(role_match.group(1)):
            continue
        if _RANGE_HOST_MEMBER_RE.search(block):
            line = text.count("\n", 0, binding_match.start()) + 1
            violations.append(
                Violation(
                    path,
                    line,
                    f"policy binding grants project-level {role_match.group(1)} to "
                    "a range-host identity (#1644).",
                )
            )
    return violations


def _forbidden_range_host_custom_roles(lines: list[str]) -> set[str]:
    """Return custom-role names whose permissions grant any Cloud Storage access."""
    forbidden: set[str] = set()
    for name, _line, body in _extract_resource_blocks(lines, _CUSTOM_ROLE_RE):
        for permission in re.findall(r'"([\w.*]+)"', body):
            stem = permission.rstrip("*")
            if permission.startswith("storage.") or (
                permission.endswith("*") and "storage.".startswith(stem)
            ):
                forbidden.add(name)
                break
    return forbidden


def _check_range_host_custom_role_bindings(
    path: Path, lines: list[str]
) -> list[Violation]:
    """Flag range-host bindings of a project-scoped custom role with storage perms."""
    forbidden_roles = _forbidden_range_host_custom_roles(lines)
    if not forbidden_roles:
        return []
    violations: list[Violation] = []
    for _name, line, body in _extract_resource_blocks(lines, _PROJECT_IAM_MEMBER_RE):
        ref_match = _CUSTOM_ROLE_REF_RE.search(body)
        if not ref_match or ref_match.group(1) not in forbidden_roles:
            continue
        if _RANGE_HOST_MEMBER_RE.search(body):
            violations.append(
                Violation(
                    path,
                    line,
                    f"custom role {ref_match.group(1)} grants project-level Cloud "
                    "Storage access to a range-host identity (#1644).",
                )
            )
    return violations


def _has_exact_assignment(body: str, key: str, expected: str) -> bool:
    """Return true only when ``key`` has one one-line assignment to ``expected``."""
    values = re.findall(
        rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$", body, flags=re.MULTILINE
    )
    return values == [expected]


def _normalize_hcl_expression(expression: str) -> str:
    """Collapse formatting whitespace while retaining every HCL token."""
    return " ".join(expression.split())


def _delimiter_delta(expression: str) -> int:
    """Return the net bracket depth for one HCL expression fragment."""
    return sum(expression.count(char) for char in "([{") - sum(
        expression.count(char) for char in ")]}"
    )


def _extract_condition_local_assignments(
    files: dict[Path, list[str]],
) -> dict[str, list[tuple[Path, int, str]]]:
    """Parse the closed condition-local expressions from every ``locals`` block."""
    assignments = {name: [] for name in _DYNAMIC_CONDITION_LOCALS}
    locals_header = re.compile(r"^\s*locals\s*\{")
    assignment = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
    for path, lines in files.items():
        index = 0
        while index < len(lines):
            if not locals_header.match(lines[index]):
                index += 1
                continue
            block_depth = _brace_delta(lines[index])
            index += 1
            while index < len(lines) and block_depth > 0:
                line = lines[index]
                if block_depth == 1 and (match := assignment.match(line)):
                    name, first_fragment = match.groups()
                    if name in assignments:
                        start_line = index + 1
                        fragments = [first_fragment]
                        expression_depth = _delimiter_delta(first_fragment)
                        while expression_depth > 0 and index + 1 < len(lines):
                            index += 1
                            fragments.append(lines[index].strip())
                            expression_depth += _delimiter_delta(lines[index])
                        assignments[name].append(
                            (path, start_line, "\n".join(fragments))
                        )
                        index += 1
                        continue
                block_depth += _brace_delta(line)
                index += 1
    return assignments


def _condition_local_violations(
    files: dict[Path, list[str]], fallback_path: Path
) -> list[Violation]:
    """Require the exact inputs and compositions for the #2083 IAM conditions."""
    violations: list[Violation] = []
    assignments = _extract_condition_local_assignments(files)
    for name, expected in _DYNAMIC_CONDITION_LOCALS.items():
        found = assignments[name]
        if len(found) != 1:
            violations.append(
                Violation(
                    fallback_path,
                    1,
                    f"#2083 dynamic-secret boundary requires exactly one condition local {name}; found {len(found)}",
                )
            )
            continue
        path, line, actual = found[0]
        if _normalize_hcl_expression(actual) != _normalize_hcl_expression(expected):
            violations.append(
                Violation(
                    path,
                    line,
                    f"#2083 dynamic-secret condition local {name} differs from the closed definition",
                )
            )
    participant = assignments["legacy_participant_secret_condition"]
    raes_exclusion = assignments["legacy_raes_directory_name_condition"]
    if len(participant) == 1 and len(raes_exclusion) == 1:
        path, line, participant_expression = participant[0]
        _raes_path, _raes_line, raes_expression = raes_exclusion[0]
        # The HCL join delimiter appears once in source but expands between all
        # list elements. The interpolated RAES classifier may contribute
        # operators of its own; the secret-only roles need no type conjunction.
        clause_count = participant_expression.count('"(resource.name.startsWith')
        operator_count = (
            len(_LOGICAL_OPERATOR_RE.findall(participant_expression))
            + max(0, clause_count - 2)
            + len(_LOGICAL_OPERATOR_RE.findall(raes_expression))
        )
        if operator_count > _IAM_CONDITION_LOGICAL_OPERATOR_LIMIT:
            violations.append(
                Violation(
                    path,
                    line,
                    "#2083 legacy portal IAM condition expands to "
                    f"{operator_count} logical operators; Google permits at most "
                    f"{_IAM_CONDITION_LOGICAL_OPERATOR_LIMIT}",
                )
            )
    return violations


def _dynamic_boundary_errors(name: str, body: str) -> list[str]:
    """Validate one named #2083 boundary binding against its exact shape."""
    specs = {
        "provisioner_dynamic_secret_create": (
            "var.dynamic_secret_project_id",
            "provisioner",
            "google_project_iam_custom_role.dynamic_secret_creator.id",
            None,
        ),
        "provisioner_dynamic_secret_lifecycle": (
            "var.dynamic_secret_project_id",
            "provisioner",
            "google_project_iam_custom_role.dynamic_secret_lifecycle.id",
            "local.dynamic_lifecycle_condition",
        ),
        "portal_dynamic_secret_accessor": (
            "var.dynamic_secret_project_id",
            "portal",
            '"roles/secretmanager.secretAccessor"',
            "local.portal_dynamic_read_condition",
        ),
        "provisioner_legacy_dynamic_secret_lifecycle": (
            "var.project_id",
            "provisioner",
            "google_project_iam_custom_role.legacy_dynamic_secret_lifecycle[0].id",
            "\"(${local.legacy_secret_name_condition})\"",
        ),
        "portal_legacy_dynamic_secret_accessor": (
            "var.project_id",
            "portal",
            '"roles/secretmanager.secretAccessor"',
            "\"(${local.legacy_participant_secret_condition})\"",
        ),
    }
    project, workload, role, condition = specs[name]
    errors: list[str] = []
    if not body.lstrip().startswith('resource "google_project_iam_member"'):
        errors.append("must use additive google_project_iam_member")
    if not _has_exact_assignment(body, "project", project):
        errors.append(f"project must be {project}")
    expected_member = (
        f'"serviceAccount:${{google_service_account.workload["{workload}"].email}}"'
    )
    if not _has_exact_assignment(body, "member", expected_member):
        errors.append(f"member must be the {workload} workload identity")
    if not _has_exact_assignment(body, "role", role):
        errors.append(f"role must be {role}")
    if re.search(r"^\s*members\s*=", body, flags=re.MULTILINE) or "for_each" in body:
        errors.append("must not add members or expand with for_each")
    expected_count = "local.dynamic_secret_project_is_dedicated ? 1 : 0"
    if name in {
        "portal_legacy_dynamic_secret_accessor",
        "provisioner_legacy_dynamic_secret_lifecycle",
    }:
        if not _has_exact_assignment(body, "count", expected_count):
            errors.append("legacy binding must exist only while projects differ")
    elif re.search(r"^\s*count\s*=", body, flags=re.MULTILINE):
        errors.append("dedicated binding must not be conditional")
    if condition is None:
        if "condition {" in body:
            errors.append("create-only parent grant must be unconditioned")
    else:
        if body.count("condition {") != 1 or not _has_exact_assignment(
            body, "expression", condition
        ):
            errors.append(f"condition expression must be exactly {condition}")
    return errors


def _check_dynamic_resource_scope(files: dict[Path, list[str]]) -> list[Violation]:
    """Allow only the exact create/lifecycle/read graph designed by #1586/#2083."""
    violations: list[Violation] = []
    combined = "\n".join("\n".join(lines) for lines in files.values())
    if not files:
        return violations
    fallback_path = next(iter(files))
    binding_occurrences: dict[str, int] = {
        name: 0 for name in _ALLOWED_DYNAMIC_BINDINGS
    }
    custom_role_occurrences = {
        "dynamic_secret_creator": 0,
        "dynamic_secret_lifecycle": 0,
        "legacy_dynamic_secret_lifecycle": 0,
    }

    for path, lines in files.items():
        for name, line, body in _extract_resource_blocks(lines, _PROJECT_IAM_MEMBER_RE):
            if name not in _ALLOWED_DYNAMIC_BINDINGS:
                continue
            binding_occurrences[name] += 1
            for error in _dynamic_boundary_errors(name, body):
                violations.append(
                    Violation(
                        path,
                        line,
                        f"invalid #2083 dynamic-secret binding {name}: {error}",
                    )
                )

        custom_roles = {
            name: (line, body)
            for name, line, body in _extract_resource_blocks(lines, _CUSTOM_ROLE_RE)
        }
        for name in custom_role_occurrences:
            custom_role_occurrences[name] += int(name in custom_roles)
        creator = custom_roles.get("dynamic_secret_creator")
        if creator is not None:
            line, body = creator
            permissions = _literal_string_list_assignment(body, "permissions")
            if permissions != {
                "secretmanager.secrets.create"
            } or not _has_exact_assignment(
                body, "project", "var.dynamic_secret_project_id"
            ):
                violations.append(
                    Violation(
                        path,
                        line,
                        "dynamic_secret_creator must contain only secretmanager.secrets.create in var.dynamic_secret_project_id",
                    )
                )
        lifecycle = custom_roles.get("dynamic_secret_lifecycle")
        if lifecycle is not None:
            line, body = lifecycle
            permissions = _literal_string_list_assignment(body, "permissions")
            if (
                permissions != _DYNAMIC_LIFECYCLE_PERMISSIONS
                or not _has_exact_assignment(
                    body, "project", "var.dynamic_secret_project_id"
                )
            ):
                violations.append(
                    Violation(
                        path,
                        line,
                        "dynamic_secret_lifecycle permissions/project differ from the closed #2083 set",
                    )
                )
        legacy = custom_roles.get("legacy_dynamic_secret_lifecycle")
        if legacy is not None:
            line, body = legacy
            if not _has_exact_assignment(
                body, "project", "var.project_id"
            ) or not _has_exact_assignment(
                body,
                "permissions",
                "google_project_iam_custom_role.dynamic_secret_lifecycle.permissions",
            ):
                violations.append(
                    Violation(
                        path,
                        line,
                        "legacy_dynamic_secret_lifecycle must reuse the closed lifecycle set in var.project_id",
                    )
                )

    boundary_present = any(
        name in combined for name in _ALLOWED_DYNAMIC_BINDINGS
    ) or any(name in combined for name in custom_role_occurrences)
    if boundary_present:
        for name, count in {**binding_occurrences, **custom_role_occurrences}.items():
            if count != 1:
                violations.append(
                    Violation(
                        fallback_path,
                        1,
                        f"#2083 dynamic-secret boundary requires exactly one {name} resource; found {count}",
                    )
                )
        required_tokens = (
            "canonical_secret_prefix",
            "canonical_participant_secret_prefix",
            "legacy_secret_name_condition",
            "legacy_raes_directory_name_condition",
            "legacy_participant_secret_condition",
        )
        for token in required_tokens:
            if token not in combined:
                violations.append(
                    Violation(
                        fallback_path,
                        1,
                        f"#2083 dynamic-secret boundary is missing required condition token {token}",
                    )
                )
        violations.extend(_condition_local_violations(files, fallback_path))
    return violations


def _check_model_broker_scope(path: Path, lines: list[str]) -> list[Violation]:
    """Model identities have a closed resource/permission matrix (ADR-059)."""
    violations: list[Violation] = []
    header = re.compile(r'^\s*resource\s+"[^"\n]+"\s+"([^"\n]+)"\s*\{')
    allowed = {
        "google_service_account_iam_member": (
            {
                "service_account_id": "google_service_account.model_invocation[each.key].name",
                "role": "google_project_iam_custom_role.model_token[each.key].name",
                "member": '"serviceAccount:${google_service_account.model_broker[0].email}"',
            },
            {
                "service_account_id": "google_service_account.model_broker[0].name",
                "role": '"roles/iam.workloadIdentityUser"',
                "member": '"serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/model-broker]"',
            },
        ),
        "google_project_iam_member": (
            {
                "project": "each.key",
                "role": "google_project_iam_custom_role.model_invoke[each.key].name",
                "member": '"serviceAccount:${google_service_account.model_invocation[each.key].email}"',
            },
        ),
    }
    role_permissions = {
        "model_token": {"iam.serviceAccounts.getAccessToken"},
        "model_invoke": {"aiplatform.endpoints.predict"},
    }
    for name, line, body in _extract_resource_blocks(lines, header):
        resource_type = re.search(r'resource\s+"([^"\n]+)"', body).group(1)
        if (
            resource_type == "google_project_iam_custom_role"
            and name in role_permissions
        ):
            if (
                _literal_string_list_assignment(body, "permissions")
                != role_permissions[name]
            ):
                violations.append(
                    Violation(
                        path, line, "model custom role exceeds its exact permission set"
                    )
                )
        if not re.search(
            r"google_service_account\.model_(?:broker|invocation)\b", body
        ):
            continue
        if resource_type == "google_service_account":
            continue
        candidates = allowed.get(resource_type, ())
        if not any(
            all(
                _has_exact_assignment(body, key, value)
                for key, value in candidate.items()
            )
            for candidate in candidates
        ):
            violations.append(
                Violation(
                    path,
                    line,
                    "model identity grant is outside the exact broker/shard IAM matrix",
                )
            )
    return violations


def check_paths(paths: list[Path]) -> list[Violation]:
    """Return every ADR-008-R7 violation across a set of module Terraform files."""
    files = {p: p.read_text().splitlines() for p in paths if p.suffix == ".tf"}
    locals_text = _collect_locals_text(files)
    violations: list[Violation] = []
    violations.extend(_check_dynamic_resource_scope(files))
    for path, lines in files.items():
        violations.extend(_check_model_broker_scope(path, lines))
        violations.extend(_check_literal_members(path, lines))
        violations.extend(_check_map_driven_members(path, lines, locals_text))
        violations.extend(_check_policy_bindings(path, "\n".join(lines)))
        violations.extend(_check_custom_role_bindings(path, lines))
        violations.extend(_check_range_host_members(path, lines, locals_text))
        violations.extend(_check_range_host_policy_bindings(path, "\n".join(lines)))
        violations.extend(_check_range_host_custom_role_bindings(path, lines))
    return violations


def check_file(path: Path) -> list[Violation]:
    """Return every ADR-008-R7 violation in a single Terraform file."""
    return check_paths([path])


def main(argv: list[str]) -> int:
    """CLI entry point: exit 1 on any violation, 2 on usage/IO error."""
    if len(argv) < 2:
        print(
            "usage: check_tf_gcp_iam_resource_scope.py FILE.tf [FILE.tf ...]",
            file=sys.stderr,
        )
        return 2

    paths: list[Path] = []
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"{path}: file not found", file=sys.stderr)
            return 2
        if path.suffix == ".tf":
            paths.append(path)

    violations = check_paths(paths)
    if violations:
        print(
            f"GCP workload IAM resource-scope violations ({len(violations)} total):",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
