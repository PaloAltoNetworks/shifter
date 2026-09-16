"""Secret/artifact hygiene: tfvars secrets, secret env files, tracked generated artifacts."""
from __future__ import annotations

from pathlib import Path

from .._common import (
    Violation,
    _repo_relative,
)
from ._secret_hygiene_artifacts import (
    _GENERATED_ARTIFACT_PREDICATES,
    _GENERATED_ARTIFACT_ROOTS,
    _generated_artifact_match,
    _git_tracked_under_roots,
    _is_bootstrap_authcode_artifact,
    _is_polaris_build_artifact,
    _is_polaris_operator_run_artifact,
    _is_terraform_plan_artifact,
    _iter_artifact_candidates,
    _walk_filesystem_artifacts,
    check_no_tracked_generated_artifacts,
)
from ._secret_hygiene_git import _git_ls_files_stdout
from ._secret_hygiene_tfvars import (
    _BLOCK_COMMENT_PATTERN,
    _NON_SECRET_NAME_SUFFIXES,
    _SECRET_ASSIGNMENT_PATTERN,
    _SECRET_BLOCK_OPEN_PATTERN,
    _SECRET_HEREDOC_PATTERN,
    _SECRET_NAME_GROUP,
    _SECRET_VAR_PATTERN,
    _STRING_LITERAL_PATTERN,
    _TFVARS_SCOPE,
    _balance_scan,
    _block_assignment_has_literal,
    _block_depth_scan,
    _collect_tfvars_candidates,
    _find_balanced_close_index,
    _find_block_close_index,
    _flagged_secret_var,
    _is_line_commented,
    _is_public_material_name,
    _lines_have_string_literal,
    _scan_tfvars_file,
    _scrub_line,
    _strip_hcl_comments,
    _strip_trailing_line_comment,
    _wrapped_rhs_has_literal,
    check_no_plaintext_secrets_in_tfvars,
)


# Centralized scope for the `no-populated-secret-env-files` check
# (ADR-004-R9). Each entry is a repo-relative path prefix under which
# `*-secrets.env` files are scanned. Adding a future overlay (e.g.
# `platform/k8s/gcp/overlays/gcp-prod/`) is automatically covered;
# adding a new top-level location (e.g. a different cluster tree) is
# one entry here.
_SECRET_ENV_ROOTS: tuple[str, ...] = ("platform/k8s/",)

# Basename suffix that selects "secret env" files. Matched on the
# basename only so unrelated `*.env` files (config-bearing, not
# secret-bearing) are not scanned by this check.
_SECRET_ENV_SUFFIX = "-secrets.env"

# Fail-loud synthetic values that may appear as the RHS of an
# assignment in a tracked secret env file. The intent is that
# committed files render Kustomize / kube-linter / kubeconform
# successfully while making it obvious to anyone who deploys with the
# committed values that they have NOT supplied real secrets. Real
# values flow in at deploy time from GitHub Secrets, GCP Secret
# Manager, a gitignored local env file, or a deploy-time Kubernetes
# Secret.
#
# The allowlist is intentionally small and FIXED. Codex review cycle 3
# caught that an earlier `<...>` regex would accept any angle-bracket
# value (e.g. `DB_PASSWORD=<attacker-known-password>`) — a committer
# could wrap a real low-entropy credential in brackets, the guard
# would call it a placeholder, and Kustomize would treat the bracketed
# bytes as the literal Secret value at deploy. The bracket-syntax
# entries below are therefore an explicit fixed set, not a pattern.
# Broader synonyms must come through a deliberate ADR update, not
# ad-hoc growth.
_SECRET_ENV_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        # Bare placeholder tokens
        "REPLACE_AT_DEPLOY",
        "CHANGE_ME",
        "PLACEHOLDER",
        "EXAMPLE",
        # Equivalent bracketed forms (conventional in some example files);
        # the bracket allowlist is fixed, not pattern-based, to close the
        # angle-bracket bypass from cycle 3.
        "<replace-at-deploy>",
        "<replace_at_deploy>",
        "<REPLACE_AT_DEPLOY>",
        "<change-me>",
        "<change_me>",
        "<CHANGE_ME>",
        "<placeholder>",
        "<PLACEHOLDER>",
        "<example>",
        "<EXAMPLE>",
    }
)

