"""Python complexity gate (ADR-012)."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .._common import (
    Violation,
    _ADR_GUARD_PATH,
    is_guard_source_path,
)


# Canonical Python packages whose pyproject.toml must enforce the per-function
# complexity gate. Keyed off `.pre-commit-config.yaml` ruff hooks. Adding a new
# Python package with a ruff-pre-commit hook means adding it here too.
PYTHON_COMPLEXITY_GATE_PYPROJECTS = (
    "shifter/shifter_platform",
    "shifter/engine/provisioner",
    "shifter/packer",
    "shifter/installation",
    "scripts/bootstrap",
    "scripts/gcp",
    "scripts/check_layer_imports",
    "scripts/check_rds_pending_modifications",
    "scripts/assert_portal_inspection",
    "scripts/handle_sd_replacement",
    "uat/event-load-harness",
)

# Single repo-wide threshold for ruff's McCabe (C901) check. Equality, not <=.
# Ratchet edits update this constant and the production pyprojects in one PR;
# the constant exists so the ratchet point is searchable.
PYTHON_COMPLEXITY_THRESHOLD = 15

# Path constants referenced by violations and the consistency / reconciliation
# passes. Defined once so messages stay consistent and so SonarCloud's
# duplicate-literal rule is satisfied.
_PRECOMMIT_CONFIG_PATH = ".pre-commit-config.yaml"
_BACKLOG_DOC_PATH = "docs/adr/complexity-backlog.md"
_CHECK_NAME = "python-complexity-gate"
_RULE_R1 = "ADR-012-R1"
_RULE_R2 = "ADR-012-R2"

# Match `- id: ruff` (not `id: ruff-format`) anywhere in the line.
_RUFF_HOOK_ID_PATTERN = re.compile(r"^\s*-\s+id:\s+ruff\b(?!-)")
# Any new hook entry (used as a "we've moved on" marker by the state machine).
_HOOK_ID_PATTERN = re.compile(r"^\s*-\s+id:")
# `files: ^<path>/` line of a hook.
_HOOK_FILES_LINE_PATTERN = re.compile(r"^\s*files:\s*\^(\S+?)/\s*$")
# A line carrying a `# noqa: ...` exemption that includes C901 anywhere in
# the rules list (e.g. `# noqa: C901`, `# noqa: E501, C901`, `# noqa:C901`).
_NOQA_C901_PATTERN = re.compile(r"#\s*noqa\s*:\s*([A-Z0-9, ]+)")
# A bare `# noqa` with no code list. Ruff treats this as line-level
# suppression of ALL rules, which silently covers C901 on a def line — the
# scanner must detect this even though there is no explicit C901 code.
_NOQA_BARE_PATTERN = re.compile(r"#\s*noqa\b(?!\s*:)")
# `def NAME(` on the same line as a `# noqa: C901` is the repo convention
# (see docs/adr/complexity-backlog.md). Methods (`    def NAME(`) match too.
_DEF_NAME_PATTERN = re.compile(r"\bdef\s+(\w+)\s*\(")
# Source-file directories we never scan for noqa sites.
_NOQA_SCAN_SKIP_PARTS = frozenset({".venv", "venv", "__pycache__", "node_modules", "staticfiles", "migrations"})


def _selector_covers_c901(selector: str) -> bool:
    """Return True if a Ruff selector string would cover the ``C901`` rule.

    Ruff supports both exact codes (``C901``) and category prefixes
    (``C``, ``C9``, ``C90``) plus the wildcard ``ALL``. A selector covers
    ``C901`` whenever ``C901`` starts with it (after upper-casing). This is the
    same semantic ruff uses when expanding selectors against the rule set.
    """
    s = selector.strip().upper()
    if not s:
        return False
    if s == "ALL":
        return True
    return "C901".startswith(s)


def _any_selector_covers_c901(selectors: list[str]) -> bool:
    """Convenience: True iff any selector in ``selectors`` covers C901."""
    return any(_selector_covers_c901(s) for s in selectors)


def _classify_noqa_line(line: str) -> str | None:
    """Classify how a source line relates to C901 suppression.

    Returns:
    - ``"c901"`` — explicit ``# noqa: C901`` (alone or alongside other codes).
    - ``"<noqa-without-def>"`` — explicit ``# noqa: C901`` but no same-line def.
    - ``"<bare-noqa>"`` — bare ``# noqa`` (no code list) on a def line.
    - ``None`` — line does not affect C901.

    The two sentinel strings match the sentinel function names used in
    :func:`_scan_noqa_c901_sites` so the caller can route them straight to
    :func:`_classify_sentinel_noqa`.
    """
    coded_match = _NOQA_C901_PATTERN.search(line)
    def_match = _DEF_NAME_PATTERN.search(line)
    if coded_match:
        codes = {c.strip() for c in coded_match.group(1).split(",")}
        if "C901" not in codes:
            return None
        return "c901" if def_match else "<noqa-without-def>"
    return "<bare-noqa>" if _NOQA_BARE_PATTERN.search(line) and def_match else None


def _scan_file_for_noqa(path: Path, relpath: str, sites: dict[tuple[str, str], tuple[str, int]]) -> None:
    """Scan one source file and record any C901-affecting noqa sites."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return
    for lineno, line in enumerate(lines, start=1):
        classification = _classify_noqa_line(line)
        if classification is None:
            continue
        if classification == "c901":
            # def_match is guaranteed by the "c901" branch in _classify_noqa_line.
            def_match = _DEF_NAME_PATTERN.search(line)
            assert def_match is not None
            sites[(relpath, def_match.group(1))] = (line.strip(), lineno)
        else:
            sites[(relpath, classification)] = (line.strip(), lineno)


