"""Bootstrap reconciliation of exact GitHub execution authority."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from installation.deployment_identity_gcp import subject_prefix
from installation.deployment_inventory_types import DeploymentRecord

from inventory_bootstrap import invalid, private_command, private_json, validate_environment

REPOSITORY_API = "repos/"


def verify_github_actor(record: DeploymentRecord, actor: str, *, inventory_repository: str | None = None) -> None:
    """Verify the named actor and immutable private repository authority."""
    user = private_json(["gh", "api", "user"])
    repository = private_json(["gh", "api", REPOSITORY_API + record.execution.repository])
    if (
        user.get("login") != actor
        or not repository.get("permissions", {}).get("admin")
        or repository.get("private") is not True
        or repository.get("full_name") != record.execution.repository
        or str(repository.get("id")) != record.execution.repository_id
        or str(repository.get("owner", {}).get("id")) != record.execution.owner_id
    ):
        raise invalid("GitHub actor, repository IDs or bootstrap administration authority do not match")
    if inventory_repository and inventory_repository != record.execution.repository:
        _verify_inventory_source(inventory_repository)


def _verify_inventory_source(repository: str) -> None:
    """Require an independently hosted inventory to be private and readable."""
    inventory = private_json(["gh", "api", REPOSITORY_API + repository])
    if (
        inventory.get("private") is not True
        or inventory.get("full_name") != repository
        or inventory.get("permissions", {}).get("pull") is not True
    ):
        raise invalid("inventory source must be the exact private repository readable by the bootstrap actor")


def reconcile_subject(record: DeploymentRecord, *, apply: bool) -> None:
    """Reconcile and verify the explicitly reviewed GitHub subject format.

    Newly created repositories require immutable subjects. An incompatible
    inventory fails readback; bootstrap never silently substitutes a format.
    """
    immutable = record.execution.subject_format == "immutable"
    endpoint = f"repos/{record.execution.repository}/actions/oidc/customization/sub"
    headers = ["-H", "X-GitHub-Api-Version: 2026-03-10"]
    if apply:
        private_command(
            ["gh", "api", *headers, "--method", "PUT", endpoint, "--input", "-"],
            stdin=json.dumps({"use_default": True, "use_immutable_subject": immutable}),
        )
    template = private_json(["gh", "api", *headers, endpoint])
    if (
        template.get("use_default") is not True
        or template.get("use_immutable_subject") is not immutable
        or template.get("sub_claim_prefix") != subject_prefix(record.execution)
    ):
        raise invalid(
            "OIDC subject readback differs from inventory; review execution.subject_format and repository IDs"
        )


def execution_environments(record: DeploymentRecord) -> dict[str, set[str]]:
    """Collect the exact branch names allowed by each execution Environment."""
    environments: dict[str, set[str]] = {}
    for contexts in record.execution.purposes.values():
        for context in contexts:
            environments.setdefault(context.environment, set()).add(context.ref.removeprefix("refs/heads/"))
    return environments


def _branch_policies(endpoint: str) -> list[dict[str, Any]]:
    """Read all branch policy pages for one execution Environment."""
    result = private_json(["gh", "api", "--paginate", "--slurp", endpoint + "/deployment-branch-policies"])
    return [policy for page in result for policy in page.get("branch_policies", [])]


def _preserved_protections(current: dict[str, Any]) -> dict[str, Any]:
    """Project existing approval controls into the Environment update payload."""
    result = {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
    if "can_admins_bypass" in current:
        result["can_admins_bypass"] = current["can_admins_bypass"]
    for rule in current.get("protection_rules", []):
        if rule.get("type") == "wait_timer":
            result["wait_timer"] = rule["wait_timer"]
        elif rule.get("type") == "required_reviewers":
            result["prevent_self_review"] = rule.get("prevent_self_review", False)
            result["reviewers"] = sorted(
                (
                    {"type": reviewer["type"], "id": reviewer["reviewer"]["id"]}
                    for reviewer in rule.get("reviewers", [])
                ),
                key=lambda reviewer: (reviewer["type"], reviewer["id"]),
            )
    return result


def _reconcile_branch_policies(endpoint: str, branches: set[str]) -> None:
    """Remove excess policies and create missing exact branch entries."""
    policies = _branch_policies(endpoint)
    for policy in policies:
        if policy.get("type") != "branch" or policy.get("name") not in branches:
            # DELETE responses have no JSON body.
            private_command(
                [
                    "gh",
                    "api",
                    "--method",
                    "DELETE",
                    endpoint + "/deployment-branch-policies/" + str(policy["id"]),
                ]
            )
    present = {policy["name"] for policy in policies if policy.get("type") == "branch"}
    for branch in sorted(branches - present):
        private_json(
            ["gh", "api", "--method", "POST", endpoint + "/deployment-branch-policies", "--input", "-"],
            stdin=json.dumps({"name": branch, "type": "branch"}),
        )


def _verify_protected_branches(repo: str, branches: set[str]) -> None:
    """Require every authorized execution ref to have branch protection."""
    for branch in sorted(branches):
        details = private_json(["gh", "api", repo + "/branches/" + quote(branch, safe="")])
        if details.get("protected") is not True:
            raise invalid("execution ref is not a protected branch")


def reconcile_environments(record: DeploymentRecord, *, apply: bool) -> None:
    """Protect/read back Environments before any WIF trust becomes usable.

    Existing approval and wait policies are preserved. Mutations use explicit
    bootstrap authority; the read-only path requires already-correct policies.
    """
    repo = REPOSITORY_API + record.execution.repository
    pages = private_json(["gh", "api", "--paginate", "--slurp", repo + "/environments"])
    existing = {entry["name"].lower(): entry for page in pages for entry in page.get("environments", [])}
    for name, branches in sorted(execution_environments(record).items()):
        _verify_protected_branches(repo, branches)
        endpoint = repo + "/environments/" + quote(name, safe="")
        expected_protections = _preserved_protections(existing.get(name.lower(), {}))
        if apply:
            private_json(
                ["gh", "api", "--method", "PUT", endpoint, "--input", "-"],
                stdin=json.dumps(expected_protections),
            )
            _reconcile_branch_policies(endpoint, branches)
        policy = private_json(["gh", "api", endpoint])
        validate_environment(policy, _branch_policies(endpoint), branches)
        observed_protections = _preserved_protections(policy)
        if any(observed_protections.get(key) != value for key, value in expected_protections.items()):
            raise invalid("execution Environment approval protections changed during reconciliation")


def publish_execution_bindings(record: DeploymentRecord, project_number: str) -> None:
    """Reconcile/read back non-secret identity locators in their exact Environment."""
    from inventory_bootstrap import expected_identity_policy

    expected = expected_identity_policy(record, project_number)
    provider = (
        f"projects/{project_number}/locations/global/workloadIdentityPools/"
        f"{record.gcp.name_prefix}-github/providers/github"
    )
    accounts = expected["service_accounts"]
    for purpose, contexts in record.execution.purposes.items():
        own = accounts[purpose].rsplit("/", 1)[-1]
        other = next(
            (value.rsplit("/", 1)[-1] for key, value in accounts.items() if key != purpose),
            "denied-purpose@" + record.installation.settings["project_id"] + ".iam.gserviceaccount.com",
        )
        values = {"GCP_WIF_PROVIDER": provider, "GCP_SERVICE_ACCOUNT": own, "GCP_DENIED_SERVICE_ACCOUNT": other}
        for environment in sorted({context.environment for context in contexts}):
            for name, value in values.items():
                private_command(
                    ["gh", "variable", "set", name, "--repo", record.execution.repository, "--env", environment],
                    stdin=value,
                )
                endpoint = (
                    f"repos/{record.execution.repository}/environments/{quote(environment, safe='')}/variables/{name}"
                )
                if private_json(["gh", "api", endpoint]).get("value") != value:
                    raise invalid("execution identity variable readback differs from bootstrap")
