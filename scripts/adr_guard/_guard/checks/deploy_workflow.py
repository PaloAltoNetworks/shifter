"""Deploy/workflow gating checks and CI action-pinning / OIDC integrity.

The rule families live in sibling private modules and are re-imported here so
this module's namespace (and therefore the ``adr_guard`` facade surface and the
``_registry`` wiring) is unchanged:

- ``_deploy_workflow_text``            - raw workflow-text block readers
- ``_deploy_workflow_plan_scope``      - ADR-003-R2 identity and skip-tests policy
- ``_deploy_workflow_routing``         - ADR-003-R2 change-routing classifiers
- ``_deploy_workflow_terraform``       - ADR-003-R2 Terraform plan/apply integrity
- ``_deploy_workflow_portal``          - ADR-003-R4 portal deploy-mode source of truth
- ``_deploy_workflow_tfvars``          - ADR-011-R7 deploy tfvars rendering
- ``_deploy_workflow_fail_loud``       - ADR-003-R3 fail-loud deploy verification
- ``_deploy_workflow_runner_exposure`` - ADR-003-R5 self-hosted runner exposure
- ``_deploy_workflow_action_pin``      - ADR-037-R1 action SHA pinning

What remains here is the ADR-003-R2 plan-scope entry point, which spans several
of those families, and the ADR-004-R15 OIDC role check.
"""
from __future__ import annotations

import re
from pathlib import Path

from .._common import (
    Violation,
    is_guard_source_path,
)
from .._workflow_model import (
    _CORE_WORKFLOW_PATH,
    _DW_REUSABLE_WORKFLOW_PATHS,
    _DwShapeError,
    _PLATFORM_WORKFLOW_PATH,
    _RANGE_WORKFLOW_PATH,
    _dw_is_self_hosted,
    _dw_job_denied_on_pull_request,
    _dw_job_if,
    _dw_jobs,
    _dw_load_workflow,
)
from ._deploy_workflow_action_pin import (
    _ACTION_PIN_CHECK,
    _ACTION_PIN_OCI_DIGEST,
    _ACTION_PIN_RULE,
    _ACTION_PIN_SHA40,
    _CLOUD_AUTH_ACTIONS,
    _DW_NAMED_SECRET_RE,
    _action_pin_violation,
    _dw_iter_strings,
    _dw_iter_uses_refs,
    _dw_iter_workflow_files,
    _dw_job_forwards_secrets,
    _dw_job_is_cloud_credentialed,
    _dw_job_steps,
    _dw_permissions_grant_id_token,
    _dw_references_named_secret,
    _dw_step_uses,
    _dw_step_uses_cloud_auth,
    _dw_uses_is_sha_pinned,
    _dw_workflow_is_cloud_credentialed,
    _workflow_action_pin_relevant,
    check_workflow_action_sha_pinning,
)
from ._deploy_workflow_fail_loud import (
    _ENGINE_BOOTSTRAP_INPUT,
    _ENGINE_TASKDEF_STEP,
    _ENGINE_WORKFLOW_PATH,
    _FAIL_LOUD_CHECK,
    _FAIL_LOUD_RULE,
    _GUAC_STABILIZE_STEP,
    _check_engine_task_family_fails,
    _check_guacamole_timeout_fails,
    _fail_loud_relevant,
    _fail_loud_violation,
    check_deploy_verification_fail_loud,
)
from ._deploy_workflow_plan_scope import (
    _DEPLOY_WORKFLOW_PATH,
    _PLAN_SCOPE_CHECK,
    _PLAN_SCOPE_RULE,
    _QUALITY_SKIP_TESTS_IMMUNE_JOB_NAMES,
    _QUALITY_SKIP_TESTS_IMMUNE_JOB_SUFFIXES,
    _QUALITY_WORKFLOW_PATH,
    _SKIP_TESTS_FORBIDDEN_MARKERS,
    _SKIP_TESTS_LITERAL,
    _check_deploy_concurrency_queues_apply_runs,
    _check_deploy_workflow_skip_tests_policy,
    _check_quality_workflow_skip_tests_contract,
    _deploy_plan_scope_relevant,
    _plan_scope_checks_deploy_and_platform,
    _plan_scope_violation,
    _quality_job_is_skip_tests_immune,
    _quality_workflow_job_names,
    _should_check_plan_scope_file,
)
from ._deploy_workflow_portal import (
    _PORTAL_DEPLOY_HELPER_PATH,
    _PORTAL_DEPLOY_MODE_CHECK,
    _PORTAL_DEPLOY_MODE_RULE,
    _PORTAL_DEV_OUTPUTS_PATH,
    _PORTAL_PROD_OUTPUTS_PATH,
    _check_portal_deploy_helper,
    _check_portal_deploy_mode_outputs,
    _check_portal_deploy_mode_workflow,
    _portal_deploy_mode_relevant,
    _portal_deploy_mode_violation,
    check_portal_deploy_mode_source_of_truth,
)
from ._deploy_workflow_routing import (
    _PORTAL_IMAGE_BUILD_INPUT,
    _PORTAL_IMAGE_DEPLOY_CONDITION,
    _PORTAL_IMAGE_OUTPUT,
    _PORTAL_IMAGE_REQUIRED_GLOB,
    _PR_GATE_SKIPPED_QUALITY_GUARD,
    _QUALITY_GUARDRAIL_DOCS_REQUIRED_GLOBS,
    _QUALITY_NON_DOCS_REQUIRED_GLOBS,
    _QUALITY_ONLY_OUTPUT,
    _QUALITY_ONLY_REQUIRED_GLOBS,
    _QUALITY_PREDICATE,
    _QUALITY_RELEVANT_CONDITION,
    _QUALITY_RELEVANT_OUTPUT,
    _check_deploy_workflow_plan_routing,
    _check_deploy_workflow_portal_image_routing,
    _check_deploy_workflow_quality_only_routing,
    _check_platform_build_portal_image_gate,
    _platform_app_source_globs,
)
from ._deploy_workflow_iam_drift import (
    _GLOBAL_IAM_DIR,
    _IAM_DRIFT_CHECK,
    _IAM_DRIFT_RULE,
    _IAM_DRIFT_WORKFLOW_PATH,
    _iam_drift_relevant,
    _iam_drift_violation,
    check_global_iam_drift_check,
)
from ._deploy_workflow_runner_exposure import (
    _RUNNER_EXPOSURE_CHECK,
    _RUNNER_EXPOSURE_RULE,
    _deploy_runner_exposure_relevant,
    _runner_exposure_violation,
    check_deploy_runner_exposure,
)
from ._deploy_workflow_terraform import (
    _TERRAFORM_PLAN_FILE,
    _check_saved_plan_apply_contract,
    _check_terraform_plan_lock_timeout,
    _check_terraform_workflow_integrity,
    _line_removes_tfplan,
    _terraform_apply_uses_saved_plan,
    _terraform_plan_has_lock_timeout,
    _terraform_plan_writes_saved_plan,
)
from ._deploy_workflow_text import (
    _active_line_contains,
    _block_contains_glob,
    _extract_job_if,
    _filter_globs,
    _noncomment_contains,
    _paths_filter_block,
    _workflow_job_block,
    _workflow_step_block,
)
from ._deploy_workflow_tfvars import (
    _LOCAL_AUTO_TFVARS,
    _TF_CONSUMING_SUBCOMMANDS,
    _TFVARS_RENDER_CHECK,
    _TFVARS_RENDER_JOBS,
    _TFVARS_RENDER_RULE,
    _is_terraform_consuming_command,
    _tfvars_render_violation,
    _tfvars_render_violations_for_workflow,
    _writes_local_auto_tfvars,
    check_platform_renders_deploy_tfvars,
)


