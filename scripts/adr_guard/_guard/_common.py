"""Shared kernels: Violation, repo paths/inventory, read-only git helpers, exception filtering."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import date
from fnmatch import fnmatch
from pathlib import Path


def _discover_repo_root() -> Path:
    """Repo root, independent of this module's depth inside the package.

    Walk up from this file to the checkout that carries the ADR registry, falling
    back to the known package layout (``scripts/adr_guard/_guard/_common.py``).
    Deeper modules must never hardcode a ``parents[N]`` that silently changes
    meaning when a module moves (issue #998 codex review); the facade establishes
    the default root and this discovery keeps it correct wherever the module sits.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "docs" / "adr" / "index.yaml").is_file():
            return parent
    return here.parents[3]


REPO_ROOT = _discover_repo_root()
# Every first-party Django app is classified (ADR-001, #1523). Held to
# set-equality with the canonical classification in layer_imports.yaml by the
# layer-classification-parity check.
LAYERS = ("shared", "engine", "cms", "management", "mission_control", "ctf", "config", "workspaces")
REQUIRED_EXCEPTION_KEYS = {"rule_id", "owner", "reason", "expires_on"}


@dataclass(frozen=True)
class Violation:
    """A single ADR guard violation."""

    check: str
    rule_id: str
    path: str
    message: str


def _parse_iso_date(value: str) -> date:
    """Parse an ISO-8601 date string, raising ValueError when malformed."""
    return date.fromisoformat(value)


def _repo_relative(path: Path, repo_root: Path) -> str:
    """Return ``path`` as a posix path relative to the repo root."""
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def is_guard_source_path(path: str) -> bool:
    """True for adr_guard package source files (facade, kernels, and checks).

    The check logic and its governing constants now live across the package
    (``checks/*`` plus ``_common`` / ``_workflow_model`` / ``_registry`` /
    ``_cli``), so a change to any package module - not only the ``adr_guard.py``
    facade - is relevant to the tool's self-validating checks (complexity,
    deploy-plan-scope, action-pinning). Test files are excluded; they never
    carry check configuration.
    """
    return (
        path.startswith("scripts/adr_guard/")
        and path.endswith(".py")
        and "/tests/" not in path
    )


def _normalize_files(files: list[str] | None, repo_root: Path) -> list[str] | None:
    """Normalize file arguments to sorted, unique repo-relative posix paths."""
    if files is None:
        return None

    normalized: list[str] = []
    for item in files:
        if not item:
            continue
        path = Path(item)
        if path.is_absolute():
            normalized.append(_repo_relative(path, repo_root))
        else:
            normalized.append(Path(item).as_posix().lstrip("./"))

    return sorted(set(normalized))


def _load_json_yaml(path: Path) -> object:
    """Load a JSON-compatible YAML document from ``path``."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_adr_exceptions(repo_root: Path) -> list[dict[str, object]]:
    """Load and validate the exception registry shape."""
    path = repo_root / "docs" / "adr" / "exceptions.yaml"
    data = _load_json_yaml(path)
    if not isinstance(data, list):
        raise ValueError("docs/adr/exceptions.yaml must contain a top-level list")
    return data


def _is_str_list(value: object) -> bool:
    """True when ``value`` is a list of strings."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _validate_exception_entry(index: int, exception: dict[str, object]) -> list[str]:
    """Validate one exception entry's schema and expiry; return its errors."""
    missing = REQUIRED_EXCEPTION_KEYS - set(exception)
    if missing:
        return [f"Exception entry {index} is missing keys: {sorted(missing)}"]

    try:
        expires_on = _parse_iso_date(exception["expires_on"])
    except ValueError:
        return [f"Exception entry {index} has invalid expires_on date: {exception['expires_on']!r}"]

    errors: list[str] = []
    if expires_on < date.today():
        errors.append(f"Exception entry {index} for {exception['rule_id']} expired on {exception['expires_on']}")

    # ``paths``/``checks`` are optional glob/name lists; ``fingerprints`` is the
    # optional exact-accessibility-fingerprint scope (ADR-055-R6) - a waiver may
    # enumerate exact fingerprints instead of overloading paths/checks.
    for key in ("paths", "checks"):
        value = exception.get(key, [])
        if value and not isinstance(value, list):
            errors.append(f"Exception entry {index} {key} must be a list when present")

    fingerprints = exception.get("fingerprints", [])
    if fingerprints and not _is_str_list(fingerprints):
        errors.append(f"Exception entry {index} fingerprints must be a list of strings when present")

    return errors


def validate_adr_exceptions(exceptions: list[dict[str, object]]) -> list[str]:
    """Validate exception schema and expiry dates."""
    errors: list[str] = []
    for index, exception in enumerate(exceptions):
        errors.extend(_validate_exception_entry(index, exception))
    return errors


