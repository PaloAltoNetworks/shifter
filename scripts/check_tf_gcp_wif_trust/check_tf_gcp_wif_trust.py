#!/usr/bin/env python3
"""Lint the GCP GitHub-Actions Workload Identity Federation trust (ADR-004-R23).

Credentialed GCP CI must establish reviewed-code provenance at the WIF trust
boundary, not inside dispatched workflow code (#1690). This guard pins the
`cicd-github-oidc` module to the exact-subject federation shape:

- the Workload Identity **provider** `attribute_condition` must gate on an exact
  protected `assertion.ref` (not repository-only), so a feature-branch or tag
  dispatch is denied at the pool even when its `environment:` `sub` matches;
- service-account WIF bindings (`roles/iam.workloadIdentityUser`) must name exact
  `principal://.../subject/<sub>` members, never a repository-wide
  `principalSet://.../attribute.repository/...` member; and
- the `CKV_GCP_125` repository-scope Checkov waiver must not survive, since the
  exact `assertion.ref`/`assertion.sub` pin satisfies it.

The check no-ops on Terraform that does not define these resources, so unrelated
modules and fixtures are unaffected. It mirrors the AWS
`check_tf_iam_role_naming` guard's comment-stripping discipline (no keying on
resource labels or prose).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

WIF_MODULE_GLOBS: tuple[str, ...] = (
    "platform/terraform/gcp/modules/cicd-github-oidc/*.tf",
)

PROVIDER_RE = re.compile(
    r'^\s*resource\s+"google_iam_workload_identity_pool_provider"\s+"([^"]+)"\s*\{'
)
SA_MEMBER_RE = re.compile(
    r'^\s*resource\s+"google_service_account_iam_member"\s+"([^"]+)"\s*\{'
)
WORKLOAD_IDENTITY_USER = "roles/iam.workloadIdentityUser"
# A repository-wide principalSet trusts every workflow/ref/actor in the repo; the
# exact-subject principal is the real impersonation boundary (ADR-004-R23).
FORBIDDEN_PRINCIPALSET = "principalSet://"
REPO_ATTRIBUTE = "attribute.repository/"
EXACT_SUBJECT_MARKER = "/subject/"
# The repository-scope waiver, matched as the Checkov skip directive (not the
# bare rule id) so prose naming the rule does not false-positive.
CKV_GCP_125_SKIP_RE = re.compile(r"checkov:skip\s*=\s*CKV_GCP_125")
# The static condition and the SA-binding list must not drift: the condition is
# written out literally (Checkov cannot render join()), so the guard compares the
# `assertion.sub == '<sub>'` clauses against the local.federated_subjects list.
SUBJECT_EQ_RE = re.compile(r"assertion\.sub\s*==\s*'([^']+)'")
# The ref gate may be inlined in the condition or factored into a `ref_condition`
# local (ADR-037-R7). Match the equality FORM, not the bare token, so the
# attribute_mapping (`"attribute.ref" = "assertion.ref"`) cannot false-pass it.
REF_EQ_RE = re.compile(r"assertion\.ref\s*==")
FEDERATED_LIST_RE = re.compile(r"federated_subjects\s*=\s*\[(.*?)\]", re.DOTALL)
DOUBLE_QUOTED_RE = re.compile(r'"([^"]+)"')
# The invariant checks scope to the attribute_condition VALUE, not the whole
# provider block: attribute_mapping maps assertion.sub/ref/repository regardless
# of the condition, so a block-wide token scan would pass even a repository-only
# condition (codex #1690 review). CEL literals use single quotes, so the HCL
# double-quoted value contains no inner `"` and `[^"]*` captures it whole.
ATTRIBUTE_CONDITION_RE = re.compile(r'attribute_condition\s*=\s*"([^"]*)"')


@dataclass
class Violation:
    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.reason}"


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _extract_resource_block(lines: list[str], start_idx: int) -> list[str]:
    depth = _brace_delta(lines[start_idx])
    idx = start_idx + 1
    while idx < len(lines) and depth > 0:
        depth += _brace_delta(lines[idx])
        idx += 1
    return lines[start_idx:idx]


def _strip_hcl_comments(text: str) -> str:
    """Drop `#` line comments so trust matching never keys on prose.

    `#` never appears inside the provider condition, principal members, or
    subjects the checks inspect, so this is a safe, precise strip. `//` / `/* */`
    stripping is intentionally avoided (a `principalSet://` member contains a
    literal `//`).
    """
    return "\n".join(re.sub(r"#.*$", "", line) for line in text.splitlines())


def _iter_resource_blocks(
    lines: list[str], header_re: re.Pattern[str]
) -> list[tuple[int, list[str]]]:
    blocks: list[tuple[int, list[str]]] = []
    idx = 0
    while idx < len(lines):
        if header_re.match(lines[idx]):
            block = _extract_resource_block(lines, idx)
            blocks.append((idx + 1, block))
            idx += len(block)
            continue
        idx += 1
    return blocks


def check_provider_condition(
    path: Path, lines: list[str], text: str
) -> list[Violation]:
    """WIF provider must pin an exact protected assertion.ref, not repo-only."""
    violations: list[Violation] = []
    # The ref gate may be factored into a `ref_condition` local (ADR-037-R7), so
    # its `assertion.ref ==` equality can live outside the provider block.
    file_has_ref_gate = bool(REF_EQ_RE.search(_strip_hcl_comments(text)))
    for line_no, block in _iter_resource_blocks(lines, PROVIDER_RE):
        raw = "\n".join(block)
        stripped = _strip_hcl_comments(raw)
        # The repository-scope Checkov waiver lives in a `#` comment, so scan the
        # RAW block text (before comment stripping) to catch a surviving skip.
        # Match the skip DIRECTIVE precisely so explanatory prose that names the
        # rule (e.g. "replaces the CKV_GCP_125 waiver") does not false-positive.
        if CKV_GCP_125_SKIP_RE.search(raw):
            violations.append(
                Violation(
                    path,
                    line_no,
                    "WIF provider must not retain the CKV_GCP_125 repository-scope "
                    "waiver once assertion.ref/sub are pinned (ADR-004-R23, #1690)",
                )
            )
        # Scope every invariant to the attribute_condition VALUE, not the whole
        # block: attribute_mapping maps assertion.sub/ref/repository regardless of
        # the condition (codex #1690 review). No static condition -> unguarded.
        condition_match = ATTRIBUTE_CONDITION_RE.search(stripped)
        if condition_match is None:
            violations.append(
                Violation(
                    path,
                    line_no,
                    "WIF provider must define a static attribute_condition string "
                    "(ADR-004-R23, #1690)",
                )
            )
            continue
        condition = condition_match.group(1)
        if "assertion.repository" not in condition:
            violations.append(
                Violation(
                    path,
                    line_no,
                    "WIF provider attribute_condition must gate on "
                    "assertion.repository (ADR-004-R23, #1690)",
                )
            )
        # The condition must WIRE the ref gate (inline assertion.ref or a
        # ref_condition local) AND that gate must actually be an assertion.ref ==
        # equality somewhere in the module (ADR-037-R7). Repository-only
        # federation is forbidden.
        wires_ref_gate = "assertion.ref" in condition or "ref_condition" in condition
        if not (wires_ref_gate and file_has_ref_gate):
            violations.append(
                Violation(
                    path,
                    line_no,
                    "WIF provider attribute_condition must pin an exact protected "
                    "assertion.ref (inline or via a ref_condition local); "
                    "repository-only federation is forbidden (ADR-004-R23, "
                    "ADR-037-R7)",
                )
            )
        # Checkov CKV_GCP_125 and the exact-subject intent both require a literal
        # `assertion.sub == '<sub>'` equality clause in the condition (not `in`).
        if not SUBJECT_EQ_RE.search(condition):
            violations.append(
                Violation(
                    path,
                    line_no,
                    "WIF provider attribute_condition must pin an exact "
                    "assertion.sub with a literal `assertion.sub ==` clause "
                    "(ADR-004-R23, #1690)",
                )
            )
    return violations


def check_sa_wif_members(path: Path, lines: list[str], text: str) -> list[Violation]:
    """WIF service-account bindings must use exact subject principals."""
    violations: list[Violation] = []
    wif_blocks = [
        (line_no, block)
        for line_no, block in _iter_resource_blocks(lines, SA_MEMBER_RE)
        if WORKLOAD_IDENTITY_USER in "\n".join(block)
    ]
    if not wif_blocks:
        return violations

    # A member may reference a `local.*` value, so a repository-wide principalSet
    # can hide in the module `locals` block. Scan the whole comment-stripped file
    # for the forbidden repo-wide member, then require an exact-subject member.
    file_compact = re.sub(r"\s+", "", _strip_hcl_comments(text))
    if FORBIDDEN_PRINCIPALSET in file_compact and REPO_ATTRIBUTE in file_compact:
        line_no = wif_blocks[0][0]
        violations.append(
            Violation(
                path,
                line_no,
                "WIF service-account binding must use exact "
                "principal://.../subject/<sub> members, never a repository-wide "
                "principalSet://.../attribute.repository/... member "
                "(ADR-004-R23, #1690)",
            )
        )
    if EXACT_SUBJECT_MARKER not in file_compact:
        line_no = wif_blocks[0][0]
        violations.append(
            Violation(
                path,
                line_no,
                "WIF service-account binding must name at least one exact "
                "principal://.../subject/<sub> member (ADR-004-R23, #1690)",
            )
        )
    return violations


def check_subject_consistency(path: Path, text: str) -> list[Violation]:
    """Static condition subjects must equal the local.federated_subjects list.

    The provider condition is written out literally (Checkov cannot render
    ``join()``), so this guard fails the build if the condition's
    ``assertion.sub == '<sub>'`` clauses and the single-source
    ``local.federated_subjects`` list diverge - which would silently strand or
    over-trust a caller. No-op unless both are present.
    """
    stripped = _strip_hcl_comments(text)
    list_match = FEDERATED_LIST_RE.search(stripped)
    condition_subs = set(SUBJECT_EQ_RE.findall(stripped))
    if list_match is None or not condition_subs:
        return []
    list_subs = set(DOUBLE_QUOTED_RE.findall(list_match.group(1)))
    if list_subs == condition_subs:
        return []
    missing_from_condition = list_subs - condition_subs
    extra_in_condition = condition_subs - list_subs
    detail = []
    if missing_from_condition:
        detail.append(
            f"missing from attribute_condition: {sorted(missing_from_condition)}"
        )
    if extra_in_condition:
        detail.append(f"not in local.federated_subjects: {sorted(extra_in_condition)}")
    return [
        Violation(
            path,
            1,
            "WIF attribute_condition subjects must equal local.federated_subjects "
            f"({'; '.join(detail)}) (ADR-004-R23, #1690)",
        )
    ]


def check_file(path: Path) -> list[Violation]:
    if path.suffix != ".tf":
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    violations = check_provider_condition(path, lines, text)
    violations.extend(check_sa_wif_members(path, lines, text))
    violations.extend(check_subject_consistency(path, text))
    return violations


def iter_target_files(repo_root: Path, argv: list[str]) -> list[Path]:
    if argv:
        return [Path(arg).resolve() for arg in argv]
    files: list[Path] = []
    for pattern in WIF_MODULE_GLOBS:
        files.extend(sorted(repo_root.glob(pattern)))
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
