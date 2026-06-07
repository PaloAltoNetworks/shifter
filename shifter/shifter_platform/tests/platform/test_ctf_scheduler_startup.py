"""CTF scheduler deployment startup invariants."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
AWS_USER_DATA = REPO_ROOT / "platform" / "terraform" / "modules" / "portal" / "ec2" / "user_data.sh"
AWS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "_shifter-platform.yml"
BASE_MANIFEST_DIR = REPO_ROOT / "platform" / "k8s" / "gcp" / "base"
CHART_DIR = REPO_ROOT / "platform" / "charts" / "shifter"
COMPOSE_FILE = REPO_ROOT / "shifter" / "shifter_platform" / "docker-compose.yml"
SCHEDULER_COMMAND = ["python", "manage.py", "run_ctf_scheduler"]
SCHEDULER_NAME = "ctf-scheduler"


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


def _deployment(documents: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for document in documents:
        if document.get("kind") == "Deployment" and document["metadata"]["name"] == name:
            return document
    raise AssertionError(f"missing Deployment/{name}")


def _scheduler_container(deployment: dict[str, Any]) -> dict[str, Any]:
    containers = deployment["spec"]["template"]["spec"]["containers"]
    for container in containers:
        if container["name"] == SCHEDULER_NAME:
            return container
    raise AssertionError(f"missing {SCHEDULER_NAME} container")


def test_local_compose_starts_ctf_scheduler_service() -> None:
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    service = compose["services"][SCHEDULER_NAME]

    assert service["command"] == " ".join(SCHEDULER_COMMAND)
    assert service["restart"] == "always"
    assert service["depends_on"]["db"]["condition"] == "service_healthy"
    assert "ctf-scheduler-heartbeat" in " ".join(service["healthcheck"]["test"])


@pytest.mark.parametrize("path", [AWS_USER_DATA, AWS_WORKFLOW])
def test_aws_deploy_paths_start_ctf_scheduler_container(path: Path) -> None:
    deployment_text = path.read_text(encoding="utf-8")

    assert f"docker stop portal worker-cms worker-engine worker-mc {SCHEDULER_NAME}" in deployment_text
    assert f"docker rm portal worker-cms worker-engine worker-mc {SCHEDULER_NAME}" in deployment_text
    assert f"docker run -d --name {SCHEDULER_NAME} --restart unless-stopped" in deployment_text
    assert " ".join(SCHEDULER_COMMAND) in deployment_text


@pytest.mark.parametrize(
    ("source_name", "loader"),
    [
        ("base", _load_base_documents),
        ("helm", _load_helm_documents),
    ],
)
def test_gcp_scheduler_deployment_runs_and_can_launch_jobs(source_name: str, loader: Any) -> None:
    deployment = _deployment(loader(), SCHEDULER_NAME)
    pod_spec = deployment["spec"]["template"]["spec"]
    container = _scheduler_container(deployment)

    assert deployment["spec"]["replicas"] == 1, f"{source_name} should run one scheduler by default"
    assert container["args"] == SCHEDULER_COMMAND
    assert "ctf-scheduler-heartbeat" in " ".join(container["livenessProbe"]["exec"]["command"])
    assert pod_spec["serviceAccountName"] == SCHEDULER_NAME
    assert pod_spec["automountServiceAccountToken"] is True, (
        f"{source_name} scheduler must mount its dedicated token so due CTF spin-up tasks can submit GCP Jobs"
    )
