"""Verify installed WIF and account policies before reporting bootstrap success."""

from __future__ import annotations

from pathlib import Path

from installation.deployment_inventory_types import DeploymentRecord

from inventory_bootstrap import expected_identity_policy, private_json, verify_identity_plan


def verify_installed_identity(record: DeploymentRecord, number: str, env: dict[str, str], product_root: Path) -> None:
    """Compare installed provider and service-account trust to the exact contract."""
    expected = expected_identity_policy(record, number)
    project = expected["project_id"]
    pool = expected["name_prefix"] + "-github"
    provider = private_json(
        [
            "gcloud",
            "iam",
            "workload-identity-pools",
            "providers",
            "describe",
            "github",
            "--workload-identity-pool",
            pool,
            "--location",
            "global",
            "--project",
            project,
            "--format=json",
        ],
        env=env,
    )
    # Translate the provider API representation into the verifier's existing
    # resolved-policy contract. The same exact comparison gates plan and readback.
    value = {
        "project": project,
        "workload_identity_pool_id": pool,
        "workload_identity_pool_provider_id": "github",
        "attribute_condition": provider.get("attributeCondition"),
        "attribute_mapping": provider.get("attributeMapping"),
        "disabled": provider.get("disabled", False),
        "oidc": [
            {
                "issuer_uri": provider.get("oidc", {}).get("issuerUri"),
                "allowed_audiences": provider.get("oidc", {}).get("allowedAudiences", []),
            }
        ],
        "aws": provider.get("aws"),
        "saml": provider.get("saml"),
    }
    resources = [
        {"type": "google_iam_workload_identity_pool_provider", "change": {"actions": ["no-op"], "after": value}}
    ]
    for account in expected["service_accounts"].values():
        policy = private_json(
            [
                "gcloud",
                "iam",
                "service-accounts",
                "get-iam-policy",
                account.rsplit("/", 1)[-1],
                "--project",
                project,
                "--format=json",
            ],
            env=env,
        )
        for binding in policy.get("bindings", []):
            for member in binding.get("members", []):
                resources.append(
                    {
                        "type": "google_service_account_iam_member",
                        "change": {
                            "actions": ["no-op"],
                            "after": {
                                "service_account_id": account,
                                "role": binding.get("role"),
                                "member": member,
                            },
                        },
                    }
                )
    verify_identity_plan({"resource_changes": resources}, record, number, product_root)
