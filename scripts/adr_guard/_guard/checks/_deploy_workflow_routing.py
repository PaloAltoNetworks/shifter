"""ADR-003-R2 change-routing contracts for `deploy.yml` and `_shifter-platform.yml`.

The deploy workflow routes a push or PR to Quality and to the platform build
through `dorny/paths-filter` classifiers. These checks keep the classifiers and
the job conditions that consume them intact, so a docs-only diff is the only
Quality skip path and an app-only diff still builds and deploys the portal image.
"""
from __future__ import annotations

from .._common import Violation
from .._workflow_model import _PLATFORM_WORKFLOW_PATH
from ._deploy_workflow_plan_scope import (
    _DEPLOY_WORKFLOW_PATH,
    _plan_scope_violation,
)
from ._deploy_workflow_text import (
    _active_line_contains,
    _block_contains_glob,
    _filter_globs,
    _paths_filter_block,
    _workflow_job_block,
)


_QUALITY_RELEVANT_OUTPUT = (
    "quality_relevant: ${{ steps.quality_non_docs.outputs.non_docs == 'true' || "
    "steps.quality_guardrails.outputs.guardrail_docs == 'true' || "
    "steps.filter.outputs.any_changed != 'true' }}"
)
_QUALITY_RELEVANT_CONDITION = "needs.changes.outputs.quality_relevant == 'true'"
_QUALITY_PREDICATE = "predicate-quantifier: every"
_QUALITY_NON_DOCS_REQUIRED_GLOBS = (
    "**",
    "!docs/**",
    "!**/*.md",
)
_QUALITY_GUARDRAIL_DOCS_REQUIRED_GLOBS = (
    ".github/pull_request_template.md",
    ".github/copilot-instructions.md",
    "docs/adr/**",
    "docs/technical/dev/adr-enforcement.md",
)
_PR_GATE_SKIPPED_QUALITY_GUARD = (
    '[ "$quality_result" = "skipped" ] && [ "$quality_relevant" != "false" ]'
)
_QUALITY_ONLY_OUTPUT = "quality_only: ${{ steps.filter.outputs.quality_only }}"
_QUALITY_ONLY_REQUIRED_GLOBS = (
    "scripts/polaris-aws-range/**",
    "scenario-dev/polaris/tests/**",
)
_PORTAL_IMAGE_OUTPUT = "portal_image: ${{ steps.filter.outputs.portal_image }}"
_PORTAL_IMAGE_DEPLOY_CONDITION = "needs.changes.outputs.portal_image == 'true'"
_PORTAL_IMAGE_REQUIRED_GLOB = "shifter/shifter_platform/**"
_PORTAL_IMAGE_BUILD_INPUT = "inputs.portal_image_changes"


def _platform_app_source_globs(deploy_text: str) -> list[str]:
    """Return app-source globs wrongly present in the `shifter_platform` filter."""
    platform_block = _paths_filter_block(deploy_text, "shifter_platform")
    return [
        glob
        for glob in _filter_globs(platform_block)
        if glob == "shifter/**" or glob.startswith("shifter/")
    ]


def _check_deploy_workflow_plan_routing(deploy_text: str) -> list[Violation]:
    """Keep the Quality classifiers and their consuming job conditions intact."""
    violations: list[Violation] = []
    app_source_globs = _platform_app_source_globs(deploy_text)
    if app_source_globs:
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "`shifter_platform` must not include app-source globs under `shifter/`; "
                f"found {', '.join(app_source_globs)}",
            )
        )

    changes_block = _workflow_job_block(deploy_text, "changes")
    quality_block = _workflow_job_block(deploy_text, "quality")
    pr_gate_block = _workflow_job_block(deploy_text, "pr-gate")
    non_docs_block = _paths_filter_block(deploy_text, "non_docs")
    guardrail_docs_block = _paths_filter_block(deploy_text, "guardrail_docs")

    if not _active_line_contains(changes_block, _QUALITY_RELEVANT_OUTPUT):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Quality routing must retain a `quality_relevant` changes-job output "
                "that combines the non-docs and guardrail-docs classifiers",
            )
        )
    elif not non_docs_block:
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Quality routing must retain a `non_docs` filter so ordinary docs-only "
                "diffs are the only general Quality skip path",
            )
        )
    elif not _active_line_contains(changes_block, _QUALITY_PREDICATE):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The `non_docs` Quality classifier must use "
                f"`{_QUALITY_PREDICATE}` so exclusion globs are honored together",
            )
        )
    elif missing_non_doc_globs := [
        glob
        for glob in _QUALITY_NON_DOCS_REQUIRED_GLOBS
        if not _block_contains_glob(non_docs_block, glob)
    ]:
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The `non_docs` Quality classifier is missing required docs-only "
                f"exclusion globs: {', '.join(missing_non_doc_globs)}",
            )
        )
    elif not guardrail_docs_block:
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Quality routing must retain a `guardrail_docs` filter so ADR and "
                "enforcement-doc changes still run Quality",
            )
        )
    elif missing_guardrail_globs := [
        glob
        for glob in _QUALITY_GUARDRAIL_DOCS_REQUIRED_GLOBS
        if not _block_contains_glob(guardrail_docs_block, glob)
    ]:
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The `guardrail_docs` Quality classifier is missing required "
                f"guardrail paths: {', '.join(missing_guardrail_globs)}",
            )
        )
    elif not _active_line_contains(quality_block, _QUALITY_RELEVANT_CONDITION):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The Quality job must include "
                f"`{_QUALITY_RELEVANT_CONDITION}` so non-docs and guardrail-docs "
                "changes run Quality",
            )
        )
    elif not pr_gate_block or not _active_line_contains(
        pr_gate_block, _PR_GATE_SKIPPED_QUALITY_GUARD
    ):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "PR Gate must reject skipped Quality unless `quality_relevant` is false, "
                "so skipped Quality is accepted only for ordinary docs-only changes",
            )
        )
    return violations


