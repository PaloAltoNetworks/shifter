#!/usr/bin/env python3
"""Reject project-scoped Secret Manager / Cloud Storage grants on GCP workloads.

ADR-008-R7 (docs/architecture/gcp-workload-resource-iam-preflight-1517.md): the
four GCP application workload identities -- ``portal``, ``workers``,
``ctf-scheduler``, and ``provisioner`` -- must not receive project-level Secret
Manager payload/admin roles or Cloud Storage object-admin roles. Static runtime
access is bound on each named secret or bucket instead; the only project-level
secret/storage grants permitted are the two dynamic-secret residuals tracked in
#1586 and enumerated in ``ALLOWLIST`` below.

The guard fails closed on every shape that attaches a forbidden role to a
workload identity at project scope:

* a literal ``google_project_iam_member`` / ``google_project_iam_binding`` whose
  ``role`` is a forbidden predefined role and whose member is a workload SA;
* the ``for_each`` construction that iterates a ``local`` role map (the forbidden
  role is read out of the map, so renaming the resource does not bypass it);
* an authoritative ``google_project_iam_policy`` binding block;
* a project-scoped ``google_project_iam_custom_role`` whose ``permissions`` grant
  equivalent secret payload/lifecycle or object-mutation access.

Legitimate different principals (the GCE range-host SA, the range-Vertex SA, the
GKE node SA, CI/bootstrap identities) are not workload identities and are not
matched. The two ``ALLOWLIST`` residuals carry an expiry so the exception cannot
outlive the #1586 boundary silently.
"""

from __future__ import annotations

import datetime
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

# Custom-role permissions that grant equivalent secret payload/lifecycle or
# object-mutation access. A project-scoped custom role bound to a workload SA is
# a violation if it carries any of these (or a matching wildcard).
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
    }
)
_FORBIDDEN_PERMISSION_WILDCARD_PREFIXES = ("secretmanager.", "storage.objects.")


@dataclass(frozen=True)
class _Residual:
    """A documented, expiring exception for one (workload, role) grant."""

    reason: str
    expires_on: datetime.date


# The only project-level secret/storage grants a workload identity may hold.
# Both are the dynamic-secret residuals whose resource-scoped replacement is
# designed in #1586; each expires so the guard forces a revisit.
ALLOWLIST: dict[tuple[str, str], _Residual] = {
    ("portal", "roles/secretmanager.secretAccessor"): _Residual(
        reason=(
            "portal reads per-range *-ssh / *-rdp-password guest credentials at "
            "runtime; dynamic-secret naming convergence / dedicated project "
            "tracked in #1586"
        ),
        expires_on=datetime.date(2027, 7, 11),
    ),
    ("provisioner", "roles/secretmanager.admin"): _Residual(
        reason=(
            "provisioner create/version/access/delete of per-range dynamic "
            "secrets + vertex-key setIamPolicy + operator GDC secret reads; "
            "dedicated-project boundary tracked in #1586"
        ),
        expires_on=datetime.date(2027, 7, 11),
    ),
}

_PROJECT_IAM_MEMBER_RE = re.compile(
    r'^\s*resource\s+"google_project_iam_(?:member|binding)"\s+"([^"]+)"\s*\{'
)
_CUSTOM_ROLE_RE = re.compile(
    r'^\s*resource\s+"google_project_iam_custom_role"\s+"([^"]+)"\s*\{'
)
_WORKLOAD_MEMBER_RE = re.compile(r'google_service_account\.workload\[\s*"([\w-]+)"\s*\]')
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
    """Return a Violation for a forbidden (workload, role) grant, or None if allowlisted.

    An allowlisted-but-expired residual is reported so the exception cannot
    outlive its #1586 review date.
    """
    residual = ALLOWLIST.get((workload, role))
    if residual is None:
        return Violation(
            path,
            line,
            f"{shape} grants project-level {role} to the {workload} workload "
            "identity. Bind it on the named secret/bucket instead "
            "(ADR-008-R7); only the #1586 dynamic-secret residuals are allowed.",
        )
    if datetime.date.today() > residual.expires_on:
        return Violation(
            path,
            line,
            f"{shape} grants project-level {role} to {workload} under an "
            f"ALLOWLIST residual that expired on {residual.expires_on.isoformat()}. "
            "Resolve #1586 or renew the exception.",
        )
    return None


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


def _check_literal_members(path: Path, lines: list[str]) -> list[Violation]:
    """Flag literal member/binding resources granting a forbidden role to a workload."""
    violations: list[Violation] = []
    for _name, line, body in _extract_resource_blocks(lines, _PROJECT_IAM_MEMBER_RE):
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
    for _name, line, body in _extract_resource_blocks(lines, _PROJECT_IAM_MEMBER_RE):
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
            for _n, _l, body in _extract_resource_blocks(lines, re.compile(r"^(locals)\s*\{"))
        )
    return "\n".join(blocks)


def check_paths(paths: list[Path]) -> list[Violation]:
    """Return every ADR-008-R7 violation across a set of module Terraform files."""
    files = {p: p.read_text().splitlines() for p in paths if p.suffix == ".tf"}
    locals_text = _collect_locals_text(files)
    violations: list[Violation] = []
    for path, lines in files.items():
        violations.extend(_check_literal_members(path, lines))
        violations.extend(_check_map_driven_members(path, lines, locals_text))
        violations.extend(_check_policy_bindings(path, "\n".join(lines)))
        violations.extend(_check_custom_role_bindings(path, lines))
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
