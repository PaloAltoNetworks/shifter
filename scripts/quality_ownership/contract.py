"""Parse, validate, and reason about the quality-ownership contract (#1530).

The contract lives at ``.github/quality-path-filters.yaml`` and answers one
question: which blocking quality jobs must run when a given production path
changes, and which paths are deliberately out of production scope.

Three consumers share this one module (no duplicated schema):

* ``classify_paths.py`` — the always-run ``_quality.yml`` ``paths`` job. It
  validates the contract, rejects an unknown changed path *before* emitting any
  job-selection output (the fail-closed execution boundary), then writes the
  ``GITHUB_OUTPUT`` keys the downstream jobs consume.
* ``scripts/adr_guard/adr_guard.py`` — the ci-level conformance check. It uses
  :func:`estate_violations` (repository-completeness), the ownership model, and
  :func:`compute_outputs` (routing reachability against the real workflow).

Design invariants:

* ``compute_outputs`` is behaviourally identical to the legacy inline
  classifier for job selection: a path activates *every* unit whose glob it
  matches. Exclusions never change which jobs run; they only make a path
  *known* (so it is not rejected) and out of production ownership.
* Estate classification uses most-specific-pattern-wins precedence (the single
  explicit more-specific rule the preflight sanctions). A path matched by a
  unit and an exclusion at equal specificity is a contradiction, not a
  silent win for either side.
* Ownership completeness is asserted per quality unit: lint AND security AND
  test, each satisfied by a real blocking job. Genuine gaps are recorded as
  time-bounded ``docs/adr/exceptions.yaml`` entries, never a schema escape
  hatch.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

import yaml

SCHEMA_VERSION = 1
RESPONSIBILITIES: tuple[str, ...] = ("lint", "security", "test")
EXCLUSION_TYPES = frozenset({"docs", "test", "generated", "vendor", "metadata", "config"})

_TOP_LEVEL_KEYS = frozenset({"schema_version", "force_full_matrix", "quality_units", "exclusions"})
_UNIT_KEYS = frozenset({"id", "paths", "packages", "sonar", "mcp", "responsibilities"})
_EXCLUSION_KEYS = frozenset({"type", "reason", "paths"})
_MCP_KEYS = frozenset({"package", "fanout_all_on_change"})
_JOBREF_KEYS = frozenset({"job", "matrix"})
_WILDCARD_CHARS = "*?["


class ContractError(Exception):
    """Raised when the contract file is structurally invalid."""


class UnknownPathError(Exception):
    """Raised by :func:`compute_outputs` for a changed path the contract does
    not classify. This is the fail-closed execution boundary: the caller must
    exit nonzero *before* emitting any job-selection output."""

    def __init__(self, paths: list[str]) -> None:
        self.paths = paths
        super().__init__(
            "unclassified changed path(s) (add a quality unit or a typed "
            f"exclusion to .github/quality-path-filters.yaml): {', '.join(paths)}"
        )


@dataclass(frozen=True)
class JobRef:
    """One workflow job that satisfies a responsibility, with an optional
    matrix selector where a single job serves multiple packages."""

    job: str
    matrix: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class McpMatrix:
    """MCP matrix metadata for a unit: its package name and whether a change
    to it fans the whole MCP matrix out (the shared-package dependency rule)."""

    package: str
    fanout_all_on_change: bool = False


@dataclass(frozen=True)
class QualityUnit:
    """A production quality owner: source paths plus the blocking jobs that
    enforce lint/security/test responsibility over them."""

    id: str
    paths: tuple[str, ...]
    responsibilities: dict[str, tuple[JobRef, ...]]
    packages: tuple[str, ...] = ()
    sonar: bool = False
    mcp: McpMatrix | None = None


@dataclass(frozen=True)
class Exclusion:
    """A narrow, typed carve-out from production ownership."""

    type: str
    reason: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Contract:
    """The parsed, validated quality-ownership contract."""

    schema_version: int
    force_full_matrix: tuple[str, ...]
    units: tuple[QualityUnit, ...]
    exclusions: tuple[Exclusion, ...]


# --------------------------------------------------------------------------- #
# Path matching + specificity
# --------------------------------------------------------------------------- #
def _matches(path: str, pattern: str) -> bool:
    """Glob match with the same semantics as the legacy inline classifier: a
    ``dir/**`` pattern matches the directory itself and anything beneath it,
    everything else is a case-sensitive ``fnmatch``."""
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatchcase(path, pattern)


def _pattern_specificity(pattern: str) -> tuple[int, int]:
    """Rank a pattern for most-specific-wins precedence: (number of leading
    path segments with no wildcard, total length). Higher wins, so
    ``docs/adr/**`` (2 literal segments) beats ``docs/**`` (1)."""
    leading = 0
    for segment in pattern.split("/"):
        if any(char in segment for char in _WILDCARD_CHARS):
            break
        leading += 1
    return (leading, len(pattern))


def is_contained_relative(path: str) -> bool:
    """A repository-relative POSIX path with no absolute prefix, traversal,
    empty component, or control character."""
    if not path or not isinstance(path, str):
        return False
    if path.startswith("/"):
        return False
    if any(ord(char) < 0x20 for char in path):
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def is_bounded_pattern(pattern: str) -> bool:
    """A pattern narrow enough for ownership: it must be anchored by either a
    literal leading path segment (a bounded directory prefix) OR a literal file
    extension. This rejects catch-all globs like ``*``, ``**``, and ``**/*``
    that would silently absorb every otherwise-unknown path (ADR-004-R24's
    no-catch-all invariant); ``docs/**`` and ``**/*.md`` remain valid."""
    segments = pattern.split("/")
    if segments and not any(char in segments[0] for char in _WILDCARD_CHARS):
        return True  # bounded by a literal leading directory (or an exact file)
    last = segments[-1]
    if "." in last:
        extension = last.rsplit(".", 1)[1]
        if extension and not any(char in extension for char in _WILDCARD_CHARS):
            return True  # bounded by a literal file extension
    return False


@dataclass(frozen=True)
class _Match:
    kind: str  # "unit" | "exclusion"
    name: str  # unit id | exclusion type
    specificity: tuple[int, int]


def classify_path(contract: Contract, path: str) -> tuple[str, str] | None:
    """Return ``(kind, name)`` for the most-specific match, or ``None`` if the
    path is unclassified. ``kind`` is ``"unit"`` or ``"exclusion"``. Raises
    :class:`ContractError` when the top-specificity match is contradictory (a
    unit and an exclusion, or two exclusion types, tie for most specific)."""
    matches: list[_Match] = []
    for unit in contract.units:
        for pattern in unit.paths:
            if _matches(path, pattern):
                matches.append(_Match("unit", unit.id, _pattern_specificity(pattern)))
    for exclusion in contract.exclusions:
        for pattern in exclusion.paths:
            if _matches(path, pattern):
                matches.append(_Match("exclusion", exclusion.type, _pattern_specificity(pattern)))
    if not matches:
        return None

    top = max(match.specificity for match in matches)
    winners = [match for match in matches if match.specificity == top]
    kinds = {match.kind for match in winners}
    if kinds == {"unit", "exclusion"}:
        raise ContractError(
            f"path {path!r} is matched by both a quality unit and an exclusion "
            "at equal specificity; make one pattern more specific"
        )
    if "exclusion" in kinds and len({m.name for m in winners}) > 1:
        raise ContractError(
            f"path {path!r} is matched by multiple exclusion types "
            f"{sorted({m.name for m in winners})!r} at equal specificity"
        )
    return (winners[0].kind, winners[0].name)


def matching_units(contract: Contract, path: str) -> list[str]:
    """Every unit id whose glob matches ``path`` (any specificity). This is the
    routing view — it mirrors the legacy classifier, where a path activates
    every category it matches (e.g. a polaris-aws-range change activates both
    ``terraform`` and ``polaris_aws_range``)."""
    return [unit.id for unit in contract.units if any(_matches(path, pattern) for pattern in unit.paths)]


def most_specific_unit(contract: Contract, path: str) -> str | None:
    """The id of the unit whose most-specific glob matches ``path`` (used to
    attribute a per-path ownership gap to a single owning unit)."""
    best: str | None = None
    best_spec: tuple[int, int] | None = None
    for unit in contract.units:
        for pattern in unit.paths:
            if _matches(path, pattern):
                spec = _pattern_specificity(pattern)
                if best_spec is None or spec > best_spec:
                    best_spec = spec
                    best = unit.id
    return best


def matches_force_full(contract: Contract, path: str) -> bool:
    return any(_matches(path, pattern) for pattern in contract.force_full_matrix)


def is_covered(contract: Contract, path: str) -> bool:
    """True if the path is a known production owner, a typed exclusion, or a
    full-matrix trigger. An uncovered path fails closed.

    A contradictory match (an equal-specificity unit/exclusion or a
    multi-type exclusion) raises :class:`ContractError` from
    :func:`classify_path` and is deliberately NOT swallowed: the caller must
    treat it as fatal so the classifier exits before emitting outputs and
    estate reconciliation records it, rather than silently accepting an
    ambiguous ownership decision."""
    if matches_force_full(contract, path):
        return True
    return classify_path(contract, path) is not None


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #
def _validate_jobref(raw: object, where: str, errors: list[str]) -> JobRef | None:
    if isinstance(raw, str):
        if not raw:
            errors.append(f"{where}: empty job id")
            return None
        return JobRef(job=raw)
    if not isinstance(raw, dict):
        errors.append(f"{where}: job entry must be a string or mapping")
        return None
    extra = set(raw) - _JOBREF_KEYS
    if extra:
        errors.append(f"{where}: unknown job key(s): {sorted(extra)}")
    job = raw.get("job")
    if not isinstance(job, str) or not job:
        errors.append(f"{where}: job mapping needs a non-empty 'job'")
        return None
    matrix_raw = raw.get("matrix", {})
    if not isinstance(matrix_raw, dict) or not matrix_raw:
        errors.append(f"{where}: job {job!r} 'matrix' must be a non-empty mapping")
        return JobRef(job=job)
    matrix = tuple(sorted((str(k), str(v)) for k, v in matrix_raw.items()))
    return JobRef(job=job, matrix=matrix)


def _validate_unit(raw: object, index: int, errors: list[str]) -> QualityUnit | None:
    where = f"quality_units[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{where} must be a mapping")
        return None
    extra = set(raw) - _UNIT_KEYS
    if extra:
        errors.append(f"{where}: unknown key(s): {sorted(extra)}")

    unit_id = raw.get("id")
    if not isinstance(unit_id, str) or not unit_id:
        errors.append(f"{where}: 'id' must be a non-empty string")
        unit_id = f"<unit {index}>"

    paths = raw.get("paths")
    if not isinstance(paths, list) or not paths:
        errors.append(f"{where} ({unit_id}): 'paths' must be a non-empty list")
        paths = []
    for pattern in paths:
        if not isinstance(pattern, str) or not is_contained_relative(pattern):
            errors.append(f"{where} ({unit_id}): invalid path pattern {pattern!r}")
        elif not is_bounded_pattern(pattern):
            errors.append(
                f"{where} ({unit_id}): unbounded/catch-all path pattern {pattern!r} "
                "(needs a literal directory prefix or file extension)"
            )

    packages_raw = raw.get("packages", [])
    if not isinstance(packages_raw, list):
        errors.append(f"{where} ({unit_id}): 'packages' must be a list")
        packages_raw = []
    packages = tuple(str(pkg) for pkg in packages_raw)

    sonar = raw.get("sonar", False)
    if not isinstance(sonar, bool):
        errors.append(f"{where} ({unit_id}): 'sonar' must be a boolean")
        sonar = bool(sonar)

    mcp = _validate_mcp(raw.get("mcp"), f"{where} ({unit_id})", errors)

    responsibilities = _validate_responsibilities(raw.get("responsibilities"), f"{where} ({unit_id})", errors)

    return QualityUnit(
        id=unit_id,
        paths=tuple(p for p in paths if isinstance(p, str)),
        responsibilities=responsibilities,
        packages=packages,
        sonar=sonar,
        mcp=mcp,
    )


def _validate_mcp(raw: object, where: str, errors: list[str]) -> McpMatrix | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        errors.append(f"{where}: 'mcp' must be a mapping")
        return None
    extra = set(raw) - _MCP_KEYS
    if extra:
        errors.append(f"{where}: unknown mcp key(s): {sorted(extra)}")
    package = raw.get("package")
    if not isinstance(package, str) or not package:
        errors.append(f"{where}: mcp 'package' must be a non-empty string")
        package = ""
    fanout = raw.get("fanout_all_on_change", False)
    if not isinstance(fanout, bool):
        errors.append(f"{where}: mcp 'fanout_all_on_change' must be a boolean")
        fanout = bool(fanout)
    return McpMatrix(package=package, fanout_all_on_change=fanout)


def _validate_responsibilities(raw: object, where: str, errors: list[str]) -> dict[str, tuple[JobRef, ...]]:
    result: dict[str, tuple[JobRef, ...]] = {name: () for name in RESPONSIBILITIES}
    if not isinstance(raw, dict):
        errors.append(f"{where}: 'responsibilities' must be a mapping")
        return result
    extra = set(raw) - set(RESPONSIBILITIES)
    if extra:
        errors.append(f"{where}: unknown responsibility key(s): {sorted(extra)}")
    for name in RESPONSIBILITIES:
        entries = raw.get(name, [])
        if not isinstance(entries, list):
            errors.append(f"{where}: responsibility {name!r} must be a list")
            continue
        jobs: list[JobRef] = []
        for entry in entries:
            jobref = _validate_jobref(entry, f"{where}.{name}", errors)
            if jobref is not None:
                jobs.append(jobref)
        result[name] = tuple(jobs)
    return result


def _validate_exclusion(raw: object, index: int, errors: list[str]) -> Exclusion | None:
    where = f"exclusions[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{where} must be a mapping")
        return None
    extra = set(raw) - _EXCLUSION_KEYS
    if extra:
        errors.append(f"{where}: unknown key(s): {sorted(extra)}")
    excl_type = raw.get("type")
    if excl_type not in EXCLUSION_TYPES:
        errors.append(f"{where}: 'type' must be one of {sorted(EXCLUSION_TYPES)}, got {excl_type!r}")
        excl_type = str(excl_type)
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append(f"{where}: 'reason' must be a non-empty string")
        reason = ""
    paths = raw.get("paths")
    if not isinstance(paths, list) or not paths:
        errors.append(f"{where}: 'paths' must be a non-empty list")
        paths = []
    for pattern in paths:
        if not isinstance(pattern, str) or not is_contained_relative(pattern):
            errors.append(f"{where}: invalid path pattern {pattern!r}")
        elif not is_bounded_pattern(pattern):
            errors.append(
                f"{where}: unbounded/catch-all exclusion pattern {pattern!r} "
                "(needs a literal directory prefix or file extension; a "
                "catch-all exclusion would absorb future production paths)"
            )
    return Exclusion(
        type=excl_type,
        reason=reason,
        paths=tuple(p for p in paths if isinstance(p, str)),
    )


def _validate_unique(contract: Contract, errors: list[str]) -> None:
    # Unit ids are the GITHUB_OUTPUT keys and must be unique. Path patterns MAY
    # legitimately appear in more than one unit: a change to
    # scripts/polaris-aws-range/** intentionally activates both the `terraform`
    # (lint/security) and `polaris_aws_range` (test) units. Ownership
    # completeness is evaluated per path across the union of matching units, so
    # a shared pattern is not a conflict.
    seen_ids: set[str] = set()
    for unit in contract.units:
        if unit.id in seen_ids:
            errors.append(f"duplicate quality unit id {unit.id!r}")
        seen_ids.add(unit.id)


def validate_schema(data: object) -> list[str]:
    """Validate the raw contract mapping. Returns a list of human-readable
    error strings (empty when valid)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["contract must be a top-level mapping"]

    extra = set(data) - _TOP_LEVEL_KEYS
    if extra:
        errors.append(f"unknown top-level key(s): {sorted(extra)}")

    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}, got {version!r}")

    force_full = data.get("force_full_matrix", [])
    if not isinstance(force_full, list) or not force_full:
        errors.append("'force_full_matrix' must be a non-empty list")
        force_full = []
    for pattern in force_full:
        if not isinstance(pattern, str) or not is_contained_relative(pattern):
            errors.append(f"force_full_matrix: invalid path pattern {pattern!r}")
        elif not is_bounded_pattern(pattern):
            errors.append(f"force_full_matrix: unbounded/catch-all path pattern {pattern!r}")

    units_raw = data.get("quality_units")
    if not isinstance(units_raw, list) or not units_raw:
        errors.append("'quality_units' must be a non-empty list")
        units_raw = []
    units = [unit for index, raw in enumerate(units_raw) if (unit := _validate_unit(raw, index, errors)) is not None]

    exclusions_raw = data.get("exclusions", [])
    if not isinstance(exclusions_raw, list):
        errors.append("'exclusions' must be a list")
        exclusions_raw = []
    exclusions = [
        excl
        for index, raw in enumerate(exclusions_raw)
        if (excl := _validate_exclusion(raw, index, errors)) is not None
    ]

    if not errors:
        contract = Contract(
            schema_version=SCHEMA_VERSION,
            force_full_matrix=tuple(p for p in force_full if isinstance(p, str)),
            units=tuple(units),
            exclusions=tuple(exclusions),
        )
        _validate_unique(contract, errors)
    return errors


