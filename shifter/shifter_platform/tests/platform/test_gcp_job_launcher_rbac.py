"""GCP job-launcher token mounting and RBAC stay confined to the provisioner launcher.

Split from ``test_gcp_job_launcher_manifests`` (admission policy) along the
behavior boundary; both render the same base manifests and Helm chart.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.platform.test_gcp_job_launcher_manifests import (
    JOB_LAUNCHER_DEPLOYMENTS,
    PLATFORM_NAMESPACE,
    _deployment_pod_spec,
    _deployments,
    _job_launcher_role,
    _load_base_documents,
    _load_helm_documents,
    _metadata_namespace,
    _rbac_subjects,
    _verbs_for,
)


@pytest.mark.parametrize(
    ("source_name", "loader"),
    [
        ("base", _load_base_documents),
        ("helm", _load_helm_documents),
    ],
)
def test_only_gcp_job_launchers_mount_service_account_tokens(
    source_name: str,
    loader: Any,
) -> None:
    documents = loader()
    deployments = _deployments(documents)
    token_mounting_deployments = {
        name
        for name, deployment in deployments.items()
        if _deployment_pod_spec(deployment).get("automountServiceAccountToken") is True
    }

    assert token_mounting_deployments == set(JOB_LAUNCHER_DEPLOYMENTS), (
        f"{source_name} must mount service account tokens only on GCP job-launching Deployments"
    )

    for deployment_name, service_account_name in JOB_LAUNCHER_DEPLOYMENTS.items():
        pod_spec = _deployment_pod_spec(deployments[deployment_name])
        assert pod_spec["serviceAccountName"] == service_account_name
        container = pod_spec["containers"][0]
        assert {entry["name"]: entry["value"] for entry in container["env"]} == {"SHIFTER_PROVISIONER_LAUNCHER": "true"}
        assert pod_spec["automountServiceAccountToken"] is True, (
            f"{source_name} {deployment_name} must mount its service account token "
            "so GCP task launching can use in-cluster Kubernetes auth"
        )

    for deployment_name, deployment in deployments.items():
        if deployment_name in JOB_LAUNCHER_DEPLOYMENTS:
            continue
        pod_spec = _deployment_pod_spec(deployment)
        assert pod_spec["automountServiceAccountToken"] is False, (
            f"{source_name} {deployment_name} must remain tokenless because it does not launch Kubernetes Jobs"
        )


@pytest.mark.parametrize(
    ("source_name", "loader"),
    [
        ("base", _load_base_documents),
        ("helm", _load_helm_documents),
    ],
)
def test_job_launcher_rbac_subjects_match_token_mounting_workloads(
    source_name: str,
    loader: Any,
) -> None:
    documents = loader()
    deployments = _deployments(documents)
    launcher_service_accounts = {
        (_metadata_namespace(deployments[name]), _deployment_pod_spec(deployments[name])["serviceAccountName"])
        for name in JOB_LAUNCHER_DEPLOYMENTS
    }

    assert _rbac_subjects(documents) == launcher_service_accounts, (
        f"{source_name} job-launcher RBAC subjects must exactly match the workloads "
        "that mount service account tokens for Kubernetes Job creation"
    )


@pytest.mark.parametrize("loader", [_load_base_documents, _load_helm_documents])
def test_portal_scheduler_and_general_workers_cannot_mutate_provisioner_objects(loader: Any) -> None:
    documents = loader()
    subjects = _rbac_subjects(documents)
    forbidden = {
        (PLATFORM_NAMESPACE, "portal"),
        (PLATFORM_NAMESPACE, "ctf-scheduler"),
        (PLATFORM_NAMESPACE, "workers"),
    }
    assert subjects.isdisjoint(forbidden)

    launcher = (PLATFORM_NAMESPACE, "provisioner-launcher")
    assert subjects == {launcher}


@pytest.mark.parametrize(
    ("source_name", "loader"),
    [
        ("base", _load_base_documents),
        ("helm", _load_helm_documents),
    ],
)
def test_job_launcher_role_grants_per_job_secret_lifecycle(
    source_name: str,
    loader: Any,
) -> None:
    """The launcher Role must allow the per-Job Secret lifecycle (issue #1185).

    The GCP task runner creates a per-Job Secret for sensitive env vars, patches
    it with the Job ownerReference, and deletes it on the unwind path; it also
    deletes the Job when owner-reference installation fails. Without these verbs
    range launch fails at create_namespaced_secret with a 403.
    """
    role = _job_launcher_role(loader())

    assert _verbs_for(role, "", "secrets") == {"create", "patch", "delete"}, (
        f"{source_name} job-launcher Role must grant create/patch/delete on secrets"
    )
    assert _verbs_for(role, "batch", "jobs") == {"create", "get", "delete"}, (
        f"{source_name} job-launcher Role must grant only create/get/delete on jobs"
    )
    assert _verbs_for(role, "", "pods") == {"list"}, (
        f"{source_name} launcher must list pods to confirm cancellation, without mutation or streaming access"
    )
    assert _verbs_for(role, "", "pods/log") == set()
    assert _verbs_for(role, "", "pods/exec") == set()