def _scan_noqa_c901_sites(repo_root: Path) -> dict[tuple[str, str], tuple[str, int]]:
    """Walk canonical packages for noqa lines that suppress C901.

    Returns a mapping ``(file_relpath, function_name) -> (line_text, line_no)``.
    The line text/number are surfaced so violations can cite the source.

    Recognized exemption shapes on a ``def NAME(`` line:
    - ``# noqa: ..., C901, ...`` — explicit C901 code list (the repo convention).
    - ``# noqa`` (bare, no code list) — ruff suppresses every rule on the line,
      including C901. The scanner records this under the sentinel function name
      ``"<bare-noqa>"`` so the caller can emit a "use explicit codes" violation.

    Lines that carry ``# noqa: C901`` but no same-line ``def NAME(`` are recorded
    under ``"<noqa-without-def>"`` so the caller can emit a wrong-placement
    violation.
    """
    sites: dict[tuple[str, str], tuple[str, int]] = {}
    for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS:
        root = repo_root / pkg
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in _NOQA_SCAN_SKIP_PARTS for part in path.parts):
                continue
            relpath = path.resolve().relative_to(repo_root.resolve()).as_posix()
            _scan_file_for_noqa(path, relpath, sites)
    return sites


def _is_backticked(cell: str) -> bool:
    """True when a markdown table cell is wrapped in backticks."""
    return cell.startswith("`") and cell.endswith("`")


def _backlog_row_entry(line: str) -> tuple[str, str] | None:
    """Parse one backlog table row into a ``(file, function)`` pair, or None."""
    cells = [c.strip() for c in line.split("|")]
    # A markdown table row has empty leading/trailing cells. The required
    # leading columns are `<pkg>|<file>|<fn>|<complexity>`; downstream
    # columns (tracking issue, owner, etc.) are accepted as long as the
    # leading shape is intact.
    if len(cells) < 6 or cells[0] or cells[-1]:
        return None
    file_cell, fn_cell, comp_cell = cells[2], cells[3], cells[4]
    if not _is_backticked(file_cell) or not _is_backticked(fn_cell) or not comp_cell.isdigit():
        return None
    return (file_cell.strip("`"), fn_cell.strip("`"))


