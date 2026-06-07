"""GCP job-launcher Kubernetes manifest invariants."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
BASE_MANIFEST_DIR = REPO_ROOT / "platform" / "k8s" / "gcp" / "base"
CHART_DIR = REPO_ROOT / "platform" / "charts" / "shifter"
DEFAULT_NAMESPACE = "default"

JOB_LAUNCHER_DEPLOYMENTS = {
    "ctf-scheduler": "ctf-scheduler",
    "portal-web": "portal",
    "worker-engine": "workers",
}


def _load_yaml_documents(source: str) -> list[dict[str, Any]]:
    return [document for document in yaml.safe_load_all(source) if isinstance(document, dict)]


def _load_base_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in BASE_MANIFEST_DIR.glob("*.yaml"):
        documents.extend(_load_yaml_documents(path.read_text(encoding="utf-8")))
    return documents


def _load_helm_documents() -> list[dict[str, Any]]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is required to validate rendered chart manifests")

    rendered = subprocess.run(  # noqa: S603
        [helm, "template", "shifter", str(CHART_DIR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return _load_yaml_documents(rendered.stdout)


def _deployments(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    deployments = {}
    for document in documents:
        if document.get("kind") != "Deployment":
            continue
        name = document["metadata"]["name"]
        deployments[name] = document
    return deployments


def _deployment_pod_spec(deployment: dict[str, Any]) -> dict[str, Any]:
    return deployment["spec"]["template"]["spec"]


def _metadata_namespace(document: dict[str, Any]) -> str:
    return document.get("metadata", {}).get("namespace", DEFAULT_NAMESPACE)


def _rbac_subjects(documents: list[dict[str, Any]]) -> set[tuple[str, str]]:
    subjects = set()
    for document in documents:
        if document.get("kind") != "RoleBinding":
            continue
        role_binding_namespace = _metadata_namespace(document)
        role_ref = document.get("roleRef", {})
        if role_ref.get("kind") != "Role" or role_ref.get("name") != "job-launcher":
            continue
        for subject in document.get("subjects", []):
            if subject.get("kind") == "ServiceAccount":
                subjects.add((subject.get("namespace", role_binding_namespace), subject["name"]))
    return subjects


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