def _is_secret_env_in_scope(rel_path: str) -> bool:
    """Return True for a repo-relative path that the secret-env check scans."""
    if not any(rel_path.startswith(root) for root in _SECRET_ENV_ROOTS):
        return False
    basename = rel_path.rsplit("/", 1)[-1]
    return basename.endswith(_SECRET_ENV_SUFFIX)


def _iter_secret_env_candidates(repo_root: Path) -> list[str]:
    """Return repo-relative paths of secret-env files in scope.

    Mirrors the tracked-only contract of
    `check_no_tracked_generated_artifacts`: prefer `git ls-files` so
    gitignored local-dev files (e.g. a developer's
    `platform-runtime-secrets.local.env`) are intentionally NOT
    scanned. Falls back to a filesystem walk only in the synthetic
    tmpdir test path where no `.git` directory exists.
    """
    tracked = _git_tracked_under_roots_for_secret_env(repo_root)
    if tracked is None:
        return _walk_filesystem_secret_env(repo_root)
    return [p for p in tracked if _is_secret_env_in_scope(p)]


def _git_tracked_under_roots_for_secret_env(repo_root: Path) -> list[str] | None:
    """Tracked + non-ignored repo-relative paths under the secret-env
    roots, or `None` if `repo_root` is not a git working tree."""
    stdout = _git_ls_files_stdout(repo_root, _SECRET_ENV_ROOTS)
    if stdout is None:
        return None
    return [entry.decode("utf-8") for entry in stdout.split(b"\x00") if entry]


def _walk_filesystem_secret_env(repo_root: Path) -> list[str]:
    """Test-mode fallback: walk the configured secret-env roots."""
    candidates: list[str] = []
    for root in _SECRET_ENV_ROOTS:
        base = repo_root / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = _repo_relative(path, repo_root)
            if _is_secret_env_in_scope(rel):
                candidates.append(rel)
    return candidates


def _is_synthetic_placeholder(value: str) -> bool:
    """Return True if `value` is an allowed fail-loud placeholder.

    The allowlist is a fixed set (see `_SECRET_ENV_PLACEHOLDERS`).
    Pattern-based bracket matching was removed in cycle 3 because it
    accepted arbitrary `<...>` content, which would allow a committer
    to hide a real credential as `<attacker-known-password>` and have
    the guardrail pass.
    """
    stripped = value.strip()
    if stripped == "":
        return True
    return stripped in _SECRET_ENV_PLACEHOLDERS


def _scan_secret_env_file(abs_path: Path, rel_path: str) -> list[Violation]:
    """Return violations for any populated, non-placeholder line.

    Parsing rules:

    - A line whose first non-whitespace character is `#`, or that is
      blank after strip, is a comment / blank and is skipped.
    - Any other line MUST contain `=` and is parsed by splitting on
      the first `=`. The LHS is treated as the variable name verbatim
      (any shape — `KEY`, `db.password`, `api-token`, `export KEY`)
      so non-identifier-key shapes cannot bypass the value check.
    - Inline `# ...` is NOT a comment. Kustomize's
      `secretGenerator.envs` loader follows the Docker env_file
      format: `#` is a comment only when it is the first non-
      whitespace character on a line; mid-line `#` is part of the
      value. Treating mid-line `#` as a comment would create a
      bypass (`TOKEN=#real-secret` would normalize to empty and pass
      the placeholder check while the bytes remain in source).
    - A non-comment, non-blank line that does NOT contain `=` is
      flagged as malformed so a committed value smuggled in via a
      non-`=` shape (free text, YAML, etc.) cannot slip past the
      value check.

    The violation message names the line number, the variable shape,
    and the path; it never echoes the rejected value, per the
    preflight contract that validation reports paths and variable
    names only.
    """
    violations: list[Violation] = []
    try:
        text = abs_path.read_text(encoding="utf-8")
    except OSError:
        return violations
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        if "=" not in stripped_line:
            violations.append(
                Violation(
                    check="no-populated-secret-env-files",
                    rule_id="ADR-004-R9",
                    path=rel_path,
                    message=(
                        f"Tracked secret-env line {lineno} is not a "
                        "comment, blank line, or `KEY=value` "
                        "assignment. Use one of the allowed synthetic "
                        "placeholders (REPLACE_AT_DEPLOY, CHANGE_ME, "
                        "PLACEHOLDER, EXAMPLE, or <placeholder>) or "
                        "remove the line."
                    ),
                )
            )
            continue
        key, _, rhs = line.partition("=")
        var_name = key.strip()
        if _is_synthetic_placeholder(rhs):
            continue
        violations.append(
            Violation(
                check="no-populated-secret-env-files",
                rule_id="ADR-004-R9",
                path=rel_path,
                message=(
                    f"Tracked secret-env assignment `{var_name}` "
                    f"(line {lineno}) has a non-placeholder value. "
                    "Replace with an allowed synthetic placeholder "
                    "(REPLACE_AT_DEPLOY, CHANGE_ME, PLACEHOLDER, "
                    "EXAMPLE, or <placeholder>); real values must come "
                    "from GCP Secret Manager, a gitignored local env "
                    "file, or a deploy-time Kubernetes Secret."
                ),
            )
        )
    return violations


