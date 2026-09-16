"""Routing-reachability invariant of the quality-ownership check (ADR-004-R24).

Proves, against the real `_quality.yml`, that a representative change to each
quality unit makes its declared jobs (and matrix members) run and that a
docs-only change selects none of them. Split out of ``quality_ownership.py`` to
keep each module under the file-length limit; every public name here is
re-imported by that module so the package surface is unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from types import ModuleType

from .._common import Violation
from .._workflow_model import (
    _DwExprError,
    _DwParser,
    _DwShapeError,
    _dw_job_if,
    _dw_normalize_expr,
    _dw_tokenize,
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
)


def _quality_probe_path(pattern: str) -> str:
    """Turn a unit path pattern into a concrete file path that matches it."""
    if pattern.endswith("/**"):
        return pattern[:-3].rstrip("/") + "/__probe__"
    return pattern


def _quality_strip_if(if_expr: object) -> str:
    """Normalize a job ``if:`` and strip an enclosing ``${{ }}`` wrapper."""
    expr = _dw_normalize_expr(if_expr)
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2].strip()
    return expr


# Workflow inputs the routing probe holds fixed: `skip_tests` false and
# `run_stack_smoke` true keep test/smoke jobs eligible.
_QUALITY_INPUT_VALUES = {
    "skip_tests": False,
    "run_full_matrix": False,
    "run_stack_smoke": True,
}


def _quality_resolve_operand(pathstr: str, outputs: dict[str, str]) -> str | bool:
    """Resolve one ``if:`` operand against the controlled paths-output map;
    an operand outside that vocabulary is an error rather than a default."""
    parts = pathstr.split(".")
    if parts[:3] == ["needs", "paths", "outputs"] and len(parts) >= 4:
        value = outputs.get(parts[3], "false")
    elif parts[0] == "needs":
        value = "success" if len(parts) >= 3 and parts[2] == "result" else "true"
    elif parts[0] == "inputs":
        value = _QUALITY_INPUT_VALUES.get(parts[1] if len(parts) > 1 else "", False)
    elif parts[0] == "github":
        value = ""
    else:
        raise _DwExprError(f"unresolvable operand: {pathstr}")
    return value


def _quality_eval_if(if_expr: object, outputs: dict[str, str]) -> bool:
    """Evaluate a job ``if:`` against a controlled paths-output map, so routing
    is proven semantically (not by substring). ``needs.paths.outputs.<key>``
    resolves from ``outputs``; other operands are permissive; ``skip_tests`` is
    false and ``run_stack_smoke`` true so test/smoke jobs are eligible."""
    expr = _quality_strip_if(if_expr)
    if not expr:
        return True
    parser = _DwParser(
        _dw_tokenize(expr), lambda pathstr: _quality_resolve_operand(pathstr, outputs)
    )
    return _dw_truthy(parser.evaluate())


def _quality_job_reachable(
    jobs: _QualityJobs,
    job_id: str,
    outputs: dict[str, str],
    seen: set[str] | None = None,
) -> bool:
    """A job runs iff its own ``if:`` is true AND every job it ``needs`` runs
    (transitively) - the real GitHub gating semantics, so a matrix generator or
    other upstream gate is honoured."""
    seen = seen or set()
    job = jobs.get(job_id)
    if job is None or job_id in seen:
        return job is not None
    if not _quality_eval_if(_dw_job_if(job), outputs):
        return False
    needs = job.get("needs") or []
    if isinstance(needs, str):
        needs = [needs]
    return all(
        _quality_job_reachable(jobs, need, outputs, seen | {job_id}) for need in needs
    )


_QUALITY_MATRIX_OUTPUT = {"mcp-lint": "mcp_lint_packages", "mcp-tests": "mcp_test_packages"}


def _quality_matrix_reachable(
    ref: _QualityJobRef,
    resp: str,
    unit: _QualityUnit,
    outputs: dict[str, str],
    jobs: _QualityJobs,
    viol: _QualityViol,
) -> list[Violation]:
    """Verify a declared matrix member is selected for the unit's probe change,
    and that the real job drives its matrix from the declared classifier output."""
    matrix = dict(ref.matrix)
    package = matrix.get("package")
    key = _QUALITY_MATRIX_OUTPUT.get(ref.job)
    if key is None:
        return []
    violations = []
    try:
        selected = json.loads(outputs.get(key, "[]"))
    except json.JSONDecodeError:
        selected = []
    if package not in selected:
        violations.append(
            viol(
                _QUALITY_WORKFLOW_REL,
                f"quality unit {unit.id!r} {resp} matrix member package={package!r} "
                f"is not selected in {key} when {unit.id!r} changes",
            )
        )
    # Verify the real job actually consumes that output as its matrix source, so
    # a job wired to the wrong JSON output (or a hard-coded matrix) is caught
    # rather than trusting the classifier value alone.
    matrix_key = next(iter(matrix), None)
    job = jobs.get(ref.job) or {}
    strategy = job.get("strategy") or {}
    matrix_spec = strategy.get("matrix") or {}
    matrix_source = str(matrix_spec.get(matrix_key, "")) if matrix_key else ""
    if "fromjson" not in matrix_source.lower() or f"needs.paths.outputs.{key}" not in matrix_source:
        violations.append(
            viol(
                _QUALITY_WORKFLOW_REL,
                f"job {ref.job!r} strategy.matrix.{matrix_key} must consume "
                f"fromJSON(needs.paths.outputs.{key}) (found {matrix_source!r}); "
                "the matrix must be driven by the declared output, not a fixed list",
            )
        )
    return violations


def _quality_output_wiring_violations(
    contract: _QualityContract,
    module: ModuleType,
    jobs: _QualityJobs,
    viol: _QualityViol,
) -> list[Violation]:
    """Verify the real paths-job output export edges, not just the classifier's
    values: every classifier-emitted key is exported as
    ``steps.detect.outputs.<key>`` (a mis-wired key silently breaks routing),
    and no classifier-sourced output exists that the contract does not emit."""
    violations = []
    paths_job = jobs.get("paths")
    if not isinstance(paths_job, dict):
        return [viol(_QUALITY_WORKFLOW_REL, "paths job is missing from the workflow")]
    declared = paths_job.get("outputs") or {}
    emitted = set(module.compute_outputs(contract, None, run_full_matrix=True).keys())
    for key in sorted(emitted):
        if key not in declared:
            violations.append(
                viol(
                    _QUALITY_WORKFLOW_REL,
                    f"paths job does not export classifier output {key!r}",
                )
            )
        elif f"steps.detect.outputs.{key}" not in str(declared[key]):
            violations.append(
                viol(
                    _QUALITY_WORKFLOW_REL,
                    f"paths output {key!r} is not wired to steps.detect.outputs.{key} "
                    f"(found {declared[key]!r}); a mis-wired output silently breaks routing",
                )
            )
    for key, value in declared.items():
        if "steps.detect.outputs." in str(value) and key not in emitted:
            violations.append(
                viol(
                    _QUALITY_WORKFLOW_REL,
                    f"paths output {key!r} is sourced from the classifier but is not an "
                    "emitted contract output",
                )
            )
    return violations


@dataclass(frozen=True)
class _QualityProbe:
    """One unit's routing probe: the representative changed path, the
    responsibility under test, and the classifier outputs the path produced."""

    unit: _QualityUnit
    resp: str
    path: str
    outputs: dict[str, str]


def _quality_ref_routing_violations(
    ref: _QualityJobRef, probe: _QualityProbe, jobs: _QualityJobs, viol: _QualityViol
) -> list[Violation]:
    """Routing violations for one declared job reference: the job (and any
    matrix member it declares) must run when the probe path changes."""
    if ref.job not in jobs:
        # missing-job already reported by completeness
        return []
    try:
        reachable = _quality_job_reachable(jobs, ref.job, probe.outputs)
    except _DwShapeError as exc:
        return [
            viol(
                _QUALITY_WORKFLOW_REL,
                f"quality unit {probe.unit.id!r} {probe.resp} job {ref.job!r} has an "
                f"if-expression the routing model cannot evaluate: {exc}",
            )
        ]
    if not reachable:
        violations = [
            viol(
                _QUALITY_WORKFLOW_REL,
                f"quality unit {probe.unit.id!r} {probe.resp} job {ref.job!r} does not "
                f"run when {probe.path!r} changes (routing unreachable)",
            )
        ]
    elif ref.matrix:
        violations = _quality_matrix_reachable(
            ref, probe.resp, probe.unit, probe.outputs, jobs, viol
        )
    else:
        violations = []
    return violations


def _quality_unit_routing_violations(
    unit: _QualityUnit,
    contract: _QualityContract,
    module: ModuleType,
    jobs: _QualityJobs,
    viol: _QualityViol,
) -> list[Violation]:
    """Routing violations for one unit: a representative change to it must make
    every job it declares run."""
    path = _quality_probe_path(unit.paths[0])
    try:
        outputs = module.compute_outputs(contract, [path])
    # UnknownPathError / ContractError
    except Exception as exc:
        return [
            viol(
                _QUALITY_CONTRACT_REL,
                f"cannot classify probe {path!r} for unit {unit.id!r}: {exc}",
            )
        ]
    violations: list[Violation] = []
    for resp, refs in unit.responsibilities.items():
        probe = _QualityProbe(unit=unit, resp=resp, path=path, outputs=outputs)
        for ref in refs:
            violations += _quality_ref_routing_violations(ref, probe, jobs, viol)
    return violations


def _quality_docs_only_violations(
    contract: _QualityContract,
    module: ModuleType,
    jobs: _QualityJobs,
    viol: _QualityViol,
) -> list[Violation]:
    """A docs-only change must not select any declared production job."""
    docs_probe = "docs/__probe__.md"
    try:
        neg = module.compute_outputs(contract, [docs_probe])
    except Exception:
        return []
    declared_jobs = {
        ref.job
        for unit in contract.units
        for refs in unit.responsibilities.values()
        for ref in refs
        if ref.job in jobs
    }
    violations = []
    for job_id in sorted(declared_jobs):
        try:
            selected = _quality_job_reachable(jobs, job_id, neg)
        except _DwShapeError:
            # unevaluatable if already reported above
            continue
        if selected:
            violations.append(
                viol(
                    _QUALITY_WORKFLOW_REL,
                    f"production job {job_id!r} is selected by a docs-only "
                    f"change ({docs_probe!r}); an exclusion must not route "
                    "production jobs",
                )
            )
    return violations


def _quality_routing_reachability(
    contract: _QualityContract,
    module: ModuleType,
    jobs: _QualityJobs,
    viol: _QualityViol,
) -> list[Violation]:
    """Routing reachability: each unit's declared jobs must run for a change to
    it, and a docs-only change must select none of them."""
    violations: list[Violation] = []
    for unit in contract.units:
        violations += _quality_unit_routing_violations(unit, contract, module, jobs, viol)
    violations += _quality_docs_only_violations(contract, module, jobs, viol)
    return violations
