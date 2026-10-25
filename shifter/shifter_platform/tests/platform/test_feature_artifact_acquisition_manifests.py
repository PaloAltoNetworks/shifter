"""The acquisition admission policy admits exactly the Job the launcher builds (#2463)."""

from __future__ import annotations

import copy
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from engine.services._feature_artifact_launcher import _job_env
from shared.cloud.feature_artifact_jobs import (
    ACQUISITION_CONTAINER,
    acquisition_args,
    acquisition_task_profile,
)
from shared.cloud.kubernetes._job_manifest import _build_env, _build_job
from tests.platform.test_gcp_job_launcher_manifests import _semantic_policy_allows
from tests.shared.cloud.test_gcp_task_runner import _make_fake_k8s_client

CHART = Path(__file__).resolve().parents[4] / "platform" / "charts" / "shifter"
IMAGE = "registry.example/shifter/platform@sha256:" + "b" * 64
LAUNCHER = "system:serviceaccount:shifter-platform:provisioner-launcher"
POLICY = "restrict-feature-artifact-jobs"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is required to render the chart")


def _render(values_file: str, *overrides: str) -> list[dict[str, Any]]:
    args = ["helm", "template", "contract-test", str(CHART), "-f", str(CHART / values_file)]
    for override in overrides:
        args += ["--set", override]
    rendered = subprocess.run(args, check=True, capture_output=True, text=True).stdout  # noqa: S603
    return [doc for doc in yaml.safe_load_all(rendered) if isinstance(doc, dict)]


def _policy() -> dict[str, Any]:
    documents = _render(
        "values-aws-dev.yaml", "capabilities.featureArtifactAcquisition=true", f"images.platform={IMAGE}"
    )
    return next(
        doc for doc in documents if doc.get("kind") == "ValidatingAdmissionPolicy" and doc["metadata"]["name"] == POLICY
    )


def _to_kubernetes_json(value: Any) -> Any:
    """Serialize the fake client's objects the way kubernetes.client does (camelCase keys)."""
    if isinstance(value, SimpleNamespace):
        return {_camel(key): _to_kubernetes_json(item) for key, item in vars(value).items() if item is not None}
    if isinstance(value, list):
        return [_to_kubernetes_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_kubernetes_json(item) for key, item in value.items()}
    return value


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _launcher_job() -> dict[str, Any]:
    """The Job exactly as the launcher's task runner builds it."""
    client = _make_fake_k8s_client()
    client.V1ResourceRequirements = lambda **kwargs: SimpleNamespace(**kwargs)
    args = acquisition_args("claude-code", "2.1.289", "linux-x64-glibc")
    env = _build_env(client, _job_env())
    job = _build_job(
        client,
        IMAGE,
        ACQUISITION_CONTAINER,
        args,
        env,
        acquisition_task_profile(),
        "11111111-1111-1111-1111-111111111111",
    )
    return _to_kubernetes_json(job)


def _allows(policy: dict[str, Any], job: dict[str, Any], username: str = LAUNCHER) -> bool:
    return _semantic_policy_allows(policy, username, job, IMAGE, parameter_data={})


def _container(job: dict[str, Any]) -> dict[str, Any]:
    return job["spec"]["template"]["spec"]["containers"][0]


@pytest.mark.django_db
@pytest.mark.parametrize("region", ["us-east-2", ""], ids=["eks-with-region", "gke-without-region"])
def test_policy_admits_the_job_with_or_without_a_region(region, monkeypatch):
    """GKE has no AWS_REGION; the launcher omits it rather than send an empty value."""
    monkeypatch.setenv("AWS_REGION", region)
    job = _launcher_job()
    names = {entry["name"] for entry in _container(job)["env"]}
    assert ("AWS_REGION" in names) is bool(region)
    assert _allows(_policy(), job)


