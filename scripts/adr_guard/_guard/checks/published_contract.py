"""Published-contract snapshot immutability (ADR-011-R8)."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .._common import (
    Violation,
    _boundary_mock_base_reference_candidates,
    _git_text,
)


_PUBLISHED_CONTRACT_DIR = "shifter/installation/published_contract"
_PUBLISHED_CONTRACT_SNAPSHOT_RE = re.compile(r"^backend-bundle-contract\.v(\d+)\.json$")
_PUBLISHED_CONTRACT_CHECK = "published-contract-snapshots-immutable"
_PUBLISHED_CONTRACT_RULE = "ADR-011-R8"
# CI lanes that fetch base-branch history set this so the check fails CLOSED when it cannot
# verify immutability. Local/shallow runs (env unset) fail open so dev is not blocked.
_PUBLISHED_CONTRACT_ENFORCE_ENV = "ADR_GUARD_SNAPSHOT_ENFORCE"


def _published_contract_snapshot_names(repo_root: Path, ref: str) -> set[str] | None:
    """Frozen version-snapshot filenames under the published-contract dir at ``ref``.

    Returns an empty set when the directory does not exist at ``ref`` (a genuine first
    publication), and ``None`` when the tree could not be read at all (a git read failure) —
    the two cases are distinct so the caller can fail closed on the unreadable case.
    """
    listing = _git_text(repo_root, ["ls-tree", "--name-only", ref, f"{_PUBLISHED_CONTRACT_DIR}/"])
    if listing is None:
        return None
    names = {line.strip().rsplit("/", 1)[-1] for line in listing.splitlines() if line.strip()}
    return {name for name in names if _PUBLISHED_CONTRACT_SNAPSHOT_RE.match(name)}


def _published_contract_enforced() -> bool:
    """True when the CI lane demands the immutability check fail closed."""
    return os.environ.get(_PUBLISHED_CONTRACT_ENFORCE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _published_contract_violation(path: str, message: str) -> Violation:
    """Shorthand for an ADR-011-R8 published-contract violation at ``path``."""
    return Violation(_PUBLISHED_CONTRACT_CHECK, _PUBLISHED_CONTRACT_RULE, path, message)


def _published_contract_unverifiable(enforce: bool, path: str, message: str) -> list[Violation]:
    """Report an unverifiable snapshot when enforcing; otherwise fail open silently."""
    return [_published_contract_violation(path, message)] if enforce else []


def _published_contract_snapshot_diff(repo_root: Path, ref: str, name: str, enforce: bool) -> list[Violation]:
    """Compare one published snapshot against ``ref`` and report any mutation."""
    rel = f"{_PUBLISHED_CONTRACT_DIR}/{name}"
    head_path = repo_root / rel
    if not head_path.exists():
        message = (
            "published contract version snapshot was deleted; published versions are immutable "
            "(append-only). Restore it and ship a new version snapshot instead of removing this one."
        )
    else:
        base_content = _git_text(repo_root, ["show", f"{ref}:{rel}"])
        if base_content is None:
            return _published_contract_unverifiable(
                enforce,
                rel,
                "cannot read the published snapshot at the base ref to verify immutability",
            )
        if head_path.read_text(encoding="utf-8") == base_content:
            return []
        message = (
            "published contract version snapshot was modified; published versions are immutable "
            "(append-only). Bump contract_version and add a new snapshot instead of changing this one."
        )
    return [_published_contract_violation(rel, message)]


def check_published_contract_snapshots_immutable(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Published backend-bundle contract version snapshots are append-only (ADR-011-R8).

    Each ``backend-bundle-contract.v<N>.json`` records the frozen shape of a published
    contract version. Once published on the base branch, a snapshot must not be modified or
    deleted — a contract change ships a *new* version snapshot instead. This is what makes the
    breaking-change gate's oracle trustworthy, which the working tree alone cannot: the
    committed snapshot is compared against its content at the base-branch merge base.

    Enforcement is fail-open by default (a shallow clone without base history cannot compare,
    so local dev is not blocked) and fail-CLOSED when ``ADR_GUARD_SNAPSHOT_ENFORCE`` is set —
    the CI lane sets it and fetches base history (``fetch-depth: 0``), so an inability to
    resolve or read the base becomes an enforcement failure rather than a silent pass.
    """
    # global repository invariant, not scoped to the changed-file set
    del files
    enforce = _published_contract_enforced()
    base_refs = _boundary_mock_base_reference_candidates(repo_root)
    if not base_refs:
        return _published_contract_unverifiable(
            enforce,
            _PUBLISHED_CONTRACT_DIR,
            "cannot resolve a base ref to verify published-contract snapshot immutability; "
            "the CI lane must fetch base-branch history (fetch-depth: 0)",
        )
    ref = base_refs[0]
    base_snapshots = _published_contract_snapshot_names(repo_root, ref)
    if base_snapshots is None:
        return _published_contract_unverifiable(
            enforce,
            _PUBLISHED_CONTRACT_DIR,
            "cannot read the published-contract directory at the base ref to verify snapshot immutability",
        )
    # An empty set means the directory does not exist at the base yet
    # (a genuine first publication), so the loop below is a no-op.
    violations: list[Violation] = []
    for name in sorted(base_snapshots):
        violations.extend(_published_contract_snapshot_diff(repo_root, ref, name, enforce))
    return violations
