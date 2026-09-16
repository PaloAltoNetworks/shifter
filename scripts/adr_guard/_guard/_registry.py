"""Deterministic check registry: CHECKS and CHECK_LEVELS."""
from __future__ import annotations

from .checks.adr_registry import (
    check_adr_registry,
)
from .checks.boundary_mock import (
    check_boundary_mock_policy,
)
from .checks.cloud_identifiers import (
    check_mission_control_no_flag_literals,
    check_no_live_cloud_identifiers,
    check_no_terraform_operational_placeholders,
)
from .checks.complexity import (
    check_python_complexity_gate,
)
from .checks.deploy_workflow import (
    check_deploy_runner_exposure,
    check_deploy_verification_fail_loud,
    check_deploy_workflow_plan_scope,
    check_github_oidc_no_admin_access,
    check_global_iam_drift_check,
    check_platform_renders_deploy_tfvars,
    check_portal_deploy_mode_source_of_truth,
    check_workflow_action_sha_pinning,
)
from .checks.documentation import (
    check_documentation_coverage,
    check_guardrail_docs,
    check_lilrae_identity_boundary,
    check_no_agent_attribution,
)
from .checks.eks_cross_stack_sourcing import (
    check_eks_cross_stack_sourcing,
)
from .checks.k8s_security import (
    check_k8s_deployment_security_context,
    check_k8s_network_policy_coverage,
)
from .checks.layer_imports import (
    check_cloud_factory_seam,
    check_cross_layer_model_imports,
    check_installed_apps_classified,
    check_layer_imports,
)
from .checks.mcp_policy import (
    check_mcp_no_shell_exec,
    check_mcp_ops_tls_strict,
)
from .checks.accessibility_baseline import check_accessibility_baseline
from .checks.published_contract import (
    check_published_contract_snapshots_immutable,
)
from .checks.quality_ownership import (
    check_quality_path_ownership,
)
from .checks.secret_hygiene import (
    check_no_plaintext_secrets_in_tfvars,
    check_no_populated_secret_env_files,
    check_no_tracked_generated_artifacts,
)


CHECKS = {
    "adr-registry": check_adr_registry,
    "layer-imports": check_layer_imports,
    "cross-layer-model-imports": check_cross_layer_model_imports,
    "installed-apps-classified": check_installed_apps_classified,
    "guardrail-docs": check_guardrail_docs,
    "cloud-factory-seam": check_cloud_factory_seam,
    "mcp-no-shell-exec": check_mcp_no_shell_exec,
    "k8s-deployment-security-context": check_k8s_deployment_security_context,
    "k8s-network-policy-coverage": check_k8s_network_policy_coverage,
    "no-plaintext-secrets-in-tfvars": check_no_plaintext_secrets_in_tfvars,
    "no-tracked-generated-artifacts": check_no_tracked_generated_artifacts,
    "no-populated-secret-env-files": check_no_populated_secret_env_files,
    "mcp-ops-tls-strict": check_mcp_ops_tls_strict,
    "boundary-mock-policy": check_boundary_mock_policy,
    "python-complexity-gate": check_python_complexity_gate,
    "deploy-workflow-plan-scope": check_deploy_workflow_plan_scope,
    "portal-deploy-mode-source-of-truth": check_portal_deploy_mode_source_of_truth,
    "aws-platform-renders-deploy-tfvars": check_platform_renders_deploy_tfvars,
    "deploy-verification-fail-loud": check_deploy_verification_fail_loud,
    "deploy-workflow-runner-exposure": check_deploy_runner_exposure,
    "workflow-action-sha-pinning": check_workflow_action_sha_pinning,
    "no-live-cloud-identifiers": check_no_live_cloud_identifiers,
    "no-mission-control-flag-literals": check_mission_control_no_flag_literals,
    "no-terraform-operational-placeholders": check_no_terraform_operational_placeholders,
    "github-oidc-no-admin-access": check_github_oidc_no_admin_access,
    "global-iam-drift-check": check_global_iam_drift_check,
    "documentation-coverage": check_documentation_coverage,
    "lilrae-identity-boundary": check_lilrae_identity_boundary,
    "published-contract-snapshots-immutable": check_published_contract_snapshots_immutable,
    "accessibility-baseline": check_accessibility_baseline,
    "no-agent-attribution": check_no_agent_attribution,
    "quality-path-ownership": check_quality_path_ownership,
    "eks-cross-stack-sourcing": check_eks_cross_stack_sourcing,
}
CHECK_LEVELS = {
    "fast": [
        "adr-registry",
        "layer-imports",
        "cross-layer-model-imports",
        "installed-apps-classified",
        "guardrail-docs",
        "cloud-factory-seam",
        "mcp-no-shell-exec",
        "no-plaintext-secrets-in-tfvars",
        "no-tracked-generated-artifacts",
        "no-populated-secret-env-files",
        "mcp-ops-tls-strict",
        "boundary-mock-policy",
        "python-complexity-gate",
        "deploy-workflow-plan-scope",
        "portal-deploy-mode-source-of-truth",
        "aws-platform-renders-deploy-tfvars",
        "deploy-verification-fail-loud",
        "deploy-workflow-runner-exposure",
        "workflow-action-sha-pinning",
        "no-live-cloud-identifiers",
        "no-mission-control-flag-literals",
        "no-terraform-operational-placeholders",
        "github-oidc-no-admin-access",
        "global-iam-drift-check",
        "documentation-coverage",
        "lilrae-identity-boundary",
        "published-contract-snapshots-immutable",
        "accessibility-baseline",
        "no-agent-attribution",
        "quality-path-ownership",
        "eks-cross-stack-sourcing",
    ],
    "ci": [
        "adr-registry",
        "layer-imports",
        "cross-layer-model-imports",
        "installed-apps-classified",
        "cloud-factory-seam",
        "mcp-no-shell-exec",
        "k8s-deployment-security-context",
        "k8s-network-policy-coverage",
        "no-plaintext-secrets-in-tfvars",
        "no-tracked-generated-artifacts",
        "no-populated-secret-env-files",
        "mcp-ops-tls-strict",
        "boundary-mock-policy",
        "python-complexity-gate",
        "deploy-workflow-plan-scope",
        "portal-deploy-mode-source-of-truth",
        "aws-platform-renders-deploy-tfvars",
        "deploy-verification-fail-loud",
        "deploy-workflow-runner-exposure",
        "workflow-action-sha-pinning",
        "no-live-cloud-identifiers",
        "no-mission-control-flag-literals",
        "no-terraform-operational-placeholders",
        "github-oidc-no-admin-access",
        "global-iam-drift-check",
        "documentation-coverage",
        "lilrae-identity-boundary",
        "published-contract-snapshots-immutable",
        "accessibility-baseline",
        "no-agent-attribution",
        "quality-path-ownership",
        "eks-cross-stack-sourcing",
    ],
    "all": list(CHECKS),
}
