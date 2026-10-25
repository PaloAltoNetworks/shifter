"""Admission evaluates actual worker manifests and rejects privilege overrides."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from celpy import CELEvalError

from shared.cloud.kubernetes._job_manifest import _build_env, _build_job
from shared.cloud.runtime_plugins import PLUGIN_CONTAINER, plugin_task_profile
from tests.platform.test_gcp_job_launcher_manifests import _load_helm_documents
from tests.shared.cloud.test_preparation_installation import ManifestClient, allows

BASE = Path(__file__).resolve().parents[5] / "platform/k8s/gcp/base/runtime-plugins.yaml"


def resources():
    return list(yaml.safe_load_all(BASE.read_text()))


def test_helm_and_static_plugin_boundaries_match():
    rendered = _load_helm_documents()
    for expected in resources():
        actual = next(
            item
            for item in rendered
            if item["kind"] == expected["kind"] and item["metadata"]["name"] == expected["metadata"]["name"]
        )
        assert actual == expected


@pytest.fixture
def policy():
    return next(item for item in resources() if item["kind"] == "ValidatingAdmissionPolicy")


@pytest.fixture
def job():
    client = ManifestClient()
    env = _build_env(client, {"SHIFTER_PLUGIN_INPUT": "private invocation"}, "runtime-plugin-secrets-" + "1" * 16)
    return _build_job(
        client,
        "registry.example.test/plugin@sha256:" + "a" * 64,
        PLUGIN_CONTAINER,
        [],
        env,
        plugin_task_profile(),
        str(uuid4()),
    )


def accepted(policy, job):
    try:
        return allows(policy, job, "system:serviceaccount:shifter-platform:provisioner-launcher")
    except CELEvalError:
        return False


def test_actual_worker_profile_is_admitted_without_cloud_credentials(policy, job):
    assert accepted(policy, job)
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["env"] == [
        {
            "name": "SHIFTER_PLUGIN_INPUT",
            "valueFrom": {
                "secretKeyRef": {"name": "runtime-plugin-secrets-" + "1" * 16, "key": "SHIFTER_PLUGIN_INPUT"}
            },
        }
    ]


@pytest.mark.parametrize(
    "override", ["identity", "token", "volume", "env", "root", "memory", "deadline", "image", "sidecar"]
)
def test_privilege_and_resource_overrides_are_denied(policy, job, override):
    changed = deepcopy(job)
    pod = changed["spec"]["template"]["spec"]
    container = pod["containers"][0]
    if override == "identity":
        pod["serviceAccountName"] = "provisioner"
    elif override == "token":
        pod["automountServiceAccountToken"] = True
    elif override == "volume":
        pod["volumes"].append({"name": "credentials", "secret": {"secretName": "other"}})
    elif override == "env":
        container["env"].append({"name": "DB_PASSWORD", "value": "example"})
    elif override == "root":
        container["securityContext"]["runAsUser"] = 0
    elif override == "memory":
        container["resources"]["limits"]["memory"] = "8Gi"
    elif override == "deadline":
        changed["spec"]["activeDeadlineSeconds"] = 3600
    elif override == "image":
        container["image"] = "registry.example.test/plugin:latest"
    else:
        pod["containers"].append(deepcopy(container))
    assert not accepted(policy, changed)


def test_namespace_blocks_all_network_and_worker_has_no_cloud_binding():
    docs = resources()
    network = next(item for item in docs if item["kind"] == "NetworkPolicy")
    assert network["spec"] == {"podSelector": {}, "policyTypes": ["Ingress", "Egress"], "ingress": [], "egress": []}
    worker = next(item for item in docs if item["kind"] == "ServiceAccount")
    assert not worker["automountServiceAccountToken"]
    assert not worker["metadata"].get("annotations")
    bindings = [item for item in docs if item["kind"] == "RoleBinding"]
    assert all(subject["name"] != "plugin-worker" for binding in bindings for subject in binding["subjects"])


def test_plugin_object_quota_has_burst_headroom_without_raising_execution_cap():
    quota = next(item for item in resources() if item["kind"] == "ResourceQuota")
    hard = quota["spec"]["hard"]
    assert hard["count/jobs.batch"] == "512"
    assert hard["count/secrets"] == "768"
    assert hard["pods"] == "16"
    assert hard["requests.cpu"] == "2"
    assert hard["limits.memory"] == "4Gi"


def test_job_admission_constrains_creation_without_blocking_controller_cleanup(policy):
    """Kubernetes controllers must be able to remove deletion finalizers."""
    rules = policy["spec"]["matchConstraints"]["resourceRules"]
    job_rule = next(rule for rule in rules if rule["resources"] == ["jobs"])
    assert job_rule["operations"] == ["CREATE"]

    role = next(
        item for item in resources() if item["kind"] == "Role" and item["metadata"]["name"] == "plugin-controller"
    )
    launcher_job_rule = next(rule for rule in role["rules"] if rule["resources"] == ["jobs"])
    assert launcher_job_rule["verbs"] == ["create", "get", "delete"]
    assert not {"update", "patch"}.intersection(launcher_job_rule["verbs"])
    status_rule = next(rule for rule in role["rules"] if rule["resources"] == ["jobs/status"])
    assert status_rule["verbs"] == ["get"]


@pytest.mark.parametrize("runtime", [None, "", "runc", "other"])
def test_default_or_unapproved_runtime_is_denied(policy, job, runtime):
    pod = job["spec"]["template"]["spec"]
    if runtime is None:
        pod.pop("runtimeClassName")
    else:
        pod["runtimeClassName"] = runtime
    assert not accepted(policy, job)


def test_platform_nodes_cannot_receive_plugin_jobs(policy, job):
    pod = job["spec"]["template"]["spec"]
    pod["nodeSelector"] = {"node-restriction.kubernetes.io/shifter-pool": "provisioner"}
    assert not accepted(policy, job)
