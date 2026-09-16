"""ADR-003-R4: the AWS portal deploy path is derived from Terraform state.

Single-instance versus autoscaling deployment is a property of what Terraform
actually applied, so the deploy job must resolve it from Terraform outputs
through `scripts/portal_deploy/portal_deploy.py` and verify the running image
digest on every in-service instance, rather than trusting a GitHub variable.
"""
from __future__ import annotations

from pathlib import Path

from .._common import (
    Violation,
    is_guard_source_path,
)
from .._workflow_model import _PLATFORM_WORKFLOW_PATH
from ._deploy_workflow_text import (
    _active_line_contains,
    _workflow_job_block,
)


_PORTAL_DEPLOY_MODE_CHECK = "portal-deploy-mode-source-of-truth"
_PORTAL_DEPLOY_MODE_RULE = "ADR-003-R4"
_PORTAL_DEPLOY_HELPER_PATH = "scripts/portal_deploy/portal_deploy.py"
_PORTAL_DEV_OUTPUTS_PATH = "platform/terraform/environments/dev/portal/outputs.tf"
_PORTAL_PROD_OUTPUTS_PATH = "platform/terraform/environments/prod/portal/outputs.tf"


def _portal_deploy_mode_relevant(files: list[str] | None) -> bool:
    """True when a changed file can affect ADR-003-R4 portal deploy-mode resolution."""
    if files is None:
        return True
    relevant = {
        _PLATFORM_WORKFLOW_PATH,
        _PORTAL_DEPLOY_HELPER_PATH,
        _PORTAL_DEV_OUTPUTS_PATH,
        _PORTAL_PROD_OUTPUTS_PATH,
    }
    return any(path in relevant or is_guard_source_path(path) for path in files)


def _portal_deploy_mode_violation(path: str, message: str) -> Violation:
    """Build an ADR-003-R4 violation for the portal deploy-mode check."""
    return Violation(_PORTAL_DEPLOY_MODE_CHECK, _PORTAL_DEPLOY_MODE_RULE, path, message)


def _check_portal_deploy_mode_workflow(platform_text: str) -> list[Violation]:
    """Require the platform deploy job to resolve mode from Terraform state."""
    violations: list[Violation] = []
    deploy_block = _workflow_job_block(platform_text, "deploy")
    if not deploy_block:
        return [
            _portal_deploy_mode_violation(
                _PLATFORM_WORKFLOW_PATH,
                "The platform deploy job is missing; ADR-003-R4 cannot verify portal "
                "deployment-mode source-of-truth handling",
            )
        ]
    if "AWS_PORTAL_ENABLE_AUTOSCALING" in platform_text:
        violations.append(
            _portal_deploy_mode_violation(
                _PLATFORM_WORKFLOW_PATH,
                "`AWS_PORTAL_ENABLE_AUTOSCALING` must not drive the AWS portal deploy "
                "path; derive deployment mode from Terraform outputs instead",
            )
        )
    if not (
        _active_line_contains(deploy_block, _PORTAL_DEPLOY_HELPER_PATH)
        and _active_line_contains(deploy_block, "resolve-topology")
    ):
        violations.append(
            _portal_deploy_mode_violation(
                _PLATFORM_WORKFLOW_PATH,
                "The deploy job must call `scripts/portal_deploy/portal_deploy.py "
                "resolve-topology` so the deploy path is derived from Terraform state",
            )
        )
    if not (
        _active_line_contains(deploy_block, "verify-asg-image")
        and _active_line_contains(deploy_block, "--image-digest")
    ):
        violations.append(
            _portal_deploy_mode_violation(
                _PLATFORM_WORKFLOW_PATH,
                "The ASG deploy path must call `verify-asg-image` after instance refresh "
                "with `--image-digest` so every in-service instance is checked for the "
                "new portal image digest",
            )
        )
    return violations


def _check_portal_deploy_mode_outputs(repo_root: Path) -> list[Violation]:
    """Require each AWS portal environment to expose `enable_autoscaling`."""
    violations: list[Violation] = []
    for outputs_path in (_PORTAL_DEV_OUTPUTS_PATH, _PORTAL_PROD_OUTPUTS_PATH):
        path = repo_root / outputs_path
        if not path.exists():
            violations.append(
                _portal_deploy_mode_violation(
                    outputs_path,
                    "Portal Terraform outputs are missing; ADR-003-R4 requires "
                    '`output "enable_autoscaling"` in each AWS portal environment',
                )
            )
            continue
        text = path.read_text(encoding="utf-8")
        if 'output "enable_autoscaling"' not in text:
            violations.append(
                _portal_deploy_mode_violation(
                    outputs_path,
                    'Portal Terraform outputs must expose `output "enable_autoscaling"` '
                    "so the deploy workflow reads the same mode Terraform applied",
                )
            )
    return violations


def _check_portal_deploy_helper(helper_text: str) -> list[Violation]:
    """Require the portal deploy helper to resolve mode and verify ASG images."""
    checks = (
        (
            "terraform output -json",
            "The portal deploy helper must read Terraform outputs, not a GitHub variable",
        ),
        (
            "len(running_instance_ids) != 1",
            "The portal deploy helper must fail unless single-instance mode finds exactly one "
            "running tagged instance",
        ),
        (
            "Reservations[].Instances[].InstanceId",
            "The portal deploy helper must query all matching running instances and must not "
            "pick `Reservations[0].Instances[0]`",
        ),
        (
            "describe-auto-scaling-groups",
            "The portal deploy helper must verify the Terraform ASG exists before choosing "
            "the ASG deploy path",
        ),
        (
            "send-command",
            "The portal deploy helper must use SSM to verify the running portal image digest "
            "on ASG instances",
        ),
        (
            "docker inspect",
            "The portal deploy helper must inspect the running portal container image during "
            "ASG verification",
        ),
        (
            "get-command-invocation",
            "The portal deploy helper must check each ASG instance's SSM verification result",
        ),
    )
    violations: list[Violation] = []
    for needle, message in checks:
        if needle not in helper_text:
            violations.append(
                _portal_deploy_mode_violation(_PORTAL_DEPLOY_HELPER_PATH, message)
            )
            break
    return violations


def check_portal_deploy_mode_source_of_truth(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Ensure the AWS portal deploy path is derived from Terraform state."""
    if not _portal_deploy_mode_relevant(files):
        return []

    violations: list[Violation] = []
    platform_path = repo_root / _PLATFORM_WORKFLOW_PATH
    helper_path = repo_root / _PORTAL_DEPLOY_HELPER_PATH

    if not platform_path.exists():
        violations.append(
            _portal_deploy_mode_violation(
                _PLATFORM_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R4 cannot verify portal "
                "deployment-mode source-of-truth handling",
            )
        )
    else:
        violations.extend(
            _check_portal_deploy_mode_workflow(platform_path.read_text(encoding="utf-8"))
        )

    violations.extend(_check_portal_deploy_mode_outputs(repo_root))

    if not helper_path.exists():
        violations.append(
            _portal_deploy_mode_violation(
                _PORTAL_DEPLOY_HELPER_PATH,
                "Portal deploy helper is missing; ADR-003-R4 requires a tested helper "
                "for Terraform-derived mode resolution and ASG image verification",
            )
        )
    else:
        violations.extend(_check_portal_deploy_helper(helper_path.read_text(encoding="utf-8")))

    return violations
