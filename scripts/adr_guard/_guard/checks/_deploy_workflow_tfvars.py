"""ADR-011-R7: AWS Terraform deploy jobs render `local.auto.tfvars` first.

The committed `terraform.tfvars` under `platform/terraform/environments/*` is an
intentionally-broken `example.com` baseline, so each Terraform-running job must
write the deployment-owned override before Terraform consumes variables.
"""
from __future__ import annotations

from pathlib import Path

from .._common import (
    Violation,
    is_guard_source_path,
)
from .._workflow_model import (
    _CORE_WORKFLOW_PATH,
    _PLATFORM_WORKFLOW_PATH,
    _RANGE_WORKFLOW_PATH,
)
from ._deploy_workflow_text import _workflow_job_block


_TFVARS_RENDER_CHECK = "aws-platform-renders-deploy-tfvars"
_TFVARS_RENDER_RULE = "ADR-011-R7"
# Jobs in `_shifter-platform.yml` that run Terraform against the portal root
# and therefore must render the deployment-owned override first.
_TFVARS_RENDER_JOBS = ("plan", "apply")
_LOCAL_AUTO_TFVARS = "local.auto.tfvars"
# `terraform` subcommands that consume variable values. `fmt`, `show`, and
# `output` do not, so the render step may legitimately sit after a `fmt` check.
_TF_CONSUMING_SUBCOMMANDS = ("init", "validate", "plan", "apply")


def _tfvars_render_violation(path: str, message: str) -> Violation:
    """Build an ADR-011-R7 violation for the deploy-tfvars-render check."""
    return Violation(_TFVARS_RENDER_CHECK, _TFVARS_RENDER_RULE, path, message)


def _is_terraform_consuming_command(stripped_line: str) -> bool:
    """True when the line runs a terraform subcommand that consumes variables."""
    if stripped_line.lstrip().startswith("#"):
        return False
    return any(f"terraform {sub}" in stripped_line for sub in _TF_CONSUMING_SUBCOMMANDS)


def _writes_local_auto_tfvars(stripped_line: str) -> bool:
    """True when the line redirects output *into* local.auto.tfvars.

    A line that merely names the file (e.g. the step's `name:`) is not
    proof of a render — only a write redirection (`> local.auto.tfvars`,
    including a path-prefixed `> dir/local.auto.tfvars`) counts, so the
    guard verifies executable behavior rather than a label.
    """
    if stripped_line.lstrip().startswith("#"):
        return False
    marker_pos = stripped_line.find(_LOCAL_AUTO_TFVARS)
    if marker_pos == -1:
        return False
    redirect_pos = stripped_line.find(">")
    return 0 <= redirect_pos < marker_pos


def _tfvars_render_violations_for_workflow(workflow_path: str, text: str) -> list[Violation]:
    """Return ADR-011-R7 violations for one reusable workflow file."""
    violations: list[Violation] = []
    for job in _TFVARS_RENDER_JOBS:
        block = _workflow_job_block(text, job)
        if not block:
            violations.append(
                _tfvars_render_violation(
                    workflow_path,
                    f"`{job}` job is missing; ADR-011-R7 expects it to render "
                    f"`{_LOCAL_AUTO_TFVARS}` before Terraform consumes variables",
                )
            )
            continue
        render_idx = next(
            (i for i, line in enumerate(block) if _writes_local_auto_tfvars(line)),
            None,
        )
        tf_idx = next(
            (i for i, line in enumerate(block) if _is_terraform_consuming_command(line)),
            None,
        )
        if render_idx is None:
            violations.append(
                _tfvars_render_violation(
                    workflow_path,
                    f"`{job}` job must render `{_LOCAL_AUTO_TFVARS}` from the deployment "
                    "secret (a step that writes the file, not merely names it) before "
                    "`terraform init/validate/plan/apply`, so the deploy never applies "
                    "the committed example.com baseline",
                )
            )
        elif tf_idx is not None and render_idx > tf_idx:
            violations.append(
                _tfvars_render_violation(
                    workflow_path,
                    f"`{job}` job renders `{_LOCAL_AUTO_TFVARS}` after a Terraform "
                    "command; the render must precede `terraform init/validate/plan/apply`",
                )
            )
    return violations


def check_platform_renders_deploy_tfvars(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Require AWS Terraform deploy jobs to render local.auto.tfvars first.

    The committed `terraform.tfvars` under `platform/terraform/environments/*`
    is an intentionally-broken `example.com` baseline. Each Terraform-running
    job in the AWS reusable workflows must render the deployment-owned override
    into a gitignored `local.auto.tfvars` before `terraform init/validate/plan/apply`
    consumes variables, so deploys never apply the baseline (ADR-011-R7).
    """
    workflow_paths = (_PLATFORM_WORKFLOW_PATH, _CORE_WORKFLOW_PATH, _RANGE_WORKFLOW_PATH)
    if files is not None and not any(
        path in {*workflow_paths} or is_guard_source_path(path) for path in files
    ):
        return []

    violations: list[Violation] = []
    for workflow_path in workflow_paths:
        workflow_file = repo_root / workflow_path
        if not workflow_file.exists():
            continue
        violations.extend(
            _tfvars_render_violations_for_workflow(
                workflow_path,
                workflow_file.read_text(encoding="utf-8"),
            )
        )
    return violations
