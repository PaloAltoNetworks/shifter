"""Fail-closed comparison of saved Terraform trust against authorized inventory."""

from __future__ import annotations

from typing import Any


def _unknown(mask: Any) -> bool:
    if isinstance(mask, dict):
        return any(_unknown(value) for value in mask.values())
    if isinstance(mask, list):
        return any(_unknown(value) for value in mask)
    return mask is True


def _provider_errors(value: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors = []
    required = {
        "attribute_condition": expected["attribute_condition"],
        "project": expected["project_id"],
        "workload_identity_pool_id": expected["name_prefix"] + "-github",
        "workload_identity_pool_provider_id": "github",
    }
    if any(value.get(key) != wanted for key, wanted in required.items()):
        errors.append("Resolved provider differs from authorized exact trust tuples")
    oidc = value.get("oidc")
    if not isinstance(oidc, list) or len(oidc) != 1:
        errors.append("Provider must use exactly one GitHub OIDC issuer")
    elif oidc[0].get("issuer_uri") != "https://token.actions.githubusercontent.com" or oidc[0].get("allowed_audiences"):
        errors.append("Provider must use GitHub issuer and default provider-specific audience")
    if value.get("attribute_mapping", {}).get("google.subject") != "assertion.sub":
        errors.append("Provider subject mapping is not exact")
    if value.get("disabled") is True or value.get("saml") or value.get("aws") or value.get("x509"):
        errors.append("Provider is disabled or has an unexpected identity source")
    return errors


def _expected_bindings(expected: dict[str, Any]) -> set[tuple[str, str]]:
    prefix = (
        "principal://iam.googleapis.com/projects/" + expected["project_number"]
        + "/locations/global/workloadIdentityPools/" + expected["name_prefix"] + "-github/subject/"
    )
    return {
        (expected["service_accounts"][purpose], prefix + subject)
        for purpose, subjects in expected["purpose_subjects"].items() for subject in subjects
    }


def check_resolved_plan(plan: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Require the entire provider/binding set, not the first matching resource.

    `expected` is generated from the authorized common record by the bootstrap
    caller, never loaded from an independently supplied policy file. Existing
    obsolete bindings may be deleted; identity foundations cannot be replaced.
    """
    resources = plan.get("resource_changes")
    if not isinstance(resources, list) or not resources:
        return ["Plan has no inspectable resource changes"]
    errors: list[str] = []
    providers = []
    bindings: list[tuple[str, str]] = []
    for resource in resources:
        kind = resource.get("type", "")
        change = resource.get("change", {})
        actions = change.get("actions", [])
        foundation = kind in {
            "google_iam_workload_identity_pool", "google_iam_workload_identity_pool_provider",
            "google_service_account", "google_storage_bucket", "google_project_iam_custom_role",
        }
        if foundation and "delete" in actions:
            errors.append("Migration would delete or replace an identity foundation")
        if actions == ["delete"]:
            continue
        value = change.get("after")
        if not isinstance(value, dict):
            errors.append("Plan contains unknown resource values")
            continue
        unknown = change.get("after_unknown", {})
        if kind == "google_iam_workload_identity_pool_provider":
            providers.append(value)
            if any(_unknown(unknown.get(k)) for k in ("attribute_condition", "attribute_mapping", "oidc", "project", "aws", "saml", "x509", "disabled")):
                errors.append("Provider trust contains unknown values")
        if kind.startswith("google_service_account_iam_"):
            if kind != "google_service_account_iam_member":
                errors.append("Authoritative service-account IAM policies are outside the purpose contract")
                continue
            if any(_unknown(unknown.get(k)) for k in ("role", "member", "service_account_id")):
                errors.append("Service-account policy contains unknown authority")
            role = value.get("role")
            if role == "roles/iam.workloadIdentityUser":
                bindings.append((value.get("service_account_id", ""), value.get("member", "")))
            else:
                # Build may act as itself; no other purpose can impersonate an
                # identity or change its key. The provider's exact subjects are
                # the only federation grants in this root.
                build = expected["service_accounts"].get("build")
                self_member = "serviceAccount:" + build.rsplit("/", 1)[-1] if build else None
                if not (
                    build and value.get("service_account_id") == build and value.get("member") == self_member
                    and role in {"roles/iam.serviceAccountUser", "roles/iam.serviceAccountTokenCreator"}
                ):
                    errors.append("Unexpected cross-purpose service-account authority")
    if len(providers) != 1:
        errors.append("Plan must contain exactly one inspected WIF provider")
    else:
        errors.extend(_provider_errors(providers[0], expected))
    if len(bindings) != len(set(bindings)) or set(bindings) != _expected_bindings(expected):
        errors.append("Resolved impersonation bindings differ from authorized purposes")
    return errors