def exception_is_active(exception: dict[str, object], today: date | None = None) -> bool:
    """Return True when an exception carries a valid, unexpired ``expires_on``.

    A missing or unparseable date counts as inactive. ``validate_adr_exceptions``
    reports those separately, and a malformed date must never buy open-ended
    suppression: the expiry is the only thing bounding an accepted violation.
    """
    raw = exception.get("expires_on")
    if not isinstance(raw, str):
        return False
    try:
        expires_on = _parse_iso_date(raw)
    except ValueError:
        return False
    return expires_on >= (today or date.today())


def exception_matches(violation: Violation, exception: dict[str, object]) -> bool:
    """Return True if an unexpired exception covers a given violation."""
    if not exception_is_active(exception) or exception.get("rule_id") != violation.rule_id:
        return False

    checks = exception.get("checks") or []
    if checks and violation.check not in checks:
        return False

    paths = exception.get("paths") or []
    return not paths or any(fnmatch(violation.path, pattern) for pattern in paths)


def filter_excepted_violations(violations: list[Violation], exceptions: list[dict[str, object]]) -> list[Violation]:
    """Drop violations that are covered by a non-expired exception."""
    filtered: list[Violation] = []
    for violation in violations:
        if any(exception_matches(violation, exception) for exception in exceptions):
            continue
        filtered.append(violation)
    return filtered


def get_changed_files(repo_root: Path) -> list[str]:
    """Get staged files, falling back to the current working tree diff."""
    commands = (
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "HEAD"],
    )

    for cmd in commands:
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if files:
                return sorted(set(files))

    return []
_BOUNDARY_MOCK_BASE_REF_ENVS = ("ADR_GUARD_BASE_REF", "GITHUB_BASE_REF")


def _git_text(repo_root: Path, args: list[str]) -> str | None:
    """Run a read-only git command and return stdout when it succeeds."""
    if not (repo_root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _boundary_mock_base_reference_candidates(repo_root: Path) -> list[str]:
    """Return base-branch commit-ish candidates for the baseline ratchet reference."""
    candidates: list[str] = []
    for env_name in _BOUNDARY_MOCK_BASE_REF_ENVS:
        base_ref = os.environ.get(env_name, "").strip()
        if not base_ref:
            continue
        candidates.append(base_ref)
        if base_ref.startswith("refs/heads/"):
            short = base_ref.removeprefix("refs/heads/")
            candidates.extend([f"origin/{short}", short])
        elif not base_ref.startswith("origin/") and not base_ref.startswith("refs/"):
            candidates.extend([f"origin/{base_ref}", base_ref])

    candidates.extend(["origin/dev", "dev", "origin/main", "main"])

    refs: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        merge_base = _git_text(repo_root, ["merge-base", "HEAD", candidate])
        if merge_base is None:
            continue
        ref = merge_base.strip()
        if ref and ref not in seen:
            refs.append(ref)
            seen.add(ref)

    return refs


def _boundary_mock_fallback_reference_candidates(repo_root: Path) -> list[str]:
    """Return fallback commit-ish candidates for shallow/synthetic repositories."""
    refs: list[str] = []
    seen: set[str] = set()
    for fallback in ("HEAD^1", "HEAD"):
        ref = _git_text(repo_root, ["rev-parse", "--verify", f"{fallback}^{{commit}}"])
        if ref is None:
            continue
        commit = ref.strip()
        if commit and commit not in seen:
            refs.append(commit)
            seen.add(commit)

    return refs
_ADR_GUARD_PATH = "scripts/adr_guard/adr_guard.py"


def _read_text_safe(path: Path) -> str | None:
    """Read a file as UTF-8, returning None for unreadable or binary content."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    return data.decode("utf-8", errors="ignore")


def _git_tracked_all(repo_root: Path) -> list[str] | None:
    """All tracked + non-ignored untracked repo-relative paths, or None when
    `repo_root` is not a git working tree (synthetic test mode)."""
    if not (repo_root / ".git").exists():
        return None
    cmd = [
        "git", "-C", str(repo_root), "ls-files", "-z",
        "--cached", "--others", "--exclude-standard",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is None or result.returncode != 0:
        return None
    output = result.stdout.decode("utf-8", errors="replace")
    return [entry for entry in output.split("\0") if entry]


def _walk_all_files(repo_root: Path) -> list[str]:
    """Test-mode fallback: every file on disk under `repo_root`, skipping the
    git dir. Only reached when there is no usable git index."""
    candidates: list[str] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = _repo_relative(path, repo_root)
        if rel.startswith(".git/"):
            continue
        candidates.append(rel)
    return candidates
