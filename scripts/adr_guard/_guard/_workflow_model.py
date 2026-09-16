"""Workflow-as-data model (_dw_*): safe YAML load, constrained expr eval, path filters.

The constrained ``if:`` expression evaluator lives in ``_workflow_model_expr``
(split out to keep each module under the file-length limit) and is re-exported
here, so this module remains the single import site for the whole model.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

from ._workflow_model_expr import (
    _DW_CANONICAL_REPOSITORY,
    _DW_EXPR_TOKEN,
    _DW_EXPR_WRAPPER,
    _DW_RESULT_REF,
    _DwExprError,
    _DwParser,
    _DwScenario,
    _DwShapeError,
    _dw_call_function,
    _dw_evaluate_if,
    _dw_evaluate_scenario,
    _dw_head_repo_full_name,
    _dw_job_denied_on_pull_request,
    _dw_job_denied_when_upstream,
    _dw_job_runs_when_eligible,
    _dw_loose_eq,
    _dw_normalize_expr,
    _dw_resolve_github,
    _dw_resolve_needs,
    _dw_resolve_operand,
    _dw_result_guarded_upstreams,
    _dw_tokenize,
    _dw_truthy,
    _dw_unwrap_expr,
)


_CORE_WORKFLOW_PATH = ".github/workflows/_core.yml"
_RANGE_WORKFLOW_PATH = ".github/workflows/_range.yml"
_PLATFORM_WORKFLOW_PATH = ".github/workflows/_shifter-platform.yml"


# ===========================================================================
# Deploy control-plane model + checks (ADR-003)
#
# The single workflow-as-data model for the deploy pipeline: it reads
# deploy.yml and the reusable deploy workflows as YAML and evaluates their
# `if:` gates, branch/event routing, and change filters semantically. The
# ADR-003-R5 runner-exposure check below runs on it as a hard gate; the
# consolidated test suite (scripts/adr_guard/tests/test_deploy_workflow.py)
# exercises the same model for the #781 upstream-gating, #892 branch/event
# matrix, and #913 change-filter invariants. No cloud calls, no Actions
# execution - only literal event/branch strings ever reach the env script.
# ===========================================================================
_ENGINE_WORKFLOW_PATH = ".github/workflows/_shifter-engine.yml"
_GCP_DEV_WORKFLOW_PATH = ".github/workflows/_gcp-dev.yml"
_DW_REUSABLE_WORKFLOW_PATHS = (
    _CORE_WORKFLOW_PATH,
    _RANGE_WORKFLOW_PATH,
    _ENGINE_WORKFLOW_PATH,
    _PLATFORM_WORKFLOW_PATH,
    _GCP_DEV_WORKFLOW_PATH,
)

# The top-level deploy workflow, used as the error-message name for the jobs and
# steps this model reads out of it.
_DW_DEPLOY_WORKFLOW_NAME = "deploy.yml"


def _dw_load_workflow(repo_root: Path, rel: str) -> dict[str, object]:
    """Load a workflow as a dict, normalizing the YAML 1.1 ``on:`` key.

    PyYAML resolves the bare word ``on`` to the Python boolean ``True``; map it
    back to the string ``"on"`` so callers can read triggers normally.
    """
    # local import: keeps PyYAML optional for non-deploy checks
    import yaml

    path = repo_root / rel
    if not path.is_file():
        raise _DwShapeError(f"workflow not found: {rel}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise _DwShapeError(f"{rel}: top-level YAML is not a mapping")
    # bare `on:` parsed as boolean True under YAML 1.1
    if True in data:
        data["on"] = data.pop(True)
    return data


def _dw_jobs(wf: dict[str, object], name: str = "<workflow>") -> dict[str, dict[str, object]]:
    """Return the workflow's ``jobs`` mapping, failing closed when it is absent."""
    js = wf.get("jobs")
    if not isinstance(js, dict) or not js:
        raise _DwShapeError(f"{name}: missing or empty 'jobs' mapping")
    return js


def _dw_get_job(wf: dict[str, object], job_id: str, name: str = "<workflow>") -> dict[str, object]:
    """Return one job by id, failing closed when the workflow has no such job."""
    js = _dw_jobs(wf, name)
    if job_id not in js:
        raise _DwShapeError(f"{name}: job '{job_id}' not found")
    return js[job_id]