def build_contract(data: object) -> Contract:
    """Validate ``data`` and construct a :class:`Contract`, or raise
    :class:`ContractError` with all errors joined."""
    errors = validate_schema(data)
    if errors:
        raise ContractError("; ".join(errors))
    assert isinstance(data, dict)
    return Contract(
        schema_version=SCHEMA_VERSION,
        force_full_matrix=tuple(data["force_full_matrix"]),
        units=tuple(
            _validate_unit(raw, index, [])  # type: ignore[misc]
            for index, raw in enumerate(data["quality_units"])
        ),
        exclusions=tuple(
            _validate_exclusion(raw, index, [])  # type: ignore[misc]
            for index, raw in enumerate(data.get("exclusions", []))
        ),
    )


def load_contract(path: Path) -> Contract:
    """Load and validate the contract from ``path`` (``yaml.safe_load``)."""
    with Path(path).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return build_contract(data)


# --------------------------------------------------------------------------- #
# Estate reconciliation
# --------------------------------------------------------------------------- #
def estate_violations(contract: Contract, tracked_paths: list[str]) -> list[str]:
    """Reconcile the contract against the tracked repository estate.

    Symmetric like the Terraform-inventory precedent:

    * completeness — every tracked path must be classified (owner, exclusion,
      or full-matrix trigger). An unclassified path fails closed.
    * staleness — every unit / exclusion / full-matrix glob must match at least
      one tracked path, so a rename that leaves the old glob behind is caught.
    * contradiction — a path matched by a unit and an exclusion at equal
      specificity (surfaced via :func:`classify_path`).
    """
    tracked = set(tracked_paths)
    errors: list[str] = []

    for path in sorted(tracked):
        try:
            if not is_covered(contract, path):
                errors.append(
                    f"unclassified path {path!r}: add a quality unit or a typed "
                    "exclusion to .github/quality-path-filters.yaml"
                )
        except ContractError as exc:
            errors.append(str(exc))

    for unit in contract.units:
        for pattern in unit.paths:
            if not any(_matches(path, pattern) for path in tracked):
                errors.append(
                    f"stale glob {pattern!r} in quality unit {unit.id!r} matches no "
                    "tracked file (was a path renamed or removed?)"
                )
    for exclusion in contract.exclusions:
        for pattern in exclusion.paths:
            if not any(_matches(path, pattern) for path in tracked):
                errors.append(f"stale glob {pattern!r} in exclusion {exclusion.type!r} matches no tracked file")
    for pattern in contract.force_full_matrix:
        if not any(_matches(path, pattern) for path in tracked):
            errors.append(f"stale glob {pattern!r} in force_full_matrix matches no tracked file")

    return errors


