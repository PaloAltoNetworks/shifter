"""Production-path quality-ownership reconciliation (ADR-004-R24).

The contract shapes and loader live in ``_quality_ownership_model`` and the
routing-reachability invariant in ``_quality_ownership_routing`` (split out to
keep each module under the file-length limit); both are re-exported here, so
this module remains the single import site for the check.
"""
from __future__ import annotations

from pathlib import Path
from types import ModuleType

from .._common import (
    Violation,
    _git_tracked_all,
    _walk_all_files,
)
from .._workflow_model import (
    _DwShapeError,
    _dw_jobs,
    _dw_load_workflow,
    _dw_truthy,
)
from ._quality_ownership_model import (
    _QUALITY_CONTRACT_REL,
    _QUALITY_WORKFLOW_REL,
    _QualityContract,
    _QualityJobRef,
    _QualityJobs,
    _QualityUnit,
    _QualityViol,
    _load_quality_module,
    _quality_load_contract,
)
from ._quality_ownership_routing import (
    _QUALITY_INPUT_VALUES,
    _QUALITY_MATRIX_OUTPUT,
    _QualityProbe,
    _quality_docs_only_violations,
    _quality_eval_if,
    _quality_job_reachable,
    _quality_matrix_reachable,
    _quality_output_wiring_violations,
    _quality_probe_path,
    _quality_ref_routing_violations,
    _quality_resolve_operand,
    _quality_routing_reachability,
    _quality_strip_if,
    _quality_unit_routing_violations,
)
from .layer_imports import (
    _classified_packages,
)


# --------------------------------------------------------------------------- #
# Production-path quality-ownership conformance (#1530, GEN-002, ADR-004-R24)
#
# Reconciles .github/quality-path-filters.yaml (the single versioned
# quality-ownership contract) against the repository. Three invariants:
#   1. estate completeness  - every tracked path is a production owner or a
#      typed exclusion (unknown fails closed);
#   2. ownership completeness - every production PATH is covered, across the
#      union of its matching units, by a blocking lint AND security AND test
#      job (advisory / continue-on-error / missing jobs do not count); genuine
#      gaps are recorded as time-bounded docs/adr/exceptions.yaml entries;
#   3. routing reachability  - a representative change to each unit makes its
#      declared jobs (and matrix members) run in the real _quality.yml, while a
#      docs-only change does not select production jobs.
# The schema itself is parsed once by scripts/quality_ownership/contract.py -
# the same module the _quality.yml `paths` job uses - so there is no second
# implementation of the contract.
# --------------------------------------------------------------------------- #
_QUALITY_RULE = "ADR-004-R24"
_QUALITY_CHECK = "quality-path-ownership"
_QUALITY_RESPONSIBILITIES = ("lint", "security", "test")
# Evidence-only jobs: soft-fail, always-run, or advisory scanners that cannot
# by themselves own a required responsibility (per the #1530 preflight).
_QUALITY_ADVISORY_JOBS = frozenset(
    {
        "security-trivy-advisory",
        "security-osv-advisory",
        "secrets-gitleaks",
        "sonarcloud",
        "security-k8s",
    }
)


def _quality_job_blocking(jobref: _QualityJobRef, jobs: _QualityJobs) -> tuple[bool, str]:
    """Return ``(is_blocking, why_not)`` for a declared job reference: only a
    present, non-advisory, non-continue-on-error job can own a responsibility."""
    if jobref.job not in jobs:
        why = "missing"
    elif jobref.job in _QUALITY_ADVISORY_JOBS:
        why = "advisory"
    elif _dw_truthy(jobs[jobref.job].get("continue-on-error")):
        why = "continue-on-error"
    else:
        why = ""
    return (not why, why)


def _quality_reference_violations(
    contract: _QualityContract, jobs: _QualityJobs, viol: _QualityViol
) -> list[Violation]:
    """Flag every responsibility whose declared job cannot own it."""
    violations = []
    for unit in contract.units:
        for resp, refs in unit.responsibilities.items():
            for ref in refs:
                ok, why = _quality_job_blocking(ref, jobs)
                if not ok:
                    violations.append(
                        viol(
                            f"{_QUALITY_CONTRACT_REL}#{unit.id}:{resp}",
                            f"quality unit {unit.id!r} {resp} references {why} job "
                            f"{ref.job!r}; an advisory / continue-on-error / missing "
                            "job cannot own a responsibility",
                        )
                    )
    return violations


def _quality_satisfied_responsibilities(
    contract: _QualityContract, jobs: _QualityJobs
) -> dict[str, set[str]]:
    """Map each unit id to the responsibilities a blocking job actually owns."""
    return {
        unit.id: {
            resp
            for resp, refs in unit.responsibilities.items()
            if any(_quality_job_blocking(ref, jobs)[0] for ref in refs)
        }
        for unit in contract.units
    }