def _dw_job_if(job: dict[str, object]) -> str:
    """Return the job's normalized ``if:`` expression, or ``""`` when it has none."""
    return _dw_normalize_expr(job.get("if", ""))


def _dw_runs_on(job: dict[str, object]) -> str | list[str] | None:
    """Return the job's ``runs-on`` value: a label, a list of labels, or None."""
    return job.get("runs-on")


# Runner labels the ADR-003-R5 exposure check treats as self-hosted-class. A
# GCP-native runner (issue #1546) registers with `--no-default-labels` + a custom
# label, so a job selecting it never carries the literal `self-hosted` label;
# without this set the exposure check would skip that job and leave a
# pull_request-reachability blind spot when GCP-dev CI is cut over to its own
# runner. New self-hosted runner labels (e.g. a future gcp-prod, or a per-account
# AWS tenant label) MUST be added here so the gate cannot be bypassed.
_SELF_HOSTED_CLASS_LABELS = frozenset({"self-hosted", "gcp-dev"})


def _dw_is_self_hosted(job: dict[str, object]) -> bool:
    """True iff the job selects a runner label treated as self-hosted-class."""
    ro = _dw_runs_on(job)
    if isinstance(ro, str):
        return ro in _SELF_HOSTED_CLASS_LABELS
    if isinstance(ro, (list, tuple)):
        return any(label in _SELF_HOSTED_CLASS_LABELS for label in ro)
    return False


def _dw_upstream_gating_violations(
    wf: dict[str, object], deploy_job_ids: Iterable[str]
) -> list[tuple[str, str, str]]:
    """Return ``[(job_id, upstream, result), ...]`` for deploy jobs that still
    RUN when a result-gated upstream is ``failure`` or ``cancelled`` (fail-open,
    the #781 class). Empty list means every deploy job fails closed."""
    found: list[tuple[str, str, str]] = []
    for jid in deploy_job_ids:
        expr = _dw_job_if(_dw_get_job(wf, jid, _DW_DEPLOY_WORKFLOW_NAME))
        for upstream in sorted(_dw_result_guarded_upstreams(expr)):
            for bad in ("failure", "cancelled"):
                if not _dw_job_denied_when_upstream(expr, upstream, bad):
                    found.append((jid, upstream, bad))
    return found


# --- dorny/paths-filter change-filter coverage (#913 / R-A2) --------------- #
def _dw_parse_paths_filter(
    wf: dict[str, object],
    job_id: str,
    step_id: str,
    name: str = _DW_DEPLOY_WORKFLOW_NAME,
) -> dict[str, list[str]]:
    """Return ``{filter_name: [patterns]}`` from a dorny/paths-filter step.

    The action's ``filters`` input is itself a YAML document (a block scalar in
    the workflow), so it is parsed a second time here."""
    import yaml

    job = _dw_get_job(wf, job_id, name)
    for step in job.get("steps", []) or []:
        if step.get("id") == step_id:
            raw = (step.get("with") or {}).get("filters")
            if not isinstance(raw, str):
                raise _DwShapeError(f"{name}:{step_id} has no string 'filters' input")
            parsed = yaml.safe_load(raw)
            if not isinstance(parsed, dict) or not parsed:
                raise _DwShapeError(f"{name}:{step_id} filters not a mapping")
            return {key: list(val) for key, val in parsed.items()}
    raise _DwShapeError(f"{name}:{job_id} has no step with id '{step_id}'")


def _dw_glob_to_regex(pattern: str) -> str:
    """Translate a micromatch-style glob to an anchored regex for the features
    the deploy filters use: ``**`` (any depth, incl. a trailing ``/`` matching
    zero or more directories), ``*`` (one path segment), and literal text."""
    i, n = 0, len(pattern)
    out = ["^"]
    while i < n:
        char = pattern[i]
        if char == "*":
            if pattern[i : i + 2] == "**":
                j = i + 2
                if pattern[j : j + 1] == "/":
                    # `**/` => zero or more directories
                    out.append("(?:.*/)?")
                    i = j + 1
                else:
                    out.append(".*")
                    i = j
            else:
                out.append("[^/]*")
                i += 1
        else:
            out.append(re.escape(char))
            i += 1
    out.append("$")
    return "".join(out)


