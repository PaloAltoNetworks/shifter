"""ADR-003-R2 plan-scope identity, relevance predicates, and skip-tests policy.

Holds the constants and leaf checks shared by the plan-scope family: which
workflows the check reads, how a violation is built, when the check is relevant
to a changed-file set, the concurrency policy for apply-capable runs, and the
rule that unit tests may never be skipped through commit-message flags.
"""
from __future__ import annotations

import re

from .._common import (
    Violation,
    is_guard_source_path,
)
from .._workflow_model import (
    _CORE_WORKFLOW_PATH,
    _PLATFORM_WORKFLOW_PATH,
    _RANGE_WORKFLOW_PATH,
)
from ._deploy_workflow_text import (
    _active_line_contains,
    _extract_job_if,
    _workflow_job_block,
)


_DEPLOY_WORKFLOW_PATH = ".github/workflows/deploy.yml"
_PLAN_SCOPE_CHECK = "deploy-workflow-plan-scope"
_PLAN_SCOPE_RULE = "ADR-003-R2"
_QUALITY_WORKFLOW_PATH = ".github/workflows/_quality.yml"
_SKIP_TESTS_LITERAL = "skip_tests: false"
_SKIP_TESTS_FORBIDDEN_MARKERS = (
    "[skip tests]",
    "[skip quality]",
    "Check for skip flags",
)
# Lint / architecture / security jobs in _quality.yml that must never be gated
# on inputs.skip_tests (ADR-003-R2 / issue #760).
_QUALITY_SKIP_TESTS_IMMUNE_JOB_SUFFIXES = ("-lint", "-lint-js", "-sast", "-arch")
_QUALITY_SKIP_TESTS_IMMUNE_JOB_NAMES = frozenset(
    {
        "adr-conformance",
        "workflow-lint",
        "terraform-lint",
        "security-iac",
        "security-k8s",
        "secrets-gitleaks",
        "k8s-lint",
        "k8s-schema",
        "mcp-lint",
    }
)
_QUALITY_JOB_NAME_RE = re.compile(r"^ {2}([a-z0-9_-]+):\s*$")
# `cancel-in-progress:` values that cannot kill an in-flight Terraform apply.
_SAFE_CANCELLATION_VALUES = frozenset({"false", "${{ false }}"})
_PULL_REQUEST_EVENT_GUARDS = (
    "github.event_name == 'pull_request'",
    'github.event_name == "pull_request"',
)


def _plan_scope_violation(path: str, message: str) -> Violation:
    """Build an ADR-003-R2 violation for the deploy-workflow-plan-scope check."""
    return Violation(_PLAN_SCOPE_CHECK, _PLAN_SCOPE_RULE, path, message)


def _deploy_plan_scope_relevant(files: list[str] | None) -> bool:
    """True when a changed file can affect ADR-003-R2 plan-scope routing."""
    if files is None:
        return True
    relevant = {
        _DEPLOY_WORKFLOW_PATH,
        _CORE_WORKFLOW_PATH,
        _RANGE_WORKFLOW_PATH,
        _PLATFORM_WORKFLOW_PATH,
        _QUALITY_WORKFLOW_PATH,
    }
    return any(path in relevant or is_guard_source_path(path) for path in files)


def _should_check_plan_scope_file(files: list[str] | None, path: str) -> bool:
    """True when the named workflow must be inspected for this changed-file set."""
    return files is None or path in files or any(is_guard_source_path(f) for f in files)


def _plan_scope_checks_deploy_and_platform(files: list[str] | None) -> bool:
    """True when the deploy and platform workflows are in scope for this run."""
    return files is None or any(
        path in {_DEPLOY_WORKFLOW_PATH, _PLATFORM_WORKFLOW_PATH} or is_guard_source_path(path)
        for path in files
    )


def _quality_job_is_skip_tests_immune(job_name: str) -> bool:
    """True for lint/architecture/security jobs that must ignore `skip_tests`."""
    if job_name in _QUALITY_SKIP_TESTS_IMMUNE_JOB_NAMES:
        return True
    return any(job_name.endswith(suffix) for suffix in _QUALITY_SKIP_TESTS_IMMUNE_JOB_SUFFIXES)