def _deploy_workflow_plan_scope_violations(repo_root: Path) -> list[Violation]:
    """ADR-003-R2 violations for the top-level deploy workflow."""
    deploy_path = repo_root / _DEPLOY_WORKFLOW_PATH
    if not deploy_path.exists():
        return [
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R2 cannot verify platform plan routing",
            )
        ]
    deploy_text = deploy_path.read_text(encoding="utf-8")
    violations: list[Violation] = []
    violations.extend(_check_deploy_concurrency_queues_apply_runs(deploy_text))
    violations.extend(_check_deploy_workflow_plan_routing(deploy_text))
    violations.extend(_check_deploy_workflow_quality_only_routing(deploy_text))
    violations.extend(_check_deploy_workflow_portal_image_routing(deploy_text))
    violations.extend(_check_deploy_workflow_skip_tests_policy(deploy_text))
    return violations


def _quality_workflow_plan_scope_violations(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """ADR-003-R2 violations for the reusable Quality workflow."""
    if not _should_check_plan_scope_file(files, _QUALITY_WORKFLOW_PATH):
        return []
    quality_path = repo_root / _QUALITY_WORKFLOW_PATH
    if not quality_path.exists():
        return [
            _plan_scope_violation(
                _QUALITY_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R2 cannot verify "
                "architecture/security independence from skip_tests",
            )
        ]
    return _check_quality_workflow_skip_tests_contract(
        quality_path.read_text(encoding="utf-8")
    )


def _terraform_workflow_plan_scope_violations(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """ADR-003-R2 Terraform integrity violations for the core and range workflows."""
    violations: list[Violation] = []
    for path in (_CORE_WORKFLOW_PATH, _RANGE_WORKFLOW_PATH):
        if not _should_check_plan_scope_file(files, path):
            continue
        workflow_path = repo_root / path
        if not workflow_path.exists():
            violations.append(
                _plan_scope_violation(
                    path,
                    "Required workflow is missing; ADR-003-R2 cannot verify Terraform "
                    "lock-timeout and saved-plan apply integrity",
                )
            )
            continue
        violations.extend(
            _check_terraform_workflow_integrity(workflow_path.read_text(encoding="utf-8"), path)
        )
    return violations


def _platform_workflow_plan_scope_violations(repo_root: Path) -> list[Violation]:
    """ADR-003-R2 violations for the reusable AWS platform workflow."""
    platform_path = repo_root / _PLATFORM_WORKFLOW_PATH
    if not platform_path.exists():
        return [
            _plan_scope_violation(
                _PLATFORM_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R2 cannot verify platform "
                "Terraform plan commands",
            )
        ]
    platform_text = platform_path.read_text(encoding="utf-8")
    violations: list[Violation] = []
    violations.extend(_check_terraform_workflow_integrity(platform_text, _PLATFORM_WORKFLOW_PATH))
    violations.extend(_check_platform_build_portal_image_gate(platform_text))
    return violations


def check_deploy_workflow_plan_scope(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Keep AWS platform PR planning scoped to Terraform inputs."""
    if not _deploy_plan_scope_relevant(files):
        return []

    check_deploy_and_platform = _plan_scope_checks_deploy_and_platform(files)
    violations: list[Violation] = []
    if check_deploy_and_platform:
        violations.extend(_deploy_workflow_plan_scope_violations(repo_root))
    violations.extend(_quality_workflow_plan_scope_violations(repo_root, files))
    violations.extend(_terraform_workflow_plan_scope_violations(repo_root, files))
    if check_deploy_and_platform:
        violations.extend(_platform_workflow_plan_scope_violations(repo_root))
    return violations


_GITHUB_OIDC_TF_PATH = "platform/terraform/global/iam/github-oidc.tf"
_GITHUB_OIDC_ADMIN_POLICY_RE = re.compile(
    r'policy_arn\s*=\s*"arn:aws:iam::aws:policy/AdministratorAccess"'
)


def _github_oidc_check_relevant(files: list[str] | None) -> bool:
    """True when the OIDC Terraform file or the guard facade itself changed."""
    if files is None:
        return True
    return _GITHUB_OIDC_TF_PATH in files or any(
        path.endswith("adr_guard.py") for path in files
    )


def check_github_oidc_no_admin_access(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid AdministratorAccess attachment on the GitHub Actions OIDC role (ADR-004-R15)."""
    if not _github_oidc_check_relevant(files):
        return []

    path = repo_root / _GITHUB_OIDC_TF_PATH
    if not path.is_file() or not _GITHUB_OIDC_ADMIN_POLICY_RE.search(
        path.read_text(encoding="utf-8")
    ):
        return []

    return [
        Violation(
            "github-oidc-no-admin-access",
            "ADR-004-R15",
            _GITHUB_OIDC_TF_PATH,
            "GitHub Actions OIDC role must not attach managed AdministratorAccess; "
            "use scoped inline or managed policies required by CI workflows.",
        )
    ]


# Names re-imported from the sibling rule modules above plus this module's own
# entry points. Declared so the re-exports that preserve this module's namespace
# (the ``adr_guard`` facade copies it wholesale) are not read as unused imports.
__all__ = [
    "_ACTION_PIN_CHECK",
    "_ACTION_PIN_OCI_DIGEST",
    "_ACTION_PIN_RULE",
    "_ACTION_PIN_SHA40",
    "_CLOUD_AUTH_ACTIONS",
    "_CORE_WORKFLOW_PATH",
    "_DEPLOY_WORKFLOW_PATH",
    "_DW_NAMED_SECRET_RE",
    "_DW_REUSABLE_WORKFLOW_PATHS",
    "_DwShapeError",
    "_ENGINE_BOOTSTRAP_INPUT",
    "_ENGINE_TASKDEF_STEP",
    "_ENGINE_WORKFLOW_PATH",
    "_FAIL_LOUD_CHECK",
    "_FAIL_LOUD_RULE",
    "_GITHUB_OIDC_TF_PATH",
    "_GLOBAL_IAM_DIR",
    "_GUAC_STABILIZE_STEP",
    "_IAM_DRIFT_CHECK",
    "_IAM_DRIFT_RULE",
    "_IAM_DRIFT_WORKFLOW_PATH",
    "_LOCAL_AUTO_TFVARS",
    "_PLAN_SCOPE_CHECK",
    "_PLAN_SCOPE_RULE",
    "_PLATFORM_WORKFLOW_PATH",
    "_PORTAL_DEPLOY_HELPER_PATH",
    "_PORTAL_DEPLOY_MODE_CHECK",
    "_PORTAL_DEPLOY_MODE_RULE",
    "_PORTAL_DEV_OUTPUTS_PATH",
    "_PORTAL_IMAGE_BUILD_INPUT",
    "_PORTAL_IMAGE_DEPLOY_CONDITION",
    "_PORTAL_IMAGE_OUTPUT",
    "_PORTAL_IMAGE_REQUIRED_GLOB",
    "_PORTAL_PROD_OUTPUTS_PATH",
    "_PR_GATE_SKIPPED_QUALITY_GUARD",
    "_QUALITY_GUARDRAIL_DOCS_REQUIRED_GLOBS",
    "_QUALITY_NON_DOCS_REQUIRED_GLOBS",
    "_QUALITY_ONLY_OUTPUT",
    "_QUALITY_ONLY_REQUIRED_GLOBS",
    "_QUALITY_PREDICATE",
    "_QUALITY_RELEVANT_CONDITION",
    "_QUALITY_RELEVANT_OUTPUT",
    "_QUALITY_SKIP_TESTS_IMMUNE_JOB_NAMES",
    "_QUALITY_SKIP_TESTS_IMMUNE_JOB_SUFFIXES",
    "_QUALITY_WORKFLOW_PATH",
    "_RANGE_WORKFLOW_PATH",
    "_RUNNER_EXPOSURE_CHECK",
    "_RUNNER_EXPOSURE_RULE",
    "_SKIP_TESTS_FORBIDDEN_MARKERS",
    "_SKIP_TESTS_LITERAL",
    "_TERRAFORM_PLAN_FILE",
    "_TFVARS_RENDER_CHECK",
    "_TFVARS_RENDER_JOBS",
    "_TFVARS_RENDER_RULE",
    "_TF_CONSUMING_SUBCOMMANDS",
    "Violation",
    "_action_pin_violation",
    "_active_line_contains",
    "_block_contains_glob",
    "_check_deploy_concurrency_queues_apply_runs",
    "_check_deploy_workflow_plan_routing",
    "_check_deploy_workflow_portal_image_routing",
    "_check_deploy_workflow_quality_only_routing",
    "_check_deploy_workflow_skip_tests_policy",
    "_check_engine_task_family_fails",
    "_check_guacamole_timeout_fails",
    "_check_platform_build_portal_image_gate",
    "_check_portal_deploy_helper",
    "_check_portal_deploy_mode_outputs",
    "_check_portal_deploy_mode_workflow",
    "_check_quality_workflow_skip_tests_contract",
    "_check_saved_plan_apply_contract",
    "_check_terraform_plan_lock_timeout",
    "_check_terraform_workflow_integrity",
    "_deploy_plan_scope_relevant",
    "_deploy_runner_exposure_relevant",
    "_dw_is_self_hosted",
    "_dw_iter_strings",
    "_dw_iter_uses_refs",
    "_dw_iter_workflow_files",
    "_dw_job_denied_on_pull_request",
    "_dw_job_forwards_secrets",
    "_dw_job_if",
    "_dw_job_is_cloud_credentialed",
    "_dw_job_steps",
    "_dw_jobs",
    "_dw_load_workflow",
    "_dw_permissions_grant_id_token",
    "_dw_references_named_secret",
    "_dw_step_uses",
    "_dw_step_uses_cloud_auth",
    "_dw_uses_is_sha_pinned",
    "_dw_workflow_is_cloud_credentialed",
    "_extract_job_if",
    "_fail_loud_relevant",
    "_fail_loud_violation",
    "_filter_globs",
    "_iam_drift_relevant",
    "_iam_drift_violation",
    "_is_terraform_consuming_command",
    "_line_removes_tfplan",
    "_noncomment_contains",
    "_paths_filter_block",
    "_plan_scope_checks_deploy_and_platform",
    "_plan_scope_violation",
    "_platform_app_source_globs",
    "_portal_deploy_mode_relevant",
    "_portal_deploy_mode_violation",
    "_quality_job_is_skip_tests_immune",
    "_quality_workflow_job_names",
    "_runner_exposure_violation",
    "_should_check_plan_scope_file",
    "_terraform_apply_uses_saved_plan",
    "_terraform_plan_has_lock_timeout",
    "_terraform_plan_writes_saved_plan",
    "_tfvars_render_violation",
    "_tfvars_render_violations_for_workflow",
    "_workflow_action_pin_relevant",
    "_workflow_job_block",
    "_workflow_step_block",
    "_writes_local_auto_tfvars",
    "check_deploy_runner_exposure",
    "check_deploy_verification_fail_loud",
    "check_deploy_workflow_plan_scope",
    "check_github_oidc_no_admin_access",
    "check_global_iam_drift_check",
    "check_platform_renders_deploy_tfvars",
    "check_portal_deploy_mode_source_of_truth",
    "check_workflow_action_sha_pinning",
    "is_guard_source_path",
]