def _dw_path_matches_any(path: str, patterns: Iterable[str]) -> bool:
    """True iff ``path`` matches any positive pattern. The deploy filters use no
    ``!`` negation and the default ``some`` quantifier, so positive-pattern
    membership is the full contract for them."""
    for pattern in patterns:
        if pattern.startswith("!"):
            continue
        if re.match(_dw_glob_to_regex(pattern), path):
            return True
    return False


# --- branch/event routing (#892) ------------------------------------------- #
def _dw_extract_set_environment_script(
    wf: dict[str, object], name: str = _DW_DEPLOY_WORKFLOW_NAME
) -> str:
    """Return the ``run`` body of the ``changes`` job's ``Set environment`` step."""
    job = _dw_get_job(wf, "changes", name)
    for step in job.get("steps", []) or []:
        if step.get("id") == "env" or step.get("name") == "Set environment":
            run = step.get("run")
            if not isinstance(run, str):
                raise _DwShapeError(f"{name}: 'Set environment' step has no run script")
            return run
    raise _DwShapeError(f"{name}: no 'Set environment' step in 'changes' job")


def _dw_evaluate_env(
    script: str, event_name: str, ref: str = "", base_ref: str = ""
) -> dict[str, str]:
    """Execute the workflow's own ``Set environment`` bash and return its
    ``GITHUB_OUTPUT`` key/value pairs. Only literal event/branch strings reach
    bash - no secrets, no shell trace - matching GitHub's default
    ``bash -e -o pipefail`` shell."""
    import tempfile

    rendered = script.replace("${{ github.event_name }}", event_name).replace(
        "${{ github.base_ref }}", base_ref
    )
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "github_output")
        Path(out_path).touch()
        env = {
            "PATH": os.environ.get("PATH", ""),
            "GITHUB_REF": ref,
            "GITHUB_OUTPUT": out_path,
        }
        proc = subprocess.run(
            ["bash", "-eo", "pipefail", "-c", rendered],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            raise _DwShapeError(
                f"Set environment script exited {proc.returncode}: {proc.stderr.strip()}"
            )
        outputs = {}
        for line in Path(out_path).read_text().splitlines():
            line = line.strip()
            if "=" in line:
                key, val = line.split("=", 1)
                outputs[key] = val
    return outputs


# Public surface of the workflow-as-data model, including the names re-exported
# from ``_workflow_model_expr`` so importers see one module.
__all__ = [
    "_CORE_WORKFLOW_PATH",
    "_DW_CANONICAL_REPOSITORY",
    "_DW_DEPLOY_WORKFLOW_NAME",
    "_DW_EXPR_TOKEN",
    "_DW_EXPR_WRAPPER",
    "_DW_RESULT_REF",
    "_DW_REUSABLE_WORKFLOW_PATHS",
    "_DwExprError",
    "_DwParser",
    "_DwScenario",
    "_DwShapeError",
    "_ENGINE_WORKFLOW_PATH",
    "_GCP_DEV_WORKFLOW_PATH",
    "_PLATFORM_WORKFLOW_PATH",
    "_RANGE_WORKFLOW_PATH",
    "_SELF_HOSTED_CLASS_LABELS",
    "_dw_call_function",
    "_dw_evaluate_env",
    "_dw_evaluate_if",
    "_dw_evaluate_scenario",
    "_dw_extract_set_environment_script",
    "_dw_get_job",
    "_dw_glob_to_regex",
    "_dw_head_repo_full_name",
    "_dw_is_self_hosted",
    "_dw_job_denied_on_pull_request",
    "_dw_job_denied_when_upstream",
    "_dw_job_if",
    "_dw_job_runs_when_eligible",
    "_dw_jobs",
    "_dw_load_workflow",
    "_dw_loose_eq",
    "_dw_normalize_expr",
    "_dw_parse_paths_filter",
    "_dw_path_matches_any",
    "_dw_resolve_github",
    "_dw_resolve_needs",
    "_dw_resolve_operand",
    "_dw_result_guarded_upstreams",
    "_dw_runs_on",
    "_dw_tokenize",
    "_dw_truthy",
    "_dw_unwrap_expr",
    "_dw_upstream_gating_violations",
]
