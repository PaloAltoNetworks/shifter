"""ADR-004-R26: the out-of-band global/iam stack has a CI drift-check workflow.

``platform/terraform/global/iam`` (the GitHub Actions OIDC deploy role) is
applied out-of-band, not by the deploy pipeline, so a merged ``github-oidc.tf``
change can go un-applied and the live role drifts behind committed config - the
recurring "new resource -> next deploy 403s" churn (issue #247). This guard
pins the drift-check workflow's *contract*, not disconnected tokens, so a later
edit cannot silently remove or weaken the gate. It proves, on one designated
privileged plan job:

* the workflow triggers only in a trusted context - ``push`` is required and the
  only other allowed event is ``workflow_dispatch``; ``pull_request`` /
  ``pull_request_target`` / any other event is rejected (ADR-003-R5, because the
  plan assumes the deploy role);
* ``push`` is restricted to the protected branches (a non-empty subset of
  ``{dev, main}``) and path-scoped to ``global/iam``;
* one step runs a real ``terraform plan -detailed-exitcode`` (not an echoed or
  commented line), whose effective working directory is ``global/iam``, whose
  exit status is not swallowed (no ``|| true`` / ``exit 0`` / ``continue-on-error``),
  so a non-empty (drift) plan fails the build.

The check reads the workflow as data through the shared ``_dw_*`` model; it does
not evaluate the plan, only its declared shape.
"""
from __future__ import annotations

import re
from pathlib import Path

from .._common import Violation, is_guard_source_path
from .._workflow_model import _DwShapeError, _dw_jobs, _dw_load_workflow

_IAM_DRIFT_CHECK = "global-iam-drift-check"
_IAM_DRIFT_RULE = "ADR-004-R26"
_IAM_DRIFT_WORKFLOW_PATH = ".github/workflows/iam-drift-check.yml"
_GLOBAL_IAM_DIR = "platform/terraform/global/iam"

# The credentialed drift plan may run only in a trusted context: push is
# required; workflow_dispatch is the only other allowed event. Any other event
# (pull_request, pull_request_target, schedule, workflow_run, ...) is rejected so
# a later edit cannot expose the deploy-role job to an untrusted event.
_ALLOWED_EVENTS = frozenset({"push", "workflow_dispatch"})
# Protected branches the drift plan is allowed to run on.
_PROTECTED_BRANCHES = frozenset({"dev", "main"})
# Exit-neutralizing constructs that would let a non-empty (drift) plan report
# success. `exit 0` anywhere in the plan step is treated as swallowing, because
# the canonical form lets terraform's non-zero exit propagate untouched.
_SWALLOW_TOKENS = ("|| true", "||true", "|| :", "||:")
_EXIT_ZERO_RE = re.compile(r"\bexit\s+0\b")
# A terraform plan invocation at a command boundary (line start or after a shell
# separator), optionally with a -chdir before `plan`. `echo terraform plan ...`
# does not match because terraform is an echo argument, not a command.
_PLAN_RE = re.compile(r"(?:^|;|&&|\|\|)\s*terraform\s+(?:-chdir=\S+\s+)?plan\b")


def _iam_drift_violation(message: str) -> Violation:
    """Build an ADR-004-R26 violation for the drift-check guard."""
    return Violation(_IAM_DRIFT_CHECK, _IAM_DRIFT_RULE, _IAM_DRIFT_WORKFLOW_PATH, message)


def _iam_drift_relevant(files: list[str] | None) -> bool:
    """True when a changed file can affect ADR-004-R26 drift-check coverage."""
    if files is None:
        return True
    return any(
        path == _IAM_DRIFT_WORKFLOW_PATH
        or path.startswith(_GLOBAL_IAM_DIR)
        or is_guard_source_path(path)
        for path in files
    )


def _truthy(value: object) -> bool:
    """True for a YAML boolean true or the literal string 'true'."""
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _trigger_events(on: object) -> set[str]:
    """Return the set of event names in the workflow's ``on:`` trigger."""
    if isinstance(on, str):
        return {on}
    # Iterating a list yields its items; iterating a dict yields its keys - both
    # are the event names.
    if isinstance(on, (list, dict)):
        return {str(item) for item in on}
    return set()