def _quality_coverage_gaps(
    contract: _QualityContract,
    module: ModuleType,
    tracked: list[str],
    satisfies: dict[str, set[str]],
) -> dict[tuple[str, str], str]:
    """Map ``(owning unit, uncovered responsibility)`` to an example path, for
    every production path the union of its matching units does not cover."""
    gaps: dict[tuple[str, str], str] = {}
    for path in tracked:
        units_here = module.matching_units(contract, path)
        if not units_here:
            continue
        covered: set[str] = set()
        for unit_id in units_here:
            covered |= satisfies.get(unit_id, set())
        missing = set(_QUALITY_RESPONSIBILITIES) - covered
        if missing:
            owner = module.most_specific_unit(contract, path) or units_here[0]
            for resp in missing:
                gaps.setdefault((owner, resp), path)
    return gaps


def _quality_ownership_completeness(
    contract: _QualityContract,
    module: ModuleType,
    tracked: list[str],
    jobs: _QualityJobs,
    viol: _QualityViol,
) -> list[Violation]:
    """Ownership completeness: every production path must be covered by a
    blocking lint AND security AND test job across its matching units."""
    violations = _quality_reference_violations(contract, jobs, viol)
    satisfies = _quality_satisfied_responsibilities(contract, jobs)
    gaps = _quality_coverage_gaps(contract, module, tracked, satisfies)
    for (unit_id, resp), path in sorted(gaps.items()):
        violations.append(
            viol(
                f"{_QUALITY_CONTRACT_REL}#{unit_id}:{resp}",
                f"no blocking {resp} owner for quality unit {unit_id!r} "
                f"(e.g. {path}); add a blocking {resp} job or record a time-bounded "
                "docs/adr/exceptions.yaml entry for this gap",
            )
        )
    return violations


def _quality_package_reconciliation(
    contract: _QualityContract, repo_root: Path, viol: _QualityViol
) -> list[Violation]:
    """Reconcile the units' declared packages against the #1523 classification:
    neither side may reference a package the other does not know about."""
    try:
        classified = _classified_packages(repo_root)
    except Exception as exc:
        return [
            viol(
                _QUALITY_CONTRACT_REL,
                f"cannot load the #1523 package classification: {exc}",
            )
        ]
    declared: set[str] = set()
    for unit in contract.units:
        declared |= set(unit.packages)
    violations = []
    for pkg in sorted(declared - classified):
        violations.append(
            viol(
                _QUALITY_CONTRACT_REL,
                f"quality unit references package {pkg!r} that is not in the #1523 "
                "classification (scripts/check_layer_imports/layer_imports.yaml)",
            )
        )
    for pkg in sorted(classified - declared):
        violations.append(
            viol(
                _QUALITY_CONTRACT_REL,
                f"#1523 first-party package {pkg!r} has no quality-ownership unit",
            )
        )
    return violations


def check_quality_path_ownership(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Reconcile the quality-ownership contract (whole-tree invariant)."""
    # whole-tree invariant
    del files

    def viol(path: str, message: str) -> Violation:
        """Build a violation of this check for `path`."""
        return Violation(_QUALITY_CHECK, _QUALITY_RULE, path, message)

    try:
        module, contract = _quality_load_contract(repo_root)
    except _DwShapeError as exc:
        return [viol(_QUALITY_CONTRACT_REL, str(exc))]

    tracked = _git_tracked_all(repo_root)
    if tracked is None:
        tracked = _walk_all_files(repo_root)

    violations: list[Violation] = [
        viol(_QUALITY_CONTRACT_REL, err)
        for err in module.estate_violations(contract, tracked)
    ]

    try:
        workflow = _dw_load_workflow(repo_root, _QUALITY_WORKFLOW_REL)
        jobs = _dw_jobs(workflow, _QUALITY_WORKFLOW_REL)
    except _DwShapeError as exc:
        return violations + [viol(_QUALITY_WORKFLOW_REL, str(exc))]

    violations += _quality_ownership_completeness(contract, module, tracked, jobs, viol)
    violations += _quality_output_wiring_violations(contract, module, jobs, viol)
    violations += _quality_routing_reachability(contract, module, jobs, viol)
    violations += _quality_package_reconciliation(contract, repo_root, viol)
    return violations


# Public surface of the check, including the names re-exported from the
# ``_quality_ownership_model`` / ``_quality_ownership_routing`` siblings.
__all__ = [
    "_QUALITY_ADVISORY_JOBS",
    "_QUALITY_CHECK",
    "_QUALITY_CONTRACT_REL",
    "_QUALITY_INPUT_VALUES",
    "_QUALITY_MATRIX_OUTPUT",
    "_QUALITY_RESPONSIBILITIES",
    "_QUALITY_RULE",
    "_QUALITY_WORKFLOW_REL",
    "_QualityContract",
    "_QualityJobRef",
    "_QualityJobs",
    "_QualityProbe",
    "_QualityUnit",
    "_QualityViol",
    "_load_quality_module",
    "_quality_coverage_gaps",
    "_quality_docs_only_violations",
    "_quality_eval_if",
    "_quality_job_blocking",
    "_quality_job_reachable",
    "_quality_load_contract",
    "_quality_matrix_reachable",
    "_quality_output_wiring_violations",
    "_quality_ownership_completeness",
    "_quality_package_reconciliation",
    "_quality_probe_path",
    "_quality_ref_routing_violations",
    "_quality_reference_violations",
    "_quality_resolve_operand",
    "_quality_routing_reachability",
    "_quality_satisfied_responsibilities",
    "_quality_strip_if",
    "_quality_unit_routing_violations",
    "check_quality_path_ownership",
]