@pytest.mark.django_db
def test_policy_requires_every_provider_neutral_input(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    policy = _policy()
    job = _launcher_job()
    for required in ("CLOUD_PROVIDER", "STORAGE_BUCKET_NAME", "RAES_CONTENT_DELIVERY_PREFIX", "HOME", "TMPDIR"):
        candidate = copy.deepcopy(job)
        _container(candidate)["env"] = [e for e in _container(candidate)["env"] if e["name"] != required]
        assert not _allows(policy, candidate), required
    empty = copy.deepcopy(job)
    _container(empty)["env"].append({"name": "AWS_REGION"})  # an empty value arrives value-less
    assert not _allows(policy, empty)


@pytest.mark.django_db
def test_policy_admits_the_launcher_built_job_and_denies_tampering():
    policy = _policy()
    job = _launcher_job()
    assert _allows(policy, job)
    assert not _allows(policy, job, username="system:serviceaccount:shifter-platform:portal")

    def tampered(mutate) -> dict[str, Any]:
        candidate = copy.deepcopy(job)
        mutate(candidate)
        return candidate

    mutations = {
        "image": lambda j: _container(j).__setitem__("image", "registry.example/other@sha256:" + "c" * 64),
        "command": lambda j: _container(j).__setitem__("command", ["sh", "-c", "curl evil"]),
        "entrypoint-kept": lambda j: _container(j).pop("command"),
        "extra-env": lambda j: _container(j)["env"].append({"name": "AWS_ACCESS_KEY_ID", "value": "x"}),
        "secret-env": lambda j: _container(j)["env"].__setitem__(
            0, {"name": "AWS_REGION", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}}
        ),
        "arg-grammar": lambda j: _container(j)["args"].__setitem__(1, "latest"),
        "extra-arg": lambda j: _container(j)["args"].append("--unsafe"),
        "identity": lambda j: j["spec"]["template"]["spec"].__setitem__("serviceAccountName", "provisioner"),
        "budget": lambda j: j["spec"].__setitem__("activeDeadlineSeconds", 86400),
        "writable-root": lambda j: _container(j)["securityContext"].__setitem__("readOnlyRootFilesystem", False),
        "scratch-elsewhere": lambda j: _container(j)["volumeMounts"][0].__setitem__("mountPath", "/scratch"),
    }
    for name, mutate in mutations.items():
        assert not _allows(policy, tampered(mutate)), name


def test_acquisition_egress_identity_and_metadata_follow_the_values():
    """Egress comes only from featureArtifactAcquisition values; identity annotations
    merge with an IRSA role; Workload Identity's metadata server stays reachable."""
    documents = _render(
        "values-gcp-dev.yaml",
        "capabilities.kubernetesJobLauncher=true",
        "capabilities.featureArtifactAcquisition=true",
        "featureArtifactAcquisition.egressCidrs={0.0.0.0/0}",
        "featureArtifactAcquisition.egressExcept={10.0.0.0/8,172.16.0.0/12}",
        "featureArtifactAcquisition.serviceAccountAnnotations.iam\\.gke\\.io/gcp-service-account=acquirer@example.iam.gserviceaccount.com",
        f"images.platform={IMAGE}",
    )
    policies = {
        doc["metadata"]["name"]: doc
        for doc in documents
        if doc.get("kind") == "NetworkPolicy" and doc["metadata"].get("namespace") == "shifter-acquisition"
    }
    https = policies["acquisition-https-egress"]["spec"]["egress"][0]
    assert https["to"] == [{"ipBlock": {"cidr": "0.0.0.0/0", "except": ["10.0.0.0/8", "172.16.0.0/12"]}}]
    assert https["ports"] == [{"protocol": "TCP", "port": 443}]
    metadata = policies["acquisition-metadata-server-egress"]["spec"]["egress"][0]
    assert metadata["to"] == [{"ipBlock": {"cidr": "169.254.169.254/32"}}]

    account = next(
        doc
        for doc in documents
        if doc.get("kind") == "ServiceAccount" and doc["metadata"]["name"] == "artifact-acquirer"
    )
    assert account["metadata"]["annotations"] == {
        "iam.gke.io/gcp-service-account": "acquirer@example.iam.gserviceaccount.com"
    }


def test_gke_profiles_never_render_acquisition_resources():
    for values_file in ("values-gcp-dev.yaml", "values-gcp-prod.yaml"):
        documents = _render(values_file)
        assert not [doc for doc in documents if doc.get("metadata", {}).get("namespace") == "shifter-acquisition"]
        assert not [doc for doc in documents if doc.get("metadata", {}).get("name") == POLICY]