def _quality_workflow_job_names(quality_text: str) -> list[str]:
    """Return the job ids declared under `jobs:` in `_quality.yml`."""
    names: list[str] = []
    in_jobs = False
    for raw_line in quality_text.splitlines():
        if raw_line.strip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if raw_line and not raw_line.startswith(" "):
            break
        match = _QUALITY_JOB_NAME_RE.match(raw_line)
        if match:
            names.append(match.group(1))
    return names


def _check_deploy_workflow_skip_tests_policy(deploy_text: str) -> list[Violation]:
    """ADR-003-R2: commit-message / dynamic test skips are not accepted."""
    violations: list[Violation] = []
    lowered = deploy_text.lower()
    for marker in _SKIP_TESTS_FORBIDDEN_MARKERS:
        if marker.lower() in lowered:
            violations.append(
                _plan_scope_violation(
                    _DEPLOY_WORKFLOW_PATH,
                    f"Commit-message or label-based test skips are not accepted; "
                    f"remove `{marker}` handling from the deploy workflow",
                )
            )
            break

    quality_block = _workflow_job_block(deploy_text, "quality")
    if not quality_block:
        return violations
    if not (
        _active_line_contains(quality_block, "_quality.yml")
        or _active_line_contains(quality_block, "./.github/workflows/_quality.yml")
    ):
        return violations
    if not _active_line_contains(quality_block, _SKIP_TESTS_LITERAL):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The Quality reusable-workflow call must pass "
                f"`{_SKIP_TESTS_LITERAL}` literally so protected-branch CI "
                "cannot bypass unit tests through commit-message flags",
            )
        )
    if _active_line_contains(quality_block, "skip_tests: ${{") or _active_line_contains(
        quality_block, "skip_tests:${{"
    ):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The Quality reusable-workflow call must not derive "
                "`skip_tests` from step outputs or commit-message parsing",
            )
        )
    return violations


def _check_quality_workflow_skip_tests_contract(quality_text: str) -> list[Violation]:
    """Architecture, lint, and security jobs must not honor ``inputs.skip_tests``."""
    violations: list[Violation] = []
    for job_name in _quality_workflow_job_names(quality_text):
        if not _quality_job_is_skip_tests_immune(job_name):
            continue
        block = _workflow_job_block(quality_text, job_name)
        if not block:
            continue
        if_expr = _extract_job_if(block)
        if "skip_tests" in if_expr:
            violations.append(
                _plan_scope_violation(
                    _QUALITY_WORKFLOW_PATH,
                    f"Job `{job_name}` must not be gated on `inputs.skip_tests`; "
                    "lint, architecture, and security checks run even when unit "
                    "tests are skipped",
                )
            )
    return violations


def _deploy_concurrency_cancel_value(deploy_text: str) -> str | None:
    """Return the first non-comment `cancel-in-progress:` value, or None."""
    for line in deploy_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped.startswith("cancel-in-progress:"):
            continue
        return stripped.split(":", 1)[1].strip()
    return None


def _concurrency_cancellation_is_safe(cancel_value: str) -> bool:
    """True when cancellation is disabled or restricted to pull_request runs."""
    normalized = cancel_value.strip()
    if normalized in _SAFE_CANCELLATION_VALUES:
        return True
    return any(guard in normalized for guard in _PULL_REQUEST_EVENT_GUARDS)


def _check_deploy_concurrency_queues_apply_runs(deploy_text: str) -> list[Violation]:
    """Require deploy runs that can apply infrastructure to queue, not cancel.

    PR cancellation is still allowed because PR runs do not execute environment
    branch applies. A global `true` cancellation policy can kill Terraform
    mid-apply on `aws-dev` / `gcp-dev` pushes.
    """
    cancel_value = _deploy_concurrency_cancel_value(deploy_text)
    if cancel_value is None or _concurrency_cancellation_is_safe(cancel_value):
        return []
    return [
        _plan_scope_violation(
            _DEPLOY_WORKFLOW_PATH,
            "Deploy workflow concurrency must queue env-branch apply runs instead "
            "of cancelling an in-flight Terraform apply; restrict cancellation to "
            "pull_request runs or set `cancel-in-progress: false`",
        )
    ]
