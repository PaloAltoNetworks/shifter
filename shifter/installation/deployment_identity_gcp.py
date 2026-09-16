"""Pure projection of the common deployment contract into GCP foundation inputs."""

from __future__ import annotations

from typing import Any

from .deployment_inventory_types import DeploymentRecord, ExecutionRepository
from .errors import ConfigIssue, InstallationConfigError


def subject_prefix(execution: ExecutionRepository) -> str:
    """Derive the reviewed GitHub subject format from exact repository identity."""
    if execution.subject_format == "immutable":
        owner, repository = execution.repository.split("/")
        return f"repo:{owner}@{execution.owner_id}/{repository}@{execution.repository_id}"
    return f"repo:{execution.repository}"


def subject(execution: ExecutionRepository, environment: str) -> str:
    """Build the exact GitHub subject for one execution Environment."""
    return f"{subject_prefix(execution)}:environment:{environment}"


def trust_condition(execution: ExecutionRepository) -> str:
    """Render a bounded union of complete tuples, with no cross-product grants."""
    common = [
        f"assertion.repository == '{execution.repository}'",
        f"assertion.repository_id == '{execution.repository_id}'",
        f"assertion.repository_owner_id == '{execution.owner_id}'",
        "assertion.event_name == 'workflow_dispatch'",
    ]
    alternatives = []
    for purpose in sorted(execution.purposes):
        for context in sorted(
            execution.purposes[purpose],
            key=lambda c: (c.environment, c.ref, c.workflow, c.reusable_workflow or ""),
        ):
            clauses = [
                f"assertion.sub == '{subject(execution, context.environment)}'",
                f"assertion.ref == '{context.ref}'",
                f"assertion.workflow_ref == '{execution.repository}/.github/workflows/"
                f"{context.workflow}@{context.ref}'",
            ]
            if context.reusable_workflow:
                clauses.append(f"assertion.job_workflow_ref == '{context.reusable_workflow}'")
            alternatives.append("(" + " && ".join(clauses) + ")")
    result = " && ".join(common) + " && (" + " || ".join(alternatives) + ")"
    if len(result.encode()) > 4096:
        raise InstallationConfigError([ConfigIssue("inventory", "WIF condition exceeds provider limit")])
    return result


def identity_tfvars(record: DeploymentRecord) -> dict[str, Any]:
    """Keep product capability policy out of inventory-supplied Terraform vars."""
    if record.gcp is None:
        raise InstallationConfigError([ConfigIssue("inventory", "GCP identity projection requires GCP inputs")])
    execution = record.execution
    owner, repo = execution.repository.split("/")
    contexts = {
        purpose: [
            {
                "environment": context.environment,
                "ref": context.ref,
                "workflow_ref": f"{execution.repository}/.github/workflows/{context.workflow}@{context.ref}",
                "reusable_workflow_ref": context.reusable_workflow or "",
            }
            for context in sorted(
                execution.purposes[purpose],
                key=lambda c: (c.environment, c.ref, c.workflow, c.reusable_workflow or ""),
            )
        ]
        for purpose in sorted(execution.purposes)
    }
    return {
        "project_id": record.installation.settings["project_id"],
        "environment": record.installation.deployment.name,
        "name_prefix": record.gcp.name_prefix,
        "region": record.installation.settings["region"],
        "github_org": owner,
        "github_repo": repo,
        "github_repository_id": execution.repository_id,
        "github_owner_id": execution.owner_id,
        "github_subject_format": execution.subject_format,
        "purpose_contexts": contexts,
        "release_evidence_bucket_name": record.gcp.evidence_bucket,
        "terraform_state_bucket_name": record.state["platform"].bucket,
        "build_read_bucket_names": sorted(record.gcp.build_read_bucket_names),
        "platform_external_bucket_names": sorted(record.gcp.platform_external_bucket_names),
        "promotion_reader_service_account_email": record.gcp.promotion_reader_service_account_email,
    }