def _check_deploy_workflow_quality_only_routing(deploy_text: str) -> list[Violation]:
    """Require non-deploy test-support paths to remain categorized."""
    quality_only_block = _paths_filter_block(deploy_text, "quality_only")
    changes_block = _workflow_job_block(deploy_text, "changes")
    if not quality_only_block or not _active_line_contains(changes_block, _QUALITY_ONLY_OUTPUT):
        return [
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Non-deploy test-support changes must retain a `quality_only` "
                "filter/output; missing the filter or changes-job output",
            )
        ]

    missing_globs = [
        glob
        for glob in _QUALITY_ONLY_REQUIRED_GLOBS
        if not _block_contains_glob(quality_only_block, glob)
    ]
    if missing_globs:
        return [
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "`quality_only` must include "
                f"{', '.join(missing_globs)} so orphaned support test suites stay "
                "categorized without triggering deploy jobs",
            )
        ]
    return []


def _check_deploy_workflow_portal_image_routing(deploy_text: str) -> list[Violation]:
    """Require the portal-image deploy trigger restored by #913.

    Application-code changes must reach the portal build/deploy path through
    a dedicated `portal_image` filter, without widening the Terraform-scoped
    `shifter_platform` plan trigger.
    """
    portal_block = _paths_filter_block(deploy_text, "portal_image")
    changes_block = _workflow_job_block(deploy_text, "changes")
    platform_job_block = _workflow_job_block(deploy_text, "shifter_platform")
    if not portal_block or not _active_line_contains(changes_block, _PORTAL_IMAGE_OUTPUT):
        message = (
            "Portal application changes must retain a `portal_image` filter/output "
            "so app-only pushes still build and deploy the portal image (#913); "
            "missing the filter or changes-job output"
        )
    elif not _block_contains_glob(portal_block, _PORTAL_IMAGE_REQUIRED_GLOB):
        message = (
            f"`portal_image` must include `{_PORTAL_IMAGE_REQUIRED_GLOB}` so portal "
            "application changes trigger the image build/deploy path"
        )
    elif not _active_line_contains(platform_job_block, _PORTAL_IMAGE_DEPLOY_CONDITION):
        message = (
            "The `shifter_platform` job must include "
            f"`{_PORTAL_IMAGE_DEPLOY_CONDITION}` so application-code pushes still "
            "invoke the portal build/deploy workflow"
        )
    else:
        return []
    return [_plan_scope_violation(_DEPLOY_WORKFLOW_PATH, message)]


def _check_platform_build_portal_image_gate(platform_text: str) -> list[Violation]:
    """Require the platform build job to gate on the portal-image input (#913)."""
    build_block = _workflow_job_block(platform_text, "build")
    if not build_block or not _active_line_contains(build_block, _PORTAL_IMAGE_BUILD_INPUT):
        return [
            _plan_scope_violation(
                _PLATFORM_WORKFLOW_PATH,
                f"The `build` job must gate on `{_PORTAL_IMAGE_BUILD_INPUT}` so app-only "
                "changes build and deploy the portal image without running Terraform",
            )
        ]
    return []