def _parse_complexity_backlog(repo_root: Path) -> set[tuple[str, str]] | None:
    """Parse the ADR-012 backlog doc into a set of ``(file, function)`` pairs.

    Returns ``None`` if the doc is missing (the caller emits a dedicated
    "missing backlog" violation). Empty backlog returns an empty set.

    Implementation: cell-by-cell split on ``|`` rather than a multi-quantifier
    regex. Linear in input size with no backtracking surface.
    """
    path = repo_root / _BACKLOG_DOC_PATH
    if not path.exists():
        return None
    entries: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = _backlog_row_entry(line)
        if entry is not None:
            entries.add(entry)
    return entries


def _ruff_hook_paths_from_precommit(repo_root: Path) -> set[str] | None:
    """Return package paths covered by `id: ruff` hooks in .pre-commit-config.yaml.

    Returns ``None`` if the file is missing (synthetic test fixtures may omit
    it). Returns a set of path strings without leading ``^`` or trailing ``/``.

    Implementation: a simple line-by-line state machine, not a single multi-line
    regex. Avoids nested quantifiers (and the ReDoS-style backtracking risk
    SonarCloud's ``python:S5852`` would flag) and reads cleanly: a hook entry
    with ``id: ruff`` arms the state, and the next ``files:`` line emits the
    captured path.
    """
    config_path = repo_root / _PRECOMMIT_CONFIG_PATH
    if not config_path.exists():
        return None
    paths: set[str] = set()
    armed = False
    for line in config_path.read_text(encoding="utf-8").splitlines():
        if _RUFF_HOOK_ID_PATTERN.match(line):
            armed = True
            continue
        if armed:
            files_match = _HOOK_FILES_LINE_PATTERN.match(line)
            if files_match:
                paths.add(files_match.group(1))
                armed = False
            elif _HOOK_ID_PATTERN.match(line):
                # A new hook started before we saw `files:`; disarm but
                # don't lose a fresh `id: ruff` line that may be this one.
                armed = bool(_RUFF_HOOK_ID_PATTERN.match(line))
    return paths


def _is_change_relevant(files: list[str] | None) -> bool:
    """Return True if the file list (``--files`` / ``--changed``) requires the check.

    The complexity gate runs unconditionally on ``--all`` (``files is None``).
    For targeted runs, only changes that could affect the gate are relevant:
    canonical pyprojects, ``.pre-commit-config.yaml``, the backlog doc,
    ``scripts/adr_guard/adr_guard.py`` (where the constants live), or any
    ``.py`` file under one of the canonical packages.
    """
    if files is None:
        return True
    canonical_paths = {f"{pkg}/pyproject.toml" for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS}
    fixed_relevant = canonical_paths | {
        _PRECOMMIT_CONFIG_PATH,
        _BACKLOG_DOC_PATH,
    }
    touched = set(files)
    if touched & fixed_relevant or any(is_guard_source_path(f) for f in touched):
        return True
    return any(
        f.endswith(".py") and any(f.startswith(f"{pkg}/") for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS) for f in touched
    )


def _violation_r1(path: str, message: str) -> Violation:
    """Shorthand for an ADR-012-R1 violation under this check."""
    return Violation(_CHECK_NAME, _RULE_R1, path, message)


def _violation_r2(path: str, message: str) -> Violation:
    """Shorthand for an ADR-012-R2 violation under this check."""
    return Violation(_CHECK_NAME, _RULE_R2, path, message)


def _load_lint_section(path: Path) -> tuple[dict[str, object], Violation | None]:
    """Read a pyproject.toml and return its ``[tool.ruff.lint]`` mapping.

    Returns ``({}, Violation)`` on TOML decode errors so the caller can record
    the failure and continue to the next package. The relative path is derived
    from ``path``'s last two components (``<pkg>/pyproject.toml``).
    """
    relative = f"{path.parent.name}/{path.name}" if path.parent.name else path.name
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return {}, _violation_r1(relative, f"pyproject.toml is not valid TOML: {exc}")
    lint = data.get("tool", {}).get("ruff", {}).get("lint", {})
    return lint, None