# --------------------------------------------------------------------------- #
# Output computation (routing) — byte-identical to the legacy inline classifier
# --------------------------------------------------------------------------- #
def _mcp_units(contract: Contract) -> list[QualityUnit]:
    return [unit for unit in contract.units if unit.mcp is not None]


def _mcp_lint_packages(contract: Contract) -> list[str]:
    """MCP packages with a lint responsibility, in declaration order."""
    packages: list[str] = []
    for unit in _mcp_units(contract):
        assert unit.mcp is not None
        if unit.responsibilities.get("lint"):
            packages.append(unit.mcp.package)
    return packages


def _mcp_test_packages(contract: Contract) -> list[str]:
    packages: list[str] = []
    for unit in _mcp_units(contract):
        assert unit.mcp is not None
        if unit.responsibilities.get("test"):
            packages.append(unit.mcp.package)
    return packages


def compute_outputs(
    contract: Contract,
    changed_paths: list[str] | None,
    *,
    run_full_matrix: bool = False,
) -> dict[str, str]:
    """Compute the ``_quality.yml`` ``paths`` job outputs.

    ``changed_paths=None`` (or ``run_full_matrix``) means the full matrix.
    Otherwise every changed path MUST be classified — an unclassified path
    raises :class:`UnknownPathError` so the caller fails closed before emitting
    any output. The returned mapping is byte-identical to the legacy inline
    classifier for a given input.
    """
    unit_ids = [unit.id for unit in contract.units]
    outputs: dict[str, str] = {}

    if run_full_matrix or changed_paths is None:
        # Full-matrix run (workflow_dispatch full validation): every category
        # is active, mirroring the legacy classifier's ``files is None`` branch.
        outputs["ci_workflows"] = "true"
        for unit_id in unit_ids:
            outputs[unit_id] = "true"
        run_all = "true"
    else:
        unknown = [path for path in changed_paths if not is_covered(contract, path)]
        if unknown:
            raise UnknownPathError(sorted(set(unknown)))
        # A change to the CI control plane forces the full matrix via run_all;
        # the per-category booleans stay at their per-glob values (every job's
        # ``if`` is ``run_all || <category>``, so run_all short-circuits). This
        # matches the legacy classifier byte-for-byte.
        ci_workflows = any(matches_force_full(contract, path) for path in changed_paths)
        activated: set[str] = set()
        for path in changed_paths:
            activated.update(matching_units(contract, path))
        outputs["ci_workflows"] = "true" if ci_workflows else "false"
        for unit_id in unit_ids:
            outputs[unit_id] = "true" if unit_id in activated else "false"
        run_all = "true" if ci_workflows else "false"

    outputs["run_all"] = run_all

    sonar_units = [unit.id for unit in contract.units if unit.sonar]
    outputs["run_sonar"] = (
        "true" if run_all == "true" or any(outputs.get(uid) == "true" for uid in sonar_units) else "false"
    )

    all_lint = _mcp_lint_packages(contract)
    all_test = _mcp_test_packages(contract)
    fanout = any(
        unit.mcp is not None and unit.mcp.fanout_all_on_change and outputs.get(unit.id) == "true"
        for unit in _mcp_units(contract)
    )
    if run_all == "true" or fanout:
        lint_packages = list(all_lint)
        test_packages = list(all_test)
    else:
        active_lint = {
            unit.mcp.package  # type: ignore[union-attr]
            for unit in _mcp_units(contract)
            if outputs.get(unit.id) == "true" and unit.responsibilities.get("lint")
        }
        lint_packages = [pkg for pkg in all_lint if pkg in active_lint]
        test_packages = [pkg for pkg in all_test if pkg in lint_packages]
    outputs["mcp_lint_any"] = "true" if lint_packages else "false"
    outputs["mcp_test_any"] = "true" if test_packages else "false"
    outputs["mcp_lint_packages"] = _json_compact(lint_packages)
    outputs["mcp_test_packages"] = _json_compact(test_packages)

    return outputs


def _json_compact(value: list[str]) -> str:
    import json

    return json.dumps(value)