def _trigger_violations(wf: dict[str, object]) -> list[Violation]:
    """ADR-004-R26 violations for the workflow's event/branch/path triggers."""
    on = wf.get("on")
    events = _trigger_events(on)
    violations: list[Violation] = []
    if "push" not in events:
        violations.append(
            _iam_drift_violation(
                "the global/iam drift-check must trigger on push to a protected branch"
            )
        )
    extra = events - _ALLOWED_EVENTS
    if extra:
        violations.append(
            _iam_drift_violation(
                "the global/iam drift-check must not trigger on any event other than push "
                f"(or workflow_dispatch); a deploy-role job must not be reachable from "
                f"{sorted(extra)} (ADR-003-R5)"
            )
        )
    push_cfg = on.get("push") if isinstance(on, dict) else None
    if not isinstance(push_cfg, dict):
        violations.append(
            _iam_drift_violation(
                "the push trigger must restrict branches to the protected set and paths to "
                "platform/terraform/global/iam"
            )
        )
        return violations
    branches = push_cfg.get("branches")
    if (
        not isinstance(branches, list)
        or not branches
        or any(str(b) not in _PROTECTED_BRANCHES for b in branches)
    ):
        violations.append(
            _iam_drift_violation(
                "the push trigger branches must be a non-empty subset of {dev, main}"
            )
        )
    paths = push_cfg.get("paths")
    if not isinstance(paths, list) or not any(_GLOBAL_IAM_DIR in str(p) for p in paths):
        violations.append(
            _iam_drift_violation(
                "the push trigger paths must be scoped to platform/terraform/global/iam"
            )
        )
    return violations


def _line_is_real_plan(line: str) -> bool:
    """True when the line is a genuine ``terraform plan -detailed-exitcode`` command."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    return (
        bool(_PLAN_RE.search(line))
        and "-detailed-exitcode" in line
        and not any(tok in line for tok in _SWALLOW_TOKENS)
    )


def _run_swallows_exit(run_body: str) -> bool:
    """True when the run body neutralizes a non-zero (drift) exit status."""
    if _EXIT_ZERO_RE.search(run_body):
        return True
    return any(tok in run_body for tok in _SWALLOW_TOKENS)


def _job_default_working_dir(job: dict[str, object]) -> str:
    """Return the job's ``defaults.run.working-directory``, or ''."""
    defaults = job.get("defaults")
    if isinstance(defaults, dict):
        default_run = defaults.get("run")
        if isinstance(default_run, dict):
            wd = default_run.get("working-directory")
            if isinstance(wd, str):
                return wd
    return ""


def _step_is_designated_drift_plan(step: dict[str, object], job_wd: str) -> bool:
    """True when this step is a valid, global/iam-scoped, non-swallowed drift plan."""
    run = step.get("run")
    if _truthy(step.get("continue-on-error")) or not isinstance(run, str):
        return False
    plan_lines = [line for line in run.splitlines() if _line_is_real_plan(line)]
    if not plan_lines or _run_swallows_exit(run):
        return False
    step_wd = step.get("working-directory")
    effective_wd = step_wd if isinstance(step_wd, str) else job_wd
    return _GLOBAL_IAM_DIR in effective_wd or any(
        _GLOBAL_IAM_DIR in line for line in plan_lines
    )


def _has_designated_drift_plan(jobs: dict[str, dict[str, object]]) -> bool:
    """True when one job carries a valid designated drift plan step."""
    for job in jobs.values():
        if not isinstance(job, dict) or _truthy(job.get("continue-on-error")):
            continue
        job_wd = _job_default_working_dir(job)
        for step in job.get("steps", []) or []:
            if isinstance(step, dict) and _step_is_designated_drift_plan(step, job_wd):
                return True
    return False


def check_global_iam_drift_check(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Require a CI drift-check workflow for the out-of-band global/iam stack (ADR-004-R26)."""
    if not _iam_drift_relevant(files):
        return []
    try:
        wf = _dw_load_workflow(repo_root, _IAM_DRIFT_WORKFLOW_PATH)
        jobs = _dw_jobs(wf, _IAM_DRIFT_WORKFLOW_PATH)
    except _DwShapeError as exc:
        return [
            _iam_drift_violation(
                "the global/iam drift-check workflow is missing or unparseable "
                f"({exc}); global/iam is applied out-of-band and needs a CI "
                "terraform-plan drift gate (issue #247)"
            )
        ]
    violations = _trigger_violations(wf)
    if not _has_designated_drift_plan(jobs):
        violations.append(
            _iam_drift_violation(
                "one job step must run a real `terraform plan -detailed-exitcode`, with its "
                "effective working directory scoped to platform/terraform/global/iam and "
                "without swallowing its exit status (no `|| true`, `exit 0`, or "
                "continue-on-error), so a non-empty (drift) plan fails the build"
            )
        )
    return violations