def _check_select(lint: dict[str, object], relative: str) -> list[Violation]:
    """C901 must be covered by ``select`` or ``extend-select``."""
    if _any_selector_covers_c901(lint.get("select", [])) or _any_selector_covers_c901(lint.get("extend-select", [])):
        return []
    return [
        _violation_r1(
            relative,
            '[tool.ruff.lint].select must enable "C901" (per-function complexity gate)',
        )
    ]


def _check_ignore_field(lint: dict[str, object], field: str, relative: str) -> list[Violation]:
    """``ignore`` / ``extend-ignore`` must not suppress C901 by any prefix."""
    covers = [s for s in lint.get(field, []) if _selector_covers_c901(s)]
    if not covers:
        return []
    return [
        _violation_r1(
            relative,
            f'[tool.ruff.lint].{field} must not suppress "C901" (selectors that cover it: {sorted(covers)})',
        )
    ]


def _check_per_file_ignores(lint: dict[str, object], relative: str) -> list[Violation]:
    """``per-file-ignores`` must not exempt C901 from any glob."""
    per_file_ignores = lint.get("per-file-ignores", {})
    broad = sorted(glob for glob, rules in per_file_ignores.items() if any(_selector_covers_c901(r) for r in rules))
    if not broad:
        return []
    return [
        _violation_r1(
            relative,
            '[tool.ruff.lint.per-file-ignores] must not suppress "C901" '
            f"(globs with covering selectors: {broad}); use per-function "
            "`# noqa: C901` instead",
        )
    ]


def _check_max_complexity(lint: dict[str, object], relative: str) -> list[Violation]:
    """``mccabe.max-complexity`` must equal the repo-wide threshold."""
    mccabe = lint.get("mccabe", {})
    if "max-complexity" not in mccabe:
        return [
            _violation_r1(
                relative,
                f"[tool.ruff.lint.mccabe].max-complexity must be set to {PYTHON_COMPLEXITY_THRESHOLD}",
            )
        ]
    if mccabe["max-complexity"] != PYTHON_COMPLEXITY_THRESHOLD:
        return [
            _violation_r1(
                relative,
                "[tool.ruff.lint.mccabe].max-complexity must equal "
                f"{PYTHON_COMPLEXITY_THRESHOLD} (got {mccabe['max-complexity']})",
            )
        ]
    return []


def _check_canonical_pyproject(pkg: str, repo_root: Path) -> list[Violation]:
    """Run all per-package pyproject checks for one canonical package."""
    relative = f"{pkg}/pyproject.toml"
    path = repo_root / pkg / "pyproject.toml"
    if not path.exists():
        return [
            _violation_r1(
                relative,
                f"missing pyproject.toml for canonical Python package {pkg}",
            )
        ]
    lint, decode_violation = _load_lint_section(path)
    if decode_violation is not None:
        return [decode_violation]
    return [
        *_check_select(lint, relative),
        *_check_ignore_field(lint, "ignore", relative),
        *_check_ignore_field(lint, "extend-ignore", relative),
        *_check_per_file_ignores(lint, relative),
        *_check_max_complexity(lint, relative),
    ]


def _check_precommit_consistency(repo_root: Path) -> list[Violation]:
    """Cross-check the constant against ``.pre-commit-config.yaml`` ruff hooks.

    Skips silently when the config file is missing (synthetic test fixtures
    legitimately omit it).
    """
    hook_paths = _ruff_hook_paths_from_precommit(repo_root)
    if hook_paths is None:
        return []
    constant = set(PYTHON_COMPLEXITY_GATE_PYPROJECTS)
    violations: list[Violation] = []
    for missing in sorted(hook_paths - constant):
        violations.append(
            _violation_r1(
                _PRECOMMIT_CONFIG_PATH,
                f"ruff pre-commit hook covers {missing!r} but it is not in "
                "PYTHON_COMPLEXITY_GATE_PYPROJECTS; add it or remove the hook",
            )
        )
    for stale in sorted(constant - hook_paths):
        violations.append(
            _violation_r1(
                _ADR_GUARD_PATH,
                f"PYTHON_COMPLEXITY_GATE_PYPROJECTS includes {stale!r} but no "
                "matching `id: ruff` hook exists in .pre-commit-config.yaml",
            )
        )
    return violations


