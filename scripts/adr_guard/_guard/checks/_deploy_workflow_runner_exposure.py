"""ADR-003-R5: no pull_request event reaches a self-hosted deploy job.

Evaluates each reusable deploy workflow's self-hosted job ``if:`` semantically
through the workflow-as-data model rather than by substring matching, so a guard
broadened with ``|| always()`` is still caught.
"""
from __future__ import annotations

from pathlib import Path

from .._common import (
    Violation,
    is_guard_source_path,
)
from .._workflow_model import (
    _DW_REUSABLE_WORKFLOW_PATHS,
    _DwShapeError,
    _dw_is_self_hosted,
    _dw_job_denied_on_pull_request,
    _dw_job_if,
    _dw_jobs,
    _dw_load_workflow,
)
from ._deploy_workflow_plan_scope import _DEPLOY_WORKFLOW_PATH


_RUNNER_EXPOSURE_CHECK = "deploy-workflow-runner-exposure"
_RUNNER_EXPOSURE_RULE = "ADR-003-R5"


def _runner_exposure_violation(path: str, message: str) -> Violation:
    """Build an ADR-003-R5 violation for the runner-exposure check."""
    return Violation(_RUNNER_EXPOSURE_CHECK, _RUNNER_EXPOSURE_RULE, path, message)


def _deploy_runner_exposure_relevant(files: list[str] | None) -> bool:
    """True when a changed file can affect ADR-003-R5 self-hosted runner exposure."""
    if files is None:
        return True
    relevant = set(_DW_REUSABLE_WORKFLOW_PATHS) | {
        _DEPLOY_WORKFLOW_PATH,
    }
    return any(path in relevant or is_guard_source_path(path) for path in files)


def _self_hosted_job_exposure_violations(
    rel: str, jid: str, job: dict[str, object]
) -> list[Violation]:
    """ADR-003-R5 violations for one self-hosted job of a reusable workflow."""
    try:
        denied = _dw_job_denied_on_pull_request(_dw_job_if(job))
    except _DwShapeError as exc:
        return [
            _runner_exposure_violation(
                rel,
                f"self-hosted job '{jid}' has an if-expression "
                f"ADR-003-R5 cannot evaluate: {exc}",
            )
        ]
    if denied:
        return []
    return [
        _runner_exposure_violation(
            rel,
            f"self-hosted job '{jid}' is reachable from a "
            "pull_request event; ADR-003-R5 requires it gate on "
            "github.event_name != 'pull_request'",
        )
    ]


def _runner_exposure_violations_for_workflow(repo_root: Path, rel: str) -> list[Violation]:
    """ADR-003-R5 violations for one reusable deploy workflow."""
    if not (repo_root / rel).exists():
        return [
            _runner_exposure_violation(
                rel,
                "Required reusable deploy workflow is missing; ADR-003-R5 "
                "cannot verify self-hosted runner exposure",
            )
        ]
    try:
        wf = _dw_load_workflow(repo_root, rel)
        job_map = _dw_jobs(wf, rel)
    except _DwShapeError as exc:
        return [
            _runner_exposure_violation(
                rel, f"workflow could not be parsed for ADR-003-R5: {exc}"
            )
        ]
    violations: list[Violation] = []
    for jid, job in job_map.items():
        if _dw_is_self_hosted(job):
            violations.extend(_self_hosted_job_exposure_violations(rel, jid, job))
    return violations


def check_deploy_runner_exposure(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """No pull_request event may reach a self-hosted deploy job (ADR-003-R5).

    Evaluates each reusable deploy workflow's self-hosted job ``if:`` for a
    pull_request event and requires it to fail closed. Semantic evaluation, not
    substring matching: a guard broadened with ``|| always()`` is still caught.
    """
    if not _deploy_runner_exposure_relevant(files):
        return []

    violations: list[Violation] = []
    for rel in _DW_REUSABLE_WORKFLOW_PATHS:
        violations.extend(_runner_exposure_violations_for_workflow(repo_root, rel))
    return violations