def check_no_populated_secret_env_files(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Forbid populated assignments in tracked `*-secrets.env` files (ADR-004-R9).

    Scans tracked `*-secrets.env` files under `_SECRET_ENV_ROOTS` (currently
    `platform/k8s/`). Allows comments, blank lines, empty assignments
    (`KEY=`), and a small synthetic-placeholder set. Anything else is
    flagged as a real value that must not ship in source.

    Reports violations with `rule_id="ADR-004-R9"`. Violation messages
    name the path and the variable name; they NEVER echo the rejected
    value. Mirrors `check_no_tracked_generated_artifacts` in using
    `git ls-files` for containment (so gitignored local-dev files are
    intentionally not scanned) with a filesystem-walk fallback for
    synthetic-tmpdir unit tests.
    """
    if files is not None:
        in_scope = sorted({p for p in files if _is_secret_env_in_scope(p)})
    else:
        in_scope = sorted(set(_iter_secret_env_candidates(repo_root)))
    violations: list[Violation] = []
    for rel in in_scope:
        abs_path = repo_root / rel
        if not abs_path.exists() or not abs_path.is_file():
            continue
        violations.extend(_scan_secret_env_file(abs_path, rel))
    return violations


# The tfvars and generated-artifact halves of this check family live in the
# private sibling modules imported above; their names are re-exported here so
# `_guard.checks.secret_hygiene` keeps the single, stable import-time surface
# that `adr_guard.py` copies and the tests reach through.
__all__ = [
    "_BLOCK_COMMENT_PATTERN",
    "_GENERATED_ARTIFACT_PREDICATES",
    "_GENERATED_ARTIFACT_ROOTS",
    "_NON_SECRET_NAME_SUFFIXES",
    "_SECRET_ASSIGNMENT_PATTERN",
    "_SECRET_BLOCK_OPEN_PATTERN",
    "_SECRET_ENV_PLACEHOLDERS",
    "_SECRET_ENV_ROOTS",
    "_SECRET_ENV_SUFFIX",
    "_SECRET_HEREDOC_PATTERN",
    "_SECRET_NAME_GROUP",
    "_SECRET_VAR_PATTERN",
    "_STRING_LITERAL_PATTERN",
    "_TFVARS_SCOPE",
    "_balance_scan",
    "_block_assignment_has_literal",
    "_block_depth_scan",
    "_collect_tfvars_candidates",
    "_find_balanced_close_index",
    "_find_block_close_index",
    "_flagged_secret_var",
    "_generated_artifact_match",
    "_git_ls_files_stdout",
    "_git_tracked_under_roots",
    "_git_tracked_under_roots_for_secret_env",
    "_is_bootstrap_authcode_artifact",
    "_is_line_commented",
    "_is_polaris_build_artifact",
    "_is_polaris_operator_run_artifact",
    "_is_public_material_name",
    "_is_secret_env_in_scope",
    "_is_synthetic_placeholder",
    "_is_terraform_plan_artifact",
    "_iter_artifact_candidates",
    "_iter_secret_env_candidates",
    "_lines_have_string_literal",
    "_scan_secret_env_file",
    "_scan_tfvars_file",
    "_scrub_line",
    "_strip_hcl_comments",
    "_strip_trailing_line_comment",
    "_walk_filesystem_artifacts",
    "_walk_filesystem_secret_env",
    "_wrapped_rhs_has_literal",
    "check_no_plaintext_secrets_in_tfvars",
    "check_no_populated_secret_env_files",
    "check_no_tracked_generated_artifacts",
]