def _classify_sentinel_noqa(file_: str, func: str, line_text: str, lineno: int) -> Violation | None:
    """Return a violation for sentinel noqa entries (wrong placement / bare)."""
    if func == "<noqa-without-def>":
        return _violation_r2(
            f"{file_}:{lineno}",
            f"`# noqa: C901` must be on the `def NAME(` line, not {line_text!r}",
        )
    if func == "<bare-noqa>":
        return _violation_r2(
            f"{file_}:{lineno}",
            "bare `# noqa` on a `def` line is forbidden — it silently "
            "suppresses C901; use an explicit code list (e.g. `# noqa: C901`) "
            "and add a backlog row",
        )
    return None


def _check_backlog_reconciliation(repo_root: Path) -> list[Violation]:
    """Compare in-source ``# noqa: C901`` sites against the ADR-012 backlog."""
    backlog = _parse_complexity_backlog(repo_root)
    if backlog is None:
        return [
            _violation_r2(
                _BACKLOG_DOC_PATH,
                "ADR-012 backlog doc is missing; the reconciliation gate cannot operate without it",
            )
        ]

    violations: list[Violation] = []
    noqa_sites = _scan_noqa_c901_sites(repo_root)
    # Sentinels first so authors get the clearer hint before the set-diff one.
    for (file_, func), (line_text, lineno) in sorted(noqa_sites.items()):
        sentinel = _classify_sentinel_noqa(file_, func, line_text, lineno)
        if sentinel is not None:
            violations.append(sentinel)

    # The keys of noqa_sites are already (file, func) tuples; filter on the
    # function-name component without redundant unpacking-on-iteration.
    noqa_pairs = {key for key in noqa_sites if not key[1].startswith("<")}
    for file_, func in sorted(noqa_pairs - backlog):
        _line_text, lineno = noqa_sites[(file_, func)]
        violations.append(
            _violation_r2(
                f"{file_}:{lineno}",
                f"unauthorized `# noqa: C901` exemption on `{func}` — add a row "
                f"to {_BACKLOG_DOC_PATH} or refactor the function below the threshold",
            )
        )
    for file_, func in sorted(backlog - noqa_pairs):
        violations.append(
            _violation_r2(
                _BACKLOG_DOC_PATH,
                f"stale backlog row for `{file_}::{func}` — no matching "
                "`# noqa: C901` exists in source; remove the row",
            )
        )
    return violations


def check_python_complexity_gate(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Enforce ADR-012-R1 / R2: per-package ruff config + backlog reconciliation.

    Three layers, applied independently:

    1. **Per-package pyproject.toml checks.** For each canonical package, verify
       that C901 is enabled (``select`` / ``extend-select`` with prefix
       semantics), not suppressed via ``ignore`` / ``extend-ignore`` /
       ``per-file-ignores``, and that ``mccabe.max-complexity`` equals
       :data:`PYTHON_COMPLEXITY_THRESHOLD`.
    2. **Pre-commit consistency.** ``PYTHON_COMPLEXITY_GATE_PYPROJECTS`` must
       match the ``id: ruff`` hook working directories in
       ``.pre-commit-config.yaml`` (in both directions).
    3. **Backlog reconciliation.** Every ``# noqa: C901`` in source must map
       1:1 to a row in ``docs/adr/complexity-backlog.md``; bare ``# noqa`` on
       a def line and ``# noqa: C901`` on a non-def line are explicit errors.

    This is a config-shape and reconciliation validator only. Computing
    per-function complexity is Ruff's job; this check is the structural
    backstop against silent gate removal and untracked exemptions.

    When ``files`` is supplied, the check is a no-op unless one of the relevant
    surfaces is in the change set (see :func:`_is_change_relevant`).
    """
    if not _is_change_relevant(files):
        return []
    violations: list[Violation] = []
    for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS:
        violations.extend(_check_canonical_pyproject(pkg, repo_root))
    violations.extend(_check_precommit_consistency(repo_root))
    violations.extend(_check_backlog_reconciliation(repo_root))
    return violations
